"""Session state store — where the chat keeps its per-session state.

The orchestrator used to keep three dictionaries in the process:

============================  =========================================  ===========
dict                          content                                   eviction
============================  =========================================  ===========
``_session_status``           ``"busy"`` / ``"idle"`` per session      never
``_abort_events``             an ``asyncio.Event`` per running session  on end
``_tool_registries``          the cached tool registry per (session,     **never**
                              wiki)
============================  =========================================  ===========

Two of them are **runtime** state: an ``asyncio.Event`` and a live
registry object cannot be serialised, so they must stay in the process.
What was wrong was not *where* they lived but that they were
**unbounded** — a long-running server grew a dict entry per session
and per (session, wiki) pair, forever.

This module provides the store abstraction for the part that *is*
durable:

* :class:`InMemorySessionStateStore` — the default. Today's behaviour
  plus an entry cap and a TTL, so the dict cannot grow without bound.
* :class:`SqliteSessionStateStore` — persists the state into the
  existing ``chat_sessions.metadata`` blob and holds a **lease**, so
  another instance can see that a session is busy and a crashed
  instance does not leave it stuck in ``"busy"`` forever.

The lease is the industry pattern (Kubernetes Lease, Temporal task
queues, Redis locks): a time-bounded claim that expires on its own.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: How many sessions the in-memory store keeps before evicting the
#: least recently used ones.
DEFAULT_MAX_SESSIONS = 512

#: How long an idle session stays in the in-memory store.
DEFAULT_TTL_SECONDS = 3600.0

#: How long a busy lease is valid in the SQLite store.
DEFAULT_LEASE_SECONDS = 300.0


@dataclass(frozen=True)
class SessionState:
    """The state of one session."""

    status: str = "idle"
    #: Who holds the lease (the instance id), empty when nobody holds it.
    holder: str = ""
    #: When the lease expires (epoch seconds), 0 when there is no lease.
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        """True when the lease is past its deadline."""
        return bool(self.expires_at) and self.expires_at <= time.time()

    @property
    def busy(self) -> bool:
        """True when the session is claimed and the claim is still valid."""
        return self.status == "busy" and not self.expired


@runtime_checkable
class SessionStateStore(Protocol):
    """Where the chat keeps the state of its sessions."""

    def get(self, session_id: str) -> SessionState:
        """The state of one session (idle when unknown)."""

    def set(
        self,
        session_id: str,
        status: str,
        *,
        holder: str = "",
        ttl: float = 0.0,
    ) -> None:
        """Record the state of one session."""

    def clear(self, session_id: str) -> None:
        """Forget one session."""

    def list_all(self) -> dict[str, SessionState]:
        """Every known session state."""


class InMemorySessionStateStore:
    """The default store: the state lives in the process.

    Same semantics as the dict the orchestrator used to keep, with two
    bounds the dict did not have:

    * at most ``max_sessions`` entries — the least recently used ones
      are evicted;
    * an entry is dropped after ``ttl_seconds`` without a touch.
    """

    def __init__(
        self,
        *,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._states: dict[str, SessionState] = {}
        # Two clocks: the wall clock decides the TTL, a monotonic tick
        # decides the recency order. The wall clock is too coarse to
        # order two writes (Windows resolves it to ~15 ms), so it cannot
        # tell "written first" from "written last".
        self._touched: dict[str, float] = {}
        self._order: dict[str, int] = {}
        self._tick = 0
        self._max_sessions = max(1, int(max_sessions))
        self._ttl_seconds = float(ttl_seconds)

    # ── reads ─────────────────────────────────────────────────────

    def get(self, session_id: str) -> SessionState:
        self._evict_expired()
        state = self._states.get(session_id, SessionState())
        if state.expired:
            # A lease that ran out is no lease — the session is idle.
            return SessionState()
        if session_id in self._states:
            # Reading makes the entry the most recently used one.
            self._tick += 1
            self._order[session_id] = self._tick
        return state

    def list_all(self) -> dict[str, SessionState]:
        self._evict_expired()
        return dict(self._states)

    # ── writes ────────────────────────────────────────────────────

    def set(
        self,
        session_id: str,
        status: str,
        *,
        holder: str = "",
        ttl: float = 0.0,
    ) -> None:
        now = time.time()
        expires_at = now + ttl if ttl else 0.0
        self._states[session_id] = SessionState(
            status=status, holder=holder, expires_at=expires_at
        )
        self._touched[session_id] = now
        self._tick += 1
        self._order[session_id] = self._tick
        self._evict_overflow()

    def clear(self, session_id: str) -> None:
        self._states.pop(session_id, None)
        self._touched.pop(session_id, None)
        self._order.pop(session_id, None)

    # ── bounds ────────────────────────────────────────────────────

    def _evict_expired(self) -> None:
        """Drop the entries that were not touched within the TTL."""
        if self._ttl_seconds <= 0:
            return
        now = time.time()
        stale = [
            sid
            for sid, touched in self._touched.items()
            if now - touched > self._ttl_seconds
        ]
        for sid in stale:
            self._states.pop(sid, None)
            self._touched.pop(sid, None)
            self._order.pop(sid, None)

    def _evict_overflow(self) -> None:
        """Drop the least recently used entries above the cap."""
        while len(self._states) > self._max_sessions:
            oldest = min(self._order, key=self._order.get)  # type: ignore[arg-type]
            self._states.pop(oldest, None)
            self._touched.pop(oldest, None)
            self._order.pop(oldest, None)

    def __len__(self) -> int:
        return len(self._states)


class SqliteSessionStateStore:
    """Persists the session state in ``chat_sessions.metadata``.

    The state goes into the metadata blob under the ``session_state``
    key — the same blob the goal state uses — so a session's durable
    state stays in one place.

    A *busy* session is held with a **lease**: the claim carries an
    expiry, so an instance that crashes mid-turn does not leave the
    session busy forever.
    """

    #: The metadata key the state lives under.
    KEY = "session_state"

    def __init__(
        self,
        db: Any,
        *,
        instance_id: str = "",
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._db = db
        self._instance_id = instance_id or uuid.uuid4().hex[:12]
        self._lease_seconds = float(lease_seconds)

    @property
    def instance_id(self) -> str:
        return self._instance_id

    # ── reads ─────────────────────────────────────────────────────

    def get(self, session_id: str) -> SessionState:
        raw = self._read(session_id)
        if not raw:
            return SessionState()
        status = str(raw.get("status", "idle"))
        holder = str(raw.get("holder", ""))
        try:
            expires_at = float(raw.get("expires_at", 0.0))
        except (TypeError, ValueError):
            expires_at = 0.0
        state = SessionState(status=status, holder=holder, expires_at=expires_at)
        if state.expired:
            # A lease that ran out is no lease — the session is idle.
            return SessionState()
        return state

    def list_all(self) -> dict[str, SessionState]:
        """Every session the store knows about.

        The metadata blob is per session, so this scans the session
        rows — callers that need the full list should use it
        sparingly.
        """
        out: dict[str, SessionState] = {}
        for session in self._db.list_chat_sessions():
            sid = session.get("id")
            if not sid:
                continue
            state = self.get(sid)
            if state.status != "idle" or state.holder:
                out[sid] = state
        return out

    # ── writes ────────────────────────────────────────────────────

    def set(
        self,
        session_id: str,
        status: str,
        *,
        holder: str = "",
        ttl: float = 0.0,
    ) -> None:
        expires_at = time.time() + (ttl or self._lease_seconds) if status == "busy" else 0.0
        payload = {
            "status": status,
            "holder": holder,
            "expires_at": expires_at,
        }
        try:
            self._db.update_session_metadata(session_id, **{self.KEY: payload})
        except Exception:
            logger.warning(
                "could not persist the session state for %s", session_id, exc_info=True
            )

    def clear(self, session_id: str) -> None:
        try:
            meta = self._db.get_session_metadata(session_id)
        except Exception:
            logger.warning(
                "could not read the session metadata for %s", session_id, exc_info=True
            )
            return
        if self.KEY not in meta:
            return
        meta.pop(self.KEY, None)
        try:
            self._db.set_session_metadata(session_id, meta)
        except Exception:
            logger.warning(
                "could not clear the session state for %s", session_id, exc_info=True
            )

    # ── lease ─────────────────────────────────────────────────────

    def try_acquire(self, session_id: str, *, ttl: float = 0.0) -> bool:
        """Take the lease on a session.

        False when another instance holds a valid lease — that is the
        multi-instance guard: two servers must not drive the same
        session at the same time.
        """
        current = self.get(session_id)
        if current.busy and current.holder and current.holder != self._instance_id:
            return False
        self.set(
            session_id,
            "busy",
            holder=self._instance_id,
            ttl=ttl or self._lease_seconds,
        )
        return True

    def release(self, session_id: str) -> None:
        """Give the lease back."""
        current = self.get(session_id)
        if current.holder and current.holder != self._instance_id:
            # Somebody else owns it now — leave it alone.
            return
        self.set(session_id, "idle")

    # ── internals ─────────────────────────────────────────────────

    def _read(self, session_id: str) -> dict[str, Any]:
        try:
            meta = self._db.get_session_metadata(session_id)
        except Exception:
            logger.warning(
                "could not read the session metadata for %s", session_id, exc_info=True
            )
            return {}
        raw = meta.get(self.KEY)
        return raw if isinstance(raw, dict) else {}


class DictSessionStateStore:
    """Adapts a plain ``dict`` to the store interface.

    The legacy path: callers that already keep the state in a dict
    (the orchestrator before the store existed, and the tests that
    share a dict with the manager) keep working unchanged — the dict
    stays the source of truth, the store just reads and writes it.
    """

    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    def get(self, session_id: str) -> SessionState:
        return SessionState(status=self._data.get(session_id, "idle"))

    def set(
        self,
        session_id: str,
        status: str,
        *,
        holder: str = "",
        ttl: float = 0.0,
    ) -> None:
        self._data[session_id] = status

    def clear(self, session_id: str) -> None:
        self._data.pop(session_id, None)

    def list_all(self) -> dict[str, SessionState]:
        return {k: SessionState(status=v) for k, v in self._data.items()}

    def __len__(self) -> int:
        return len(self._data)


class SessionStateView(MutableMapping):
    """A dict-like view over a :class:`SessionStateStore`.

    The orchestrator and the session manager used to share a plain dict
    by reference. The view keeps that surface — ``view["s1"] = "busy"``
    still works — but the state itself now lives in the store, so it
    can be bounded or externalised.
    """

    def __init__(self, store: SessionStateStore) -> None:
        self._store = store

    def __getitem__(self, key: str) -> str:
        state = self._store.get(key)
        if not self._store.list_all().get(key):
            raise KeyError(key)
        return state.status

    def __setitem__(self, key: str, value: str) -> None:
        self._store.set(key, value)

    def __delitem__(self, key: str) -> None:
        self._store.clear(key)

    def __iter__(self):
        return iter(self._store.list_all())

    def __len__(self) -> int:
        return len(self._store.list_all())


__all__ = [
    "SessionState",
    "SessionStateStore",
    "SessionStateView",
    "InMemorySessionStateStore",
    "SqliteSessionStateStore",
    "DictSessionStateStore",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_TTL_SECONDS",
    "DEFAULT_LEASE_SECONDS",
]

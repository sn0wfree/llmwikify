"""JWT encode/decode wrapper for llmwikify.

Layer: L1 (foundation). Wraps PyJWT to add our specific claim schema
(sub/scope/wikis/aud/iss/exp/iat) on top of standard RFC 7519 fields.

Decisions:
  - 4:  scope = "read" | "write"
  - 7:  wikis = explicit list (no wildcard at runtime; "*" is the
         sentinel for "all wikis" but only used internally for owner
         bootstrap; the middleware always validates per-request)
  - 1:  AuthMiddleware enforces scope based on HTTP method (GET=read,
         non-GET=write) unless public_read=True and method=read
  - 5:  exp = 30d from issue, no silent refresh

PyJWT is the only external dep of this module. Pure stateless: encode()
needs a secret, decode() needs the same secret. The middleware decides
where the secret comes from (keyring or `--auth-token` override).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

import jwt

# Audiences / issuers are intentionally hard-coded strings, not config.
# If we ever federate (Phase 4 hub), add iss variants per AS.
AUDIENCE = "llmwikify"
ISSUER = "llmwikify.local"

# Algorithm lock: we only accept HS256 (symmetric, single-tenant).
# RS256/ES256 reserved for Phase 4 hub-federated tokens.
ALGORITHM = "HS256"

# Token TTL (decision 5). Owner + share both 30d max; share can override
# shorter. This is the canonical default; caller can pass any exp.
DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days


@dataclass
class TokenClaims:
    """llmwikify JWT claim shape.

    Fields:
        sub:    "user:<uuid>" | "share:<uuid>" — who/what issued this.
        scope:  "read" | "write" — capability level.
        wikis:  explicit whitelist of wiki_ids the token can act on.
                Use ["*"] for owner bootstrap only; middleware always
                checks per-request (decision 7).
        exp:    unix timestamp (PyJWT requires int).
        iat:    unix timestamp.
        aud:    always "llmwikify".
        iss:    always "llmwikify.local" (Phase 4 will add hub variants).
    """

    sub: str
    scope: str
    wikis: list[str]
    exp: int
    iat: int
    aud: str = AUDIENCE
    iss: str = ISSUER

    @classmethod
    def new(
        cls,
        sub: str,
        scope: str,
        wikis: list[str],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> TokenClaims:
        """Construct a fresh claim with iat=now, exp=now+ttl."""
        now = int(time.time())
        return cls(
            sub=sub,
            scope=scope,
            wikis=list(wikis),
            iat=now,
            exp=now + ttl_seconds,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> TokenClaims:
        # PyJWT returns dict-of-str-or-int; we coerce back into the dataclass.
        # `wikis` is always a list per our schema; default to [] for
        # forward-compat with tokens that omit it.
        wikis_raw = data.get("wikis", [])
        wikis = list(wikis_raw) if isinstance(wikis_raw, list) else []
        return cls(
            sub=str(data["sub"]),
            scope=str(data["scope"]),
            wikis=wikis,
            exp=int(data["exp"]),
            iat=int(data.get("iat", data["exp"] - DEFAULT_TTL_SECONDS)),
            aud=str(data.get("aud", AUDIENCE)),
            iss=str(data.get("iss", ISSUER)),
        )


def encode(claims: TokenClaims, secret: bytes) -> str:
    """Encode claims into a compact JWS string (HS256)."""
    return jwt.encode(
        claims.to_dict(),
        secret,
        algorithm=ALGORITHM,
    )


def decode(token: str, secret: bytes) -> TokenClaims:
    """Decode and verify a JWS string. Raises:
        - jwt.ExpiredSignatureError: exp < now
        - jwt.InvalidSignatureError:  bad HMAC
        - jwt.InvalidAudienceError:  aud != "llmwikify"
        - jwt.InvalidTokenError:      malformed/other
    Caller should catch these and map to AuthError.
    """
    payload = jwt.decode(
        token,
        secret,
        algorithms=[ALGORITHM],
        audience=AUDIENCE,
    )
    return TokenClaims.from_dict(payload)

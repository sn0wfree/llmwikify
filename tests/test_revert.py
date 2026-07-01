"""Tests for session revert functionality."""

from __future__ import annotations

import shutil
import tempfile
import time

from llmwikify.apps.chat.db import ChatDatabase


def _make_db() -> tuple[ChatDatabase, str]:
    tmpdir = tempfile.mkdtemp()
    db = ChatDatabase(tmpdir)
    sid = db.create_chat_session("test", None)
    return db, sid, tmpdir


class TestRevert:
    def test_revert_middle_message(self):
        db, sid, tmpdir = _make_db()
        try:
            db.save_chat_message({"session_id": sid, "role": "user", "content": "hello"})
            time.sleep(1.1)
            db.save_chat_message({"session_id": sid, "role": "assistant", "content": "hi"})
            time.sleep(1.1)
            db.save_chat_message({"session_id": sid, "role": "user", "content": "bye"})
            time.sleep(1.1)
            db.save_chat_message({"session_id": sid, "role": "assistant", "content": "goodbye"})

            msgs = db.get_chat_messages(sid)
            assert len(msgs) == 4

            # Revert to second message (assistant "hi")
            target_id = msgs[1]["id"]
            count = db.revert_to_message(sid, target_id)
            assert count == 2  # "bye" + "goodbye" reverted

            msgs = db.get_chat_messages(sid)
            assert len(msgs) == 2
            assert msgs[0]["content"] == "hello"
            assert msgs[1]["content"] == "hi"
        finally:
            shutil.rmtree(tmpdir)

    def test_revert_first_message(self):
        db, sid, tmpdir = _make_db()
        try:
            db.save_chat_message({"session_id": sid, "role": "user", "content": "hello"})
            time.sleep(1.1)
            db.save_chat_message({"session_id": sid, "role": "assistant", "content": "hi"})

            msgs = db.get_chat_messages(sid)
            count = db.revert_to_message(sid, msgs[0]["id"])
            assert count == 1

            msgs = db.get_chat_messages(sid)
            assert len(msgs) == 1
            assert msgs[0]["content"] == "hello"
        finally:
            shutil.rmtree(tmpdir)

    def test_revert_nonexistent_message(self):
        db, sid, tmpdir = _make_db()
        try:
            db.save_chat_message({"session_id": sid, "role": "user", "content": "hello"})
            count = db.revert_to_message(sid, "nonexistent_id")
            assert count == 0
            msgs = db.get_chat_messages(sid)
            assert len(msgs) == 1
        finally:
            shutil.rmtree(tmpdir)

    def test_include_reverted(self):
        db, sid, tmpdir = _make_db()
        try:
            db.save_chat_message({"session_id": sid, "role": "user", "content": "hello"})
            time.sleep(1.1)
            db.save_chat_message({"session_id": sid, "role": "assistant", "content": "hi"})
            time.sleep(1.1)
            db.save_chat_message({"session_id": sid, "role": "user", "content": "bye"})

            msgs = db.get_chat_messages(sid)
            db.revert_to_message(sid, msgs[1]["id"])

            # Default: excludes reverted
            msgs = db.get_chat_messages(sid)
            assert len(msgs) == 2

            # With include_reverted: shows all
            msgs = db.get_chat_messages(sid, include_reverted=True)
            assert len(msgs) == 3
        finally:
            shutil.rmtree(tmpdir)


class TestAutoNaming:
    def test_title_stored_and_retrieved(self):
        db, sid, tmpdir = _make_db()
        try:
            db.update_chat_session_title(sid, "My Chat Title")
            session = db.get_chat_session(sid)
            assert session["title"] == "My Chat Title"

            title = db.get_chat_session_title(sid)
            assert title == "My Chat Title"
        finally:
            shutil.rmtree(tmpdir)

    def test_title_falls_back_to_first_message(self):
        db, sid, tmpdir = _make_db()
        try:
            db.save_chat_message({"session_id": sid, "role": "user", "content": "hello world"})
            title = db.get_chat_session_title(sid)
            assert title == "hello world"
        finally:
            shutil.rmtree(tmpdir)

    def test_title_prefers_stored_over_derived(self):
        db, sid, tmpdir = _make_db()
        try:
            db.save_chat_message({"session_id": sid, "role": "user", "content": "hello world"})
            db.update_chat_session_title(sid, "Custom Title")
            title = db.get_chat_session_title(sid)
            assert title == "Custom Title"
        finally:
            shutil.rmtree(tmpdir)

import hashlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("history_recovery", ROOT / "scripts/codex-history.py")
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


class HistoryRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.db = self.home / "state_5.sqlite"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("""CREATE TABLE threads (
                id TEXT PRIMARY KEY, name TEXT, title TEXT, cwd TEXT,
                model_provider TEXT, has_user_event INTEGER, source TEXT,
                archived INTEGER, thread_source TEXT, updated_at INTEGER,
                rollout_path TEXT, first_user_message TEXT)""")
        self.ids = []
        self.add_row("openai", "旧会话")
        self.add_row("rotateproxy", "新会话")

    def add_row(self, provider, title, **overrides):
        sid = f"01990c90-1111-7111-8111-{len(self.ids) + 1:012d}"
        self.ids.append(sid)
        path = self.home / "sessions" / (sid + ".jsonl")
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": sid, "model_provider": provider}}) + "\n")
        row = dict(id=sid, name=None, title=title, cwd=str(self.home),
                   model_provider=provider, has_user_event=1, source="cli",
                   archived=0, thread_source="user", updated_at=len(self.ids),
                   rollout_path=str(path), first_user_message=title)
        row.update(overrides)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
        return row

    def test_cross_provider_scope_and_database_unchanged(self):
        self.add_row("openai", "exec", source="exec")
        self.add_row("rotateproxy", "archived", archived=1)
        self.add_row("openai", "subagent", thread_source="subagent")
        self.add_row("unrelated", "foreign")
        self.add_row("openai", "empty", has_user_event=0, first_user_message="")
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        rows = recovery.read_sessions(self.home)
        self.assertEqual([row["id"] for row in rows], self.ids[:2][::-1])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_native_index_with_message_but_unset_event_flag_remains_visible(self):
        row = self.add_row("openai", "已存在用户消息", has_user_event=0)
        self.assertIn(row["id"], {item["id"] for item in recovery.read_sessions(self.home)})

    def test_read_connection_cannot_write(self):
        connect = sqlite3.connect

        def checked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE threads SET title='unexpected'")
            return connection

        with patch.object(recovery.sqlite3, "connect", side_effect=checked_connect):
            recovery.read_sessions(self.home)

    def test_cwd_search_and_title_are_not_sql_or_terminal_code(self):
        alias = self.home / "alias"
        alias.symlink_to(self.home, target_is_directory=True)
        self.add_row("openai", "Other", cwd="/another/project")
        rows = recovery.read_sessions(self.home, alias)
        self.assertEqual({row["id"] for row in rows}, set(self.ids[:2]))
        self.assertEqual(recovery.match_sessions(rows, "旧")[0]["id"], self.ids[0])
        self.assertEqual(recovery.match_sessions(rows, "' OR 1=1 --"), [])
        self.assertEqual(recovery.display_text("a\x1b\n\x07b"), "a b")

    def test_missing_database_and_schema_fail_instead_of_looking_empty(self):
        with self.assertRaises(recovery.HistoryError):
            recovery.read_sessions(self.home / "absent")
        self.assertFalse((self.home / "absent").exists())
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("DROP TABLE threads")
        with self.assertRaises(recovery.HistoryError):
            recovery.read_sessions(self.home)

    def test_empty_database_is_a_real_empty_result(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("DELETE FROM threads")
        self.assertEqual(recovery.read_sessions(self.home), [])

    def test_selection_search_cancel_and_out_of_range(self):
        rows = recovery.read_sessions(self.home)
        with patch("builtins.input", side_effect=["999", "/旧", "1"]), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(recovery.select_session(rows)["id"], self.ids[0])
        for answer in ("q", "", "Q"):
            with self.subTest(answer=answer), patch("builtins.input", return_value=answer), patch("sys.stdout", new=io.StringIO()):
                self.assertIsNone(recovery.select_session(rows))
        with patch("builtins.input", side_effect=EOFError), patch("sys.stdout", new=io.StringIO()):
            self.assertIsNone(recovery.select_session(rows))

    def test_pagination_selects_only_a_visible_row(self):
        for i in range(22):
            self.add_row("openai", f"Page {i}")
        rows = recovery.read_sessions(self.home)
        with patch("builtins.input", side_effect=["21", "n", "21"]) as answer, patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(recovery.select_session(rows)["id"], rows[20]["id"])
        self.assertEqual(answer.call_count, 3)

    def test_resume_validates_rollout_identity_and_uses_existing_proxy_entry(self):
        row = recovery.read_sessions(self.home)[0]
        with patch.object(recovery.shutil, "which", return_value="/fixture/cxp") as lookup, patch.object(recovery.os, "execv") as execute, patch("sys.stdout", new=io.StringIO()):
            recovery.resume_session(row, self.home)
        lookup.assert_called_once_with("cxp")
        execute.assert_called_once_with("/fixture/cxp", ["/fixture/cxp", "resume", row["id"]])
        path = Path(row["rollout_path"])
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": self.ids[0]}}))
        with patch.object(recovery.os, "execv") as execute, self.assertRaises(recovery.HistoryError):
            recovery.resume_session(row, self.home)
        execute.assert_not_called()

    def test_missing_or_external_rollout_cannot_be_resumed(self):
        row = recovery.read_sessions(self.home)[0]
        Path(row["rollout_path"]).unlink()
        with self.assertRaises(recovery.HistoryError):
            recovery.resume_session(row, self.home)
        outside = self.home / "outside.jsonl"
        outside.write_text(json.dumps({"type": "session_meta", "payload": {"id": row["id"]}}))
        row["rollout_path"] = str(outside)
        with patch.object(recovery.shutil, "which", return_value="/fixture/cxp"), patch.object(recovery.os, "execv") as execute, self.assertRaises(recovery.HistoryError):
            recovery.resume_session(row, self.home)
        execute.assert_not_called()

    def test_noninteractive_selection_never_launches_a_session(self):
        with patch.object(recovery.sys.stdin, "isatty", return_value=False), patch.object(recovery.os, "execv") as execute, patch.dict(recovery.os.environ, {"CODEX_HOME": str(self.home)}), patch.object(recovery, "select_session", return_value=None):
            with self.assertRaises(recovery.HistoryError):
                recovery.main(["--select", "--all"])
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()

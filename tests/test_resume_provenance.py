"""Proxy resume must never assign anonymous historical telemetry to the active account."""
import concurrent.futures
import contextlib
import copy
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SID = "01990c90-1111-7111-8111-111111111111"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("resume_quota_cli", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)
    return cli


class QuotaAttribution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "codex"
        self.store = Path(self.tmp.name) / "store"
        self.home.mkdir()
        self.store.mkdir()
        self.rollout = self.home / "rollout.jsonl"
        self.rollout.write_text(json.dumps({"type": "session_meta", "payload": {
            "id": SID, "model_provider": "openai"}}) + "\n" + json.dumps({
                "timestamp": "2026-09-08T01:00:00Z", "payload": {"rate_limits": {
                    "limit_id": "codex", "primary": {"used_percent": 91, "window_minutes": 300}}}}) + "\n")
        self.cli = load_cli()
        self.addCleanup(patch.stopall)
        patch.object(self.cli, "CODEX_HOME", self.home).start()
        patch.object(self.cli, "STORE", self.store).start()
        patch.object(self.cli, "_newest_rollout", return_value=self.rollout).start()

    def mark(self):
        key = hashlib.sha256(os.path.normcase(str(self.home.resolve())).encode()).hexdigest()
        marker = self.store / ".proxy-sessions-v1" / key / SID
        marker.parent.mkdir(parents=True)
        marker.touch()

    def test_old_openai_proxy_echo_is_not_attributed(self):
        self.assertEqual(self.cli._live_quota()["primary"]["used_percent"], 91)
        original = self.rollout.read_bytes()
        self.mark()
        self.assertIsNone(self.cli._live_quota())
        self.assertIsNone(self.cli._attributable_quota({"active_since": 1}))
        self.assertEqual(original, self.rollout.read_bytes())

    def test_syncback_preserves_account_a_when_rollout_contains_proxy_b(self):
        self.mark()
        live = self.home / "auth.json"
        live.write_text(json.dumps({"tokens": {"account_id": "account-a"}}))
        state = {"active": "account-a", "active_since": 1, "slots": {
            "account-a": {"quota": {"primary": {"used_percent": 12}}}}}
        expected = copy.deepcopy(state["slots"]["account-a"]["quota"])
        with patch.object(self.cli, "LIVE", live), \
             patch.object(self.cli, "_cred_lock", contextlib.nullcontext), \
             patch.object(self.cli, "_write_slot") as writer, \
             patch.object(self.cli, "_stamp_identity"):
            self.cli._syncback(state)
        writer.assert_called_once()
        self.assertEqual(state["slots"]["account-a"]["quota"], expected)

    def test_invalid_registry_refuses_attribution(self):
        (self.store / ".proxy-sessions-v1").write_text("damaged")
        self.assertIsNone(self.cli._live_quota())

    def test_daemon_style_import_can_read_plain_rollout_outside_repo(self):
        result = subprocess.run([sys.executable, "-I", "-c",
                                 'import runpy, sys; m=runpy.run_path(sys.argv[1]); '
                                 'print(m["_rollout_is_proxy"](sys.argv[2]))',
                                 str(ROOT / "codex-rotate"), str(self.rollout)],
                                cwd=self.tmp.name, env=dict(os.environ, CODEX_HOME=str(self.home),
                                CODEX_ROTATE_STORE=str(self.store)), capture_output=True,
                                text=True, timeout=10, check=True)
        self.assertEqual(result.stdout.strip(), "False")


class ProvenanceMarkers(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Symlink creation requires extra Windows privileges")
    def test_symlink_home_has_the_same_identity(self):
        import resume_provenance as provenance
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            alias = root / "alias"
            alias.symlink_to(home, target_is_directory=True)
            provenance.mark_proxy_session(root / "store", alias, SID)
            self.assertTrue(provenance.is_proxy_session(root / "store", home, SID))

    def test_idempotent_concurrent_home_scoped_registration(self):
        import resume_provenance as provenance
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            home = Path(tmp) / "中文 home"
            self.assertFalse(provenance.is_proxy_session(store, home, SID))
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: provenance.mark_proxy_session(store, home, SID), range(24)))
            self.assertTrue(provenance.is_proxy_session(store, home, SID))
            self.assertFalse(provenance.is_proxy_session(store, Path(tmp) / "other", SID))
            self.assertEqual(len(list(store.rglob(SID))), 1)
            with self.assertRaises(ValueError):
                provenance.mark_proxy_session(store, home, "../../bad")

    def test_unreadable_state_is_unknown_and_write_failure_is_loud(self):
        import resume_provenance as provenance
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            (store / ".proxy-sessions-v1").write_text("damaged")
            with self.assertRaises(OSError):
                provenance.is_proxy_session(store, store, SID)
            with self.assertRaises(OSError):
                provenance.mark_proxy_session(store, store, SID)

    def test_reader_is_in_the_actual_bundle_resource_map(self):
        config = json.loads((ROOT / "codexbar/src-tauri/tauri.conf.json").read_text())
        resources = config["bundle"]["resources"]
        selected = [(ROOT / "codexbar/src-tauri" / source, dest) for source, dest in resources.items()
                    if dest in ("scripts/codex-rotate", "scripts/resume_provenance.py")]
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            package = Path(tmp)
            for source, dest in selected:
                target = package / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            self.assertTrue((package / "scripts/resume_provenance.py").is_file())
            self.assertTrue((package / "scripts/codex-rotate").is_file())


if __name__ == "__main__":
    unittest.main()

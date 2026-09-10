#!/usr/bin/env python3
"""Exercise the real native picker with isolated histories and no model prompts (POSIX)."""
import argparse
import hashlib
import json
import os
import select
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from native_protocol import AppServer, list_threads
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from resume_provenance import is_proxy_session


class Terminal:
    def __init__(self, command):
        import fcntl
        import pty
        import termios
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 150, 0, 0))
        self.process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                                        start_new_session=True)
        os.close(slave)
        self.data = b""

    def pump(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not select.select([self.master], [], [], min(0.1, max(0, deadline-time.monotonic())))[0]:
                continue
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                break
            if not chunk:
                break
            self.data += chunk
            for query, reply in ((b"\x1b[6n", b"\x1b[1;1R"),
                                 (b"\x1b]10;?", b"\x1b]10;rgb:dddd/dddd/dddd\x1b\\"),
                                 (b"\x1b]11;?", b"\x1b]11;rgb:1111/1111/1111\x1b\\")):
                if query in chunk:
                    self.send(reply)

    def send(self, keys):
        os.write(self.master, keys)

    def wait_for(self, needle, timeout=45):
        deadline = time.monotonic() + timeout
        while needle not in self.data and time.monotonic() < deadline:
            self.pump(0.1)
        if needle not in self.data:
            raise AssertionError(f"Native terminal did not render {needle!r}")

    def close(self):
        if self.process.poll() is None:
            self.send(b"\x03")
            self.pump(0.5)
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        os.close(self.master)


def fixture(home):
    a, b = home / "work-a", home / "work-b"
    a.mkdir(); b.mkdir()
    config = '''model = "gpt-5.6-sol"
model_provider = "rotateproxy"
check_for_update_on_startup = false
[model_providers.rotateproxy]
name = "RotateProxy fixture"
base_url = "http://127.0.0.1:1"
wire_api = "responses"
supports_websockets = false
requires_openai_auth = false
[features]
background_paginated_rollout_migration = false
'''
    for directory in (a, b):
        config += f'\n[projects.{json.dumps(str(directory))}]\ntrust_level = "trusted"\n'
    (home / "config.toml").write_text(config)
    (home / "rotateproxy.config.toml").write_text(config)
    items = []
    for index, (provider, cwd, source, archived) in enumerate([
            ("openai", a, "cli", False), ("rotateproxy", a, "cli", False),
            ("openai", b, "vscode", False), ("rotateproxy", b, "cli", False),
            ("rotateproxy", a, "exec", False), ("openai", a, "cli", True)]):
        sid = f"01990c90-1111-7111-8111-{index+1:012d}"
        title = f"fixture-history-{index+1}"
        directory = home / ("archived_sessions" if archived else "sessions/2026/09/08")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"rollout-2026-09-08T00-00-0{index}-{sid}.jsonl"
        timestamp = f"2026-09-08T00:00:0{index}.000Z"
        records = [
            {"timestamp": timestamp, "type": "session_meta", "payload": {
                "id": sid, "timestamp": timestamp, "cwd": str(cwd), "originator": "codex_cli_rs",
                "cli_version": "0.153.4", "source": source, "model_provider": provider}},
            {"timestamp": timestamp, "type": "response_item", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": title}]}},
            {"timestamp": timestamp, "type": "event_msg", "payload": {
                "type": "user_message", "message": title, "images": [], "local_images": []}},
            {"timestamp": timestamp, "type": "event_msg", "payload": {
                "type": "task_complete", "turn_id": f"fixture-turn-{index}", "last_agent_message": None}}]
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        items.append({"id": sid, "title": title, "path": path})
    return a, items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.output = args.output.resolve()
    args.codex = args.codex.resolve(); args.baseline = args.baseline.resolve()
    proof = {}
    with tempfile.TemporaryDirectory(prefix="native-resume-proof-") as tmp:
        home = Path(tmp).resolve()
        work, items = fixture(home)
        store = home / "store"
        os.environ.update(CODEX_HOME=str(home), CODEX_ROTATE_STORE=str(store), TERM="xterm-256color",
                          NO_PROXY="127.0.0.1,localhost,::1", no_proxy="127.0.0.1,localhost,::1")
        with AppServer([str(args.baseline), "app-server", "--stdio"]) as client:
            params = {"modelProviders": [], "sourceKinds": ["cli", "vscode"],
                      "archived": False, "useStateDbOnly": False, "limit": 100}
            client.request("thread/list", params)
            client.request("thread/list", {**params, "archived": True})
            assert {r["id"] for r in list_threads(client)} == {i["id"] for i in items[:4]}
        hashes = {i["id"]: hashlib.sha256(i["path"].read_bytes()).hexdigest() for i in items}
        headers = {i["id"]: i["path"].read_bytes().splitlines()[0] for i in items}
        os.chdir(work)
        for label, binary, flags, expected in [
                ("baseline-all", args.baseline, ["--all"], [2, 4]),
                ("patched-all", args.codex, ["--all"], [1, 2, 3, 4]),
                ("patched-cwd", args.codex, [], [1, 2])]:
            started = time.monotonic()
            terminal = Terminal([str(binary), "--profile", "rotateproxy", "resume", *flags])
            try:
                for number in expected:
                    terminal.wait_for(f"fixture-history-{number}".encode())
                terminal.pump(0.5)
                seen = [n for n in range(1, 7) if f"fixture-history-{n}".encode() in terminal.data]
                assert seen == expected, (label, seen, expected)
                proof[label] = seen
                print(label, "rendered", seen, "seconds", round(time.monotonic() - started, 2), flush=True)
            finally:
                terminal.close()
                (args.output / f"{label}.terminal.txt").write_bytes(terminal.data)
        assert not (store / ".proxy-sessions-v1").exists(), "Cancel registered a resume"
        assert hashes == {i["id"]: hashlib.sha256(i["path"].read_bytes()).hexdigest() for i in items}
        for label, flags, item in [("picker-resume", ["--all"], items[0]),
                                    ("uuid-resume", [items[2]["id"]], items[2])]:
            terminal = Terminal([str(args.codex), "--profile", "rotateproxy", "resume", *flags])
            try:
                if label == "picker-resume":
                    terminal.wait_for(b"fixture-history-1")
                    terminal.send(item["title"].encode())
                    terminal.pump(0.8)
                    terminal.data = b""
                    terminal.send(b"\r")
                else:
                    terminal.wait_for(b"Press enter to continue")
                    terminal.pump(0.5)  # Native startup intentionally discards early action keys.
                    terminal.send(b"\r")  # Native prompt: use the session's working directory.
                terminal.wait_for(item["title"].encode())
                terminal.pump(1)
                terminal.send(b"/status")
                terminal.pump(0.5)
                terminal.send(b"\r")
                terminal.wait_for(b"RotateProxy fixture")
                marker = list(store.rglob(item["id"]))
                assert len(marker) == 1, "Native resume did not register provenance"
                assert is_proxy_session(store, home, item["id"]), "Rust/Python provenance identities differ"
                assert item["path"].read_bytes().splitlines()[0] == headers[item["id"]]
                with sqlite3.connect(f"file:{home / 'state_5.sqlite'}?mode=ro", uri=True) as db:
                    provider = db.execute("SELECT model_provider FROM threads WHERE id=?", (item["id"],)).fetchone()[0]
                proof[label] = {"id": item["id"], "effective_provider": "rotateproxy (native /status)",
                                "historical_database_provider": provider, "original_header_unchanged": True,
                                "provenance_marker": True, "history_rendered": True}
            finally:
                terminal.close()
                (args.output / f"{label}.terminal.txt").write_bytes(terminal.data)
        proof["cancel_unchanged"] = True
        proof["model_prompts_sent"] = 0
    (args.output / "native-fixture-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()

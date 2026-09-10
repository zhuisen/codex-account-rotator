"""Cross-provider discovery through the local official Codex app-server protocol."""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from uuid import UUID


class HistoryError(RuntimeError):
    pass


class AppServer:
    def __init__(self, command, timeout=15):
        self.command = command
        self.timeout = timeout
        self.process = None
        self.messages = queue.Queue()
        self.sequence = 0

    def __enter__(self):
        self.process = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.request("initialize", {"clientInfo": {"name": "codexbar_history", "version": "1"},
                                        "capabilities": {"experimentalApi": True}})
            self._send({"method": "initialized", "params": {}})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (OSError, ValueError) as exc:
            self.messages.put(exc)
        finally:
            self.messages.put(None)

    def _send(self, message):
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise HistoryError("Codex app-server pipe closed") from exc

    def request(self, method, params):
        self.sequence += 1
        self._send({"method": method, "id": self.sequence, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                reply = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise HistoryError(f"Codex app-server timed out: {method}") from exc
            if not isinstance(reply, dict):
                raise HistoryError("Codex app-server stopped or returned invalid JSON")
            if reply.get("id") != self.sequence:
                continue
            if "error" in reply or not isinstance(reply.get("result"), dict):
                raise HistoryError(f"Codex app-server rejected {method}; check CLI compatibility/config")
            return reply["result"]

    def __exit__(self, *args):
        if self.process is None:
            return
        self.process.stdin.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
        self.reader.join(timeout=2)
        self.process.stdout.close()


def list_threads(client, cwd=None):
    params = {"modelProviders": ["openai", "rotateproxy"], "sourceKinds": ["cli", "vscode"],
              "archived": False, "useStateDbOnly": True, "sortKey": "updated_at", "limit": 100}
    if cwd is not None:
        params["cwd"] = cwd
    threads = {}
    cursors = set()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = client.request("thread/list", params)
        data, cursor = result.get("data"), result.get("nextCursor")
        if not isinstance(data, list) or (cursor is not None and not isinstance(cursor, str)):
            raise HistoryError("Unsupported thread/list response")
        for row in data:
            if not isinstance(row, dict) or row.get("modelProvider") not in params["modelProviders"]:
                raise HistoryError("thread/list returned an incompatible provider")
            try:
                identity = str(UUID(row.get("sessionId") or row["id"]))
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                raise HistoryError("thread/list did not return a local session UUID") from exc
            threads.setdefault(identity, {**row, "id": identity})
        if cursor is None:
            return list(threads.values())
        if not cursor or cursor in cursors:
            raise HistoryError("thread/list returned a repeated pagination cursor")
        cursors.add(cursor)
        params["cursor"] = cursor
    raise HistoryError("History discovery timed out before all pages were read")


def codex_command():
    executable = os.environ.get("CXP_CODEX_BIN") or shutil.which("codex")
    if not executable:
        raise HistoryError("Codex CLI not found on PATH")
    path = Path(executable).resolve()
    if path.name in ("cxp", "cxp.py", "cxp.ps1"):
        raise HistoryError("CXP_CODEX_BIN must point to Codex, not cxp")
    # Launch npm's JS through Node on Windows; never interpolate argv into cmd.exe.
    if path.suffix.lower() == ".cmd":
        script = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node")
        if not script.is_file() or not node:
            raise HistoryError("Set CXP_CODEX_BIN to codex.exe or install the official npm CLI")
        return [node, str(script)]
    return [executable]


def discover(cwd=None):
    # 0.153.4 rejects --profile for app-server. Listing sets providers in the RPC;
    # only the subsequent native resume uses the execution profile.
    with AppServer(codex_command() + ["app-server", "--stdio"]) as client:
        return list_threads(client, cwd)


def display_text(value, limit=100):
    text = " ".join(str(value or "").split())
    return "".join(c for c in text if not unicodedata.category(c).startswith("C"))[:limit]


def main(argv=None):
    parser = argparse.ArgumentParser(description="List local openai/rotateproxy Codex histories")
    parser.add_argument("--all", action="store_true", help="Include other working directories")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--search", default="")
    args = parser.parse_args(argv)
    rows = discover(None if args.all else str(Path.cwd().resolve()))
    query = args.search.casefold()
    rows = [r for r in rows if query in " ".join(str(r.get(k) or "") for k in
            ("id", "name", "preview", "cwd")).casefold()]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        print(f"{len(rows)} sessions (openai + rotateproxy)")
        for row in rows:
            title = display_text(row.get("name") or row.get("preview"))
            print(f"{row['id']}  {title}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HistoryError, OSError) as exc:
        print(f"CodexBar history: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

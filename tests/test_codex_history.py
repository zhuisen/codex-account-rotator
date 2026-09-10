import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/native-resume"))
IDS = [f"01990c90-1111-7111-8111-{i:012d}" for i in range(1, 5)]


def row(i, provider="openai"):
    return {"id": IDS[i], "preview": "fixture", "modelProvider": provider,
            "cwd": "/fixture", "updatedAt": 1788829000}


class HistoryProtocol(unittest.TestCase):
    def test_pagination_uses_explicit_compatible_providers_and_cwd(self):
        from native_protocol import list_threads
        calls = []

        class Client:
            def request(self, method, params):
                calls.append((method, params.copy()))
                if not params.get("cursor"):
                    return {"data": [row(0), row(1, "rotateproxy")], "nextCursor": "page2"}
                return {"data": [row(1, "rotateproxy"), row(2)], "nextCursor": None}

        threads = list_threads(Client(), "/fixture")
        self.assertEqual([r["id"] for r in threads], IDS[:3])
        self.assertEqual(len(calls), 2)
        for method, params in calls:
            self.assertEqual(method, "thread/list")
            self.assertEqual(params["modelProviders"], ["openai", "rotateproxy"])
            self.assertEqual(params["sourceKinds"], ["cli", "vscode"])
            self.assertTrue(params["useStateDbOnly"])
            self.assertFalse(params["archived"])
            self.assertEqual(params["cwd"], "/fixture")

    def test_all_omits_cwd_and_bad_response_is_not_empty(self):
        from native_protocol import HistoryError, list_threads
        outer = self

        class Client:
            result = {"data": [], "nextCursor": None}

            def request(self, method, params):
                outer.assertNotIn("cwd", params)
                return self.result

        client = Client()
        self.assertEqual(list_threads(client), [])
        for bad in ({}, {"data": [row(0, "unrelated-provider")]},
                    {"data": [{**row(0), "id": "virtual:not-a-session"}]},
                    {"data": [], "nextCursor": 3}):
            client.result = bad
            with self.subTest(bad=bad), self.assertRaises(HistoryError):
                list_threads(client)

    def test_repeated_cursor_is_an_error(self):
        from native_protocol import HistoryError, list_threads

        class Client:
            def request(self, method, params):
                return {"data": [row(0)], "nextCursor": "same"}

        with self.assertRaises(HistoryError):
            list_threads(Client())

    def test_stdio_handshake_errors_timeout_and_cleanup(self):
        from native_protocol import AppServer, HistoryError
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake.py"
            script.write_text('''import json, sys, time
for line in sys.stdin:
    r = json.loads(line)
    if "id" not in r: continue
    if r["method"] == "sleep": time.sleep(10)
    result = {"id": r["id"], "result": {"data": [], "nextCursor": None}}
    if r["method"] == "bad": result = {"id": r["id"], "error": {"code": -32601}}
    print(json.dumps(result), flush=True)
''')
            with AppServer([sys.executable, str(script)], timeout=0.5) as client:
                self.assertEqual(client.request("thread/list", {})["data"], [])
                with self.assertRaises(HistoryError):
                    client.request("bad", {})
                with self.assertRaises(HistoryError):
                    client.request("sleep", {})
                process = client.process
            self.assertIsNotNone(process.poll())


if __name__ == "__main__":
    unittest.main()

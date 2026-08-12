import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "codex-rotate"


class RetiredSwiftBarInvariantTest(unittest.TestCase):
    def test_cli_cannot_launch_retired_swiftbar(self) -> None:
        source = CLI.read_text(encoding="utf-8")
        tree = ast.parse(source)
        function_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        self.assertNotIn("swiftbar://", source.lower())
        self.assertNotIn("_refresh_menu", function_names)


if __name__ == "__main__":
    unittest.main()

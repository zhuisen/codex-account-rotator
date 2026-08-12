import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "codex-rotate",
    ROOT / "proxy" / "proxy.py",
    ROOT / "daemon" / "quota_daemon.py",
)
STATE_CALLS = {"_state_mutex", "_mutate_state"}
CREDENTIAL_CALLS = {"_cred_lock"}


def call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def contains_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(item, ast.Name) and item.id == name for item in ast.walk(node))


def lock_kind(node: ast.AST) -> str | None:
    name = call_name(node)
    if name in STATE_CALLS:
        return "state"
    if name in CREDENTIAL_CALLS:
        return "credential"
    if name == "open" and contains_name(node, "STATE_LOCK"):
        return "state"
    if name == "open" and contains_name(node, "REFRESH_LOCK"):
        return "credential"
    return None


def function_index(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


class FunctionFacts(ast.NodeVisitor):
    def __init__(self) -> None:
        self.direct_state = False
        self.calls: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node)
        if name:
            self.calls.add(name)
        if lock_kind(node) == "state":
            self.direct_state = True
        self.generic_visit(node)


def state_acquiring_functions(
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> set[str]:
    facts: dict[str, FunctionFacts] = {}
    for name, function in functions.items():
        visitor = FunctionFacts()
        for statement in function.body:
            visitor.visit(statement)
        facts[name] = visitor

    acquiring = {name for name, fact in facts.items() if fact.direct_state}
    changed = True
    while changed:
        changed = False
        for name, fact in facts.items():
            if name not in acquiring and fact.calls & acquiring:
                acquiring.add(name)
                changed = True
    return acquiring


class ReverseLockVisitor(ast.NodeVisitor):
    def __init__(self, source: Path, function: str, state_functions: set[str]) -> None:
        self.source = source
        self.function = function
        self.state_functions = state_functions
        self.credential_depth = 0
        self.violations: set[tuple[str, int, str]] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_With(self, node: ast.With) -> None:
        original_depth = self.credential_depth
        for item in node.items:
            kind = lock_kind(item.context_expr)
            if kind == "state" and self.credential_depth:
                self.record(item.context_expr, "state lock acquired inside credential lock")
            self.visit(item.context_expr)
            if kind == "credential":
                self.credential_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.credential_depth = original_depth

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node)
        if self.credential_depth and (name in STATE_CALLS or name in self.state_functions):
            self.record(node, f"call to state-acquiring helper {name} inside credential lock")
        self.generic_visit(node)

    def record(self, node: ast.AST, reason: str) -> None:
        self.violations.add((self.function, getattr(node, "lineno", 0), reason))


def lock_assignments(tree: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"STATE_LOCK", "REFRESH_LOCK"}:
            continue
        strings = [
            item.value
            for item in ast.walk(node.value)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        if strings:
            result[target.id] = strings[-1]
    return result


class LockOrderInvariantTest(unittest.TestCase):
    def test_cli_and_proxy_share_the_same_lock_files(self) -> None:
        cli = ast.parse((ROOT / "codex-rotate").read_text())
        proxy = ast.parse((ROOT / "proxy" / "proxy.py").read_text())
        expected = {"STATE_LOCK": ".state.lock", "REFRESH_LOCK": ".refresh.lock"}

        self.assertEqual(lock_assignments(cli), expected)
        self.assertEqual(lock_assignments(proxy), expected)

    def test_detector_rejects_direct_and_indirect_lock_inversions(self) -> None:
        tree = ast.parse(
            """
def helper():
    _mutate_state(lambda state: state)

def broken_direct():
    with _cred_lock():
        _mutate_state(lambda state: state)

def broken_indirect():
    with _cred_lock():
        helper()
"""
        )
        functions = function_index(tree)
        state_functions = state_acquiring_functions(functions)
        detected: set[str] = set()

        for name in ("broken_direct", "broken_indirect"):
            visitor = ReverseLockVisitor(Path("synthetic.py"), name, state_functions)
            for statement in functions[name].body:
                visitor.visit(statement)
            detected.update(function for function, _, _ in visitor.violations)

        self.assertEqual(detected, {"broken_direct", "broken_indirect"})

    def test_state_lock_is_never_acquired_after_credential_lock(self) -> None:
        violations: list[str] = []
        for source in SOURCES:
            tree = ast.parse(source.read_text())
            functions = function_index(tree)
            state_functions = state_acquiring_functions(functions)

            module_visitor = ReverseLockVisitor(source, "<module>", state_functions)
            for statement in tree.body:
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    module_visitor.visit(statement)
            for function, line, reason in module_visitor.violations:
                violations.append(f"{source.relative_to(ROOT)}:{line} {function}: {reason}")

            for name, function in functions.items():
                visitor = ReverseLockVisitor(source, name, state_functions)
                for statement in function.body:
                    visitor.visit(statement)
                for function_name, line, reason in visitor.violations:
                    violations.append(
                        f"{source.relative_to(ROOT)}:{line} {function_name}: {reason}"
                    )

        self.assertEqual(violations, [], "credential -> state inversion:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()

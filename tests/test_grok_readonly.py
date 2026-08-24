"""`grok-quota` 只读性的 AST 闸 —— 全库最贵的一条守卫。

它挡的事故是:**误刷 grok 的 refresh_token 把号刷掉线。**
`~/.grok/auth.json` 是 grok CLI 自己的活文件,我们和它**共用同一份凭证**;grok 的 refresh_token
单次有效,我们一刷,grok CLI 手里那份立刻作废。这与 CLAUDE.md §8「绝不刷 active 号的 token
(B7/B8/B14 连环杀号)」是完全同族的事故 —— 那次是真的连环杀过号的。

写成 AST 而不是 grep:本仓库反复吃过「朴素 grep 假阳性」的亏(agy 的 `usageMetadata` 自指、
Claude 额度那次 8592 次命中全是正文)。这里反过来也一样 —— 文件头的禁令注释里本来就写着
`refresh_token` 四个字,grep 必然命中,而注释不是代码。AST 只看**真的取了这个键**没有。
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "grok-quota"

WRITE_MODES = ("w", "a", "x")

# ★ 分两档,因为**方法名本身不足以定性**。第一版把两档混在一起,立刻被
# `s.replace("Z", "+00:00")` 染红 —— 那是 str.replace,与文件系统毫无关系。
# 同族的还有 `list.remove` / `dict.copy` / `str.rename`(自定义类)。
# 全局那条「同前缀 ≠ 同标识」在这里的具体形态就是:**同方法名 ≠ 同接收者**。
AMBIGUOUS_MUTATORS = {"replace", "rename", "remove", "copy", "copy2", "move", "chmod"}
MUTATOR_RECEIVERS = {"os", "shutil", "path", "Path", "p", "fh"}
# 这些名字在 stdlib 里只有"改文件系统"一种含义,不看接收者也不会误伤。
UNAMBIGUOUS_MUTATORS = {"unlink", "rmdir", "write_text", "write_bytes", "mkdir", "makedirs"}
LOCK_NAMES = {"_state_mutex", "_mutate_state", "_cred_lock", "flock", "lockf"}
FORBIDDEN_LITERALS = {"state.json", "auth.json.lock", ".state.lock", ".refresh.lock"}


class GrokQuotaIsReadOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = SCRIPT.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)
        # 注释与 docstring 不是代码。docstring 是 Expr(Constant),要显式排掉,否则文件头那段
        # 禁令说明本身就会把这条测试染红 —— 那就成了「守卫因为写了守卫的理由而失败」。
        cls.docstrings = {id(n.value) for n in ast.walk(cls.tree)
                          if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                          and isinstance(n.value.value, str)}

    def code_strings(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in self.docstrings:
                yield node

    # ---- 第 1 条:绝不碰 refresh_token --------------------------------------

    def test_no_refresh_token_string_in_code(self):
        hits = [n.value for n in self.code_strings() if "refresh_token" in n.value]
        self.assertEqual(hits, [], "代码里出现了 refresh_token:{}".format(hits))

    def test_no_refresh_token_attribute_or_subscript(self):
        bad = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and "refresh" in node.attr.lower():
                bad.append(node.attr)
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str) and "refresh" in node.slice.value.lower():
                bad.append(node.slice.value)
        self.assertEqual(bad, [], "出现了 refresh 相关的取值:{}".format(bad))

    def test_no_oauth_token_endpoint(self):
        """`/oauth2/token` 是 grok 的刷新端点(HPACK 解出来的),这个文件永远不该认识它。"""
        hits = [n.value for n in self.code_strings() if "oauth" in n.value.lower() or "/token" in n.value]
        self.assertEqual(hits, [], "出现了刷新端点:{}".format(hits))

    # ---- 第 2 条:只读、只 GET -----------------------------------------------

    def test_open_is_read_only(self):
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "open"):
                continue
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if mode is None:
                continue  # 缺省即 "r"
            self.assertFalse(mode.startswith(WRITE_MODES) or "+" in mode,
                             "open() 用了写模式 {!r}(行 {})".format(mode, node.lineno))

    def test_no_mutating_filesystem_calls(self):
        bad = []
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            name = node.func.attr
            if name in UNAMBIGUOUS_MUTATORS:
                bad.append("{}(行 {})".format(name, node.lineno))
            elif name in AMBIGUOUS_MUTATORS:
                recv = node.func.value
                recv_name = recv.id if isinstance(recv, ast.Name) else (
                    recv.attr if isinstance(recv, ast.Attribute) else None)
                if recv_name in MUTATOR_RECEIVERS:
                    bad.append("{}.{}(行 {})".format(recv_name, name, node.lineno))
        self.assertEqual(bad, [], "出现了会改文件系统的调用:{}".format(bad))

    def test_only_get_requests(self):
        methods = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "request" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                methods.append(node.args[0].value)
        self.assertTrue(methods, "一个 conn.request() 都没找到 —— 断言可能打空了")
        self.assertEqual(set(methods), {"GET"}, "出现了非 GET 请求:{}".format(methods))

    def test_no_write_verbs_anywhere(self):
        verbs = {"POST", "PUT", "PATCH", "DELETE"}
        hits = [n.value for n in self.code_strings() if n.value in verbs]
        self.assertEqual(hits, [], "出现了写动词:{}".format(hits))

    # ---- 第 3 条:不碰账号池的任何锁与状态 ------------------------------------

    def test_touches_no_locks(self):
        bad = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and node.id in LOCK_NAMES:
                bad.append(node.id)
            if isinstance(node, ast.Attribute) and node.attr in LOCK_NAMES:
                bad.append(node.attr)
        self.assertEqual(bad, [], "碰了锁:{} —— 取 auth.json.lock 会阻塞 grok CLI 自己的刷新".format(bad))

    def test_no_pool_state_literals(self):
        hits = [n.value for n in self.code_strings()
                if any(lit in n.value for lit in FORBIDDEN_LITERALS)]
        self.assertEqual(hits, [], "出现了账号池的状态/锁文件:{}".format(hits))

    # ---- 退出码契约 ----------------------------------------------------------

    def test_exit_codes_are_zero_or_two(self):
        """★ 只允许 0(含降级)与 2(参数错误)。非 0 会让 Rust 走 Err(String),
        而 Err 在前端三条消费路径上都被读成「没数据」—— 降级又被折叠回去了。"""
        codes = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, int):
                codes.add(node.value.value)
        self.assertTrue(codes <= {0, 2}, "出现了非 0/2 的返回码:{}".format(sorted(codes)))


class GrokIsNotInThePool(unittest.TestCase):
    """轮换池的三个文件**都不该认识 grok**。

    塞进 `state.json` 的 `slots` 会有四条会直接炸的后果,最严重的是:`cmd_keepalive` /
    `_refresh_slot` 就是拿 refresh_token 去刷的 —— grok 进池即进刷新器射程,绕回上面第 1 条。

    ⚠️ **必须走 AST,不能 grep**:`proxy/proxy.py` 的注释里提到过跨模型评审的 grok,
    朴素 `grep -i grok` 有假阳性。基线实测:三个文件的**代码字符串**里 0 命中。
    """
    POOL = ("codex-rotate", "proxy/proxy.py", "daemon/quota_daemon.py")

    def test_pool_files_never_mention_grok(self):
        for rel in self.POOL:
            path = ROOT / rel
            with self.subTest(file=rel):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                docs = {id(n.value) for n in ast.walk(tree)
                        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str)}
                hits = [n.value for n in ast.walk(tree)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and id(n) not in docs and "grok" in n.value.lower()]
                self.assertEqual(hits, [], "{} 的代码里提到了 grok:{}".format(rel, hits))


if __name__ == "__main__":
    unittest.main()

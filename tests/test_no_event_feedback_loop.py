"""事件自激回环闸 —— 「监听某事件的 handler 不许调一个会发同一事件的命令」。

## 为什么有这条（2026-09-21 的事故）

`useRotationBoard` 同时做了两件事：

    load()  ──invoke("run_rotate", ["next","--json"])──▶  Rust 侧无条件 emit("state-changed")
      ▲                                                              │
      └──────────────── listen("state-changed", () => load()) ◀──────┘

于是它自己把自己喂回去。实测（v1.8.0+23，主窗停在总览页）：

  · **12 秒内 789 个不同的 python 子进程**（≈66 个/秒）
  · 任一采样时刻并发 ~11 个 `codex-rotate integration` + ~5 个 `next`
  · app 自身 CPU 16.3%（不含那 789 个子进程）
  · 两个 webview 连同 `useStore` / `useIntegration` / `useBusyMirror` 一起被拖进去反复重拉

用户看到的是「CodexBar 一直在闪来闪去」。

★★★ **这条规则当时已经写在 `lib.rs::read_integration` 的注释里**
（「为什么要有一条专用 IPC 而不是复用 `run_rotate`：它每次都 emit + refresh_tray，
而这是个只读查询，会被 UI 定期调」）—— 而我照样违反了。
本仓铁律：**写下来但没有闸的规则一定会被违反，包括被写它的人。**
第二次撞上同一类，交付物就必须是**一条会变红的检查**，不是又一句叮嘱。

## 判据

不靠命名约定（那要求 `connector_plan` 改名），而是**从 Rust 源码里现读**
「哪些 `#[tauri::command]` 会发 `state-changed`」，再要求：
**任何 `listen("state-changed", h)` 的 handler，其可达函数体里不得 `invoke` 这些命令之一。**

★ 两侧都从**真源**解析，测试里不抄任何一份名单 —— 本仓栽过「测试抄了一份排序键，
  改真实现对闸毫无影响」。

## ⚠️ 这条闸**盖不住**什么（codex 评审 2026-09-21 点名，如实记下）

它是正则 + 有界解析，不是 TS AST。**它守得住已知的那几种写法，不等于关闭了整个缺陷类。**
已知漏报：

  · **跨文件** helper —— 只在同一文件里解析函数体；
  · **超过 `depth` 层**的调用链；
  · **动态事件名 / 动态命令名**（`useQuotaSidecar` 就有合法的动态参数形态）；
  · **多事件闭环** `A → B → A`（只查同名事件的自环）；
  · 前端**自己 `emit`** 造出的环（只查 Rust 命令的副作用）。

★ 写出来是因为「宣称覆盖了但其实没有」比没有闸更糟 —— 它让人以为这件事有人守着。
  真正关闭这一类要走 TS Compiler API 按 symbol 跟踪，并接进装过前端依赖的 CI job
  （现在的 python invariants job 没有 `npm ci`）。**未做，是已知缺口不是已解决。**
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "codexbar" / "src"
LIB_RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"

EVENT = "state-changed"


def _strip_comments(src: str) -> str:
    """★ 断言前必须剥注释 —— 本仓踩过五次「断言撞上正在解释这条规则的注释」。

    这份文件尤其危险：`lib.rs` 与两个 hook 的注释里**都逐字写着** `emit("state-changed")`
    和 `listen("state-changed"`，不剥的话解析器会把说明文字当成代码。
    """
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(?<![:/])//[^\n]*", "", src)


def _balanced(src: str, start: int, opener: str, closer: str) -> str:
    """从 `start` 处第一个 `opener` 起，返回配对闭合为止的整段（含两端）。

    ⚠️ 不用定长切片 —— 本仓记过：`src[i:i+600]` 会滑进下一个函数/注释，
      让闸要么假红、要么窗口整个偏掉。
    """
    i = src.find(opener, start)
    if i < 0:
        return ""
    depth, j = 0, i
    while j < len(src):
        if src[j] == opener:
            depth += 1
        elif src[j] == closer:
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    return ""


def emitting_commands() -> set:
    """从 `lib.rs` 现读：哪些 `#[tauri::command]` 的函数体会广播 `state-changed`。"""
    rs = _strip_comments(LIB_RS.read_text(encoding="utf-8"))
    out = set()
    for m in re.finditer(r"#\[tauri::command\]\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", rs):
        body = _balanced(rs, m.end(), "{", "}")
        if f'emit("{EVENT}"' in body:
            out.add(m.group(1))
    return out


def _fn_body(src: str, name: str) -> str:
    """取同文件里 `name` 的函数体。覆盖本仓实际出现的三种声明形态。"""
    for pat in (rf"\bconst\s+{name}\s*=\s*useCallback\s*\(",
                rf"\bconst\s+{name}\s*=\s*(?:async\s*)?\(",
                rf"\bfunction\s+{name}\s*\("):
        m = re.search(pat, src)
        if m:
            # useCallback(...) / 箭头函数：从声明处起取到最外层 `{…}` 闭合
            return _balanced(src, m.end(), "{", "}")
    return ""


def listener_reachable_invokes(src: str, depth: int = 3):
    """返回 `listen("state-changed", h)` 的 handler 在 `depth` 层内 invoke 了哪些命令。"""
    hits = []
    # ⚠️ 必须从 `listen(` **那一个**括号起平衡。第一版从事件名后的逗号起找下一个 `(`，
    #    而 `() => load()` 的第一个 `(` 是**空参数表** ⇒ 抓到 `()`、handler 恒为空、
    #    闸全绿。是 `test_it_fires_on_a_known_positive` 当场判红才发现的。
    for m in re.finditer(rf'\blisten\s*\((?=\s*["\']{EVENT}["\'])', src):
        handler = _balanced(src, m.start(), "(", ")")
        bodies, seen = [handler], set()
        for _ in range(depth):
            nxt = []
            for b in bodies:
                # ★ 既收「被调用的」`foo(` 也收**裸标识符** —— `listen("state-changed", load)`
                #   这种写法里 handler 根本不带括号，只找 `foo(` 会整条漏掉（codex 评审指出）。
                # ⚠️ 前面带 `.` 的跳过：`obj.load()` 里的 `load` 与同文件里另一个 `load`
                #   同名却不是同一个东西（同前缀 ≠ 同标识）。
                names = re.findall(r"(?<![.\w])(\w+)\s*\(", b) + re.findall(r"(?<![.\w])(\w+)", b)
                for call in names:
                    if call in seen or call in ("invoke", "listen", "setTimeout", "void"):
                        continue
                    seen.add(call)
                    fb = _fn_body(src, call)
                    if fb:
                        nxt.append(fb)
            if not nxt:
                break
            bodies += nxt
        for b in bodies:
            hits += re.findall(r'invoke\s*<[^>]*>\s*\(\s*["\'](\w+)["\']', b)
            hits += re.findall(r'invoke\s*\(\s*["\'](\w+)["\']', b)
    return hits


class TheProbeItselfWorks(unittest.TestCase):
    """★★ 先证明仪器是活的 —— 空名单 + 零监听者，与「全部干净」逐字节相同。"""

    def test_the_emitter_set_is_not_empty(self):
        cmds = emitting_commands()
        self.assertIn("run_rotate", cmds,
                      f"★★ 解析不出 `run_rotate` 会发 {EVENT} —— 解析器坏了，闸全部作废")
        self.assertGreaterEqual(len(cmds), 2, f"发事件的命令只解析出 {cmds}，太少，判据失准")

    def test_the_read_only_twin_is_not_in_the_set(self):
        """★ 反向：只读那两条**不许**被解析成发事件的 —— 否则闸会假红。"""
        cmds = emitting_commands()
        for ok in ("read_integration", "read_rotation_board"):
            self.assertNotIn(ok, cmds, f"★ `{ok}` 被误判成会发事件 —— 闸会假红")

    def test_listeners_are_actually_found(self):
        """★★ 正面证明它真的找到了监听者。找到 0 个时下面那条会静默全绿。"""
        n = sum(1 for f in SRC.rglob("*.ts*")
                if re.search(rf'listen\(\s*["\']{EVENT}["\']', _strip_comments(
                    f.read_text(encoding="utf-8"))))
        self.assertGreaterEqual(n, 3, f"只找到 {n} 个 `{EVENT}` 监听者 —— 解析器可能打空了")

    def test_it_fires_on_a_known_positive(self):
        """★★ 喂一个已知阳性（正是 2026-09-21 那份代码）看它响不响。"""
        bad = '''
          const load = useCallback(() => {
            void (async () => { await invoke<string>("run_rotate", { args: ["next"] }); })();
          }, []);
          useEffect(() => { const un = listen("state-changed", () => load()); }, [load]);
        '''
        self.assertIn("run_rotate", listener_reachable_invokes(bad),
                      "★★ 已知阳性没被抓到 —— 这个探针是坏的")

    def test_it_also_fires_on_the_bare_identifier_form(self):
        """★★ 第二个已知阳性：handler 写成**裸标识符**（codex 评审点名的漏报）。

        `listen("state-changed", load)` 里 handler 不带括号，只找 `foo(` 的解析器
        会整条漏掉 —— 而漏掉的样子与「这文件干净」一模一样。
        """
        bad = '''
          const reload = useCallback(async () => {
            await invoke("run_rotate", { args: ["health"] });
          }, []);
          useEffect(() => { const un = listen("state-changed", reload); }, [reload]);
        '''
        self.assertIn("run_rotate", listener_reachable_invokes(bad),
                      "★★ 裸标识符形态没被抓到 —— 这是已知的漏报，必须盖住")


class NoListenerCallsSomethingThatEmitsTheSameEvent(unittest.TestCase):
    """★★★ 正题：自激回环在本仓等同于「把机器打死」，而它不报任何错。"""

    def test_no_feedback_loop_in_the_frontend(self):
        emitters = emitting_commands()
        offenders = []
        for f in sorted(SRC.rglob("*.ts*")):
            src = _strip_comments(f.read_text(encoding="utf-8"))
            for cmd in listener_reachable_invokes(src):
                if cmd in emitters:
                    offenders.append(f"{f.relative_to(ROOT)} → invoke(\"{cmd}\")")
        self.assertEqual([], offenders,
                         "★★★ 自激回环：监听 `{}` 的 handler 调了会发同一事件的命令：\n  {}\n"
                         "  修法：加一条**只读**专用 IPC（照 `read_rotation_board` 的形状），"
                         "不 emit、不 refresh_tray。".format(EVENT, "\n  ".join(offenders)))


class NoReadOnlyQueryRidesTheWriteChannel(unittest.TestCase):
    """★★ 只读查询不许走会广播的写通道 —— 即使**不成环**也不行。

    2026-09-21 agy 评审发现的同族（比续航条那个轻，但是同一个病）：
    `dawn-probe --status` 是纯查询，却走着 `run_rotate`，而菜单栏 webview **每 10 分钟**
    调它一次 ⇒ 每 10 分钟平白让两个 webview 连同托盘整体重拉一遍。
    它没成环只是因为调用方恰好没监听那个事件 —— 而那是运气，不是设计。

    ★ 判据取 `--status` / `--json` 两个**只读标记**：带它们的命令按定义是「只告诉我，别做事」。
      窄、可判、且改回去必红。不去猜 `health`/`list` 这些算不算读 ——
      判据要挑**只有被测那条能挡住**的输入，含糊的判据会制造假红，而假红等于没有闸。
    """

    def test_no_run_rotate_call_carries_a_read_only_flag(self):
        offenders = []
        for f in sorted(SRC.rglob("*.ts*")):
            src = _strip_comments(f.read_text(encoding="utf-8"))
            for m in re.finditer(r'invoke\s*(?:<[^>]*>)?\s*\(\s*["\']run_rotate["\']', src):
                call = _balanced(src, m.start(), "(", ")")
                for flag in ("--status", "--json"):
                    if flag in call:
                        offenders.append(f"{f.relative_to(ROOT)}: run_rotate(… {flag} …)")
        self.assertEqual([], offenders,
                         "★★ 只读查询走了会广播 `{}` 的写通道：\n  {}\n"
                         "  修法：加一条 `read_*` 专用 IPC（见 `read_dawn_status`）。".format(
                             EVENT, "\n  ".join(offenders)))

    def test_the_read_only_subcommand_left_the_write_allowlist(self):
        """★ 专用 IPC 接管后，旧入口必须从 `ALLOWED_CMDS` 里**拆掉**。

        留着等于给那条自激回环留一条复活路径：闸挡得住新写法，
        但下一个人照样能 `run_rotate(["next"])` 把它原样造回来。
        """
        rs = _strip_comments(LIB_RS.read_text(encoding="utf-8"))
        m = re.search(r"ALLOWED_CMDS[^=]*=\s*&\[([^\]]*)\]", rs)
        self.assertIsNotNone(m, "★★ 找不到 ALLOWED_CMDS —— 断言打空了")
        cmds = re.findall(r'"([^"]+)"', m.group(1))
        self.assertIn("switch", cmds, "★★ 解析出的白名单不像真的 —— 判据失准")
        self.assertNotIn("next", cmds,
                         "★ `next` 还在写通道的白名单里 —— 它已由 `read_rotation_board` 接管")


class TheReadOnlyTwinStaysReadOnly(unittest.TestCase):
    """★ `read_*` 命令不许长出副作用 —— 它们会被 UI 按事件/定时反复调。"""

    def test_read_commands_neither_emit_nor_touch_the_tray(self):
        rs = _strip_comments(LIB_RS.read_text(encoding="utf-8"))
        bad = []
        for m in re.finditer(r"#\[tauri::command\]\s*(?:pub\s+)?(?:async\s+)?fn\s+(read_\w+)", rs):
            body = _balanced(rs, m.end(), "{", "}")
            for sin in ('emit(', 'refresh_tray('):
                if sin in body:
                    bad.append(f"{m.group(1)} 里有 {sin}")
        self.assertEqual([], bad,
                         "★ 只读命令长出了副作用（会被 UI 定期调，等于给自己造回环）：\n  "
                         + "\n  ".join(bad))


if __name__ == "__main__":
    unittest.main(verbosity=2)

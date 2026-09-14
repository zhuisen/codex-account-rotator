"""agy 的**探针 / 检查 token / 自动切号开关** —— 三条都用 agy 自己的机制，不是照搬 codex。

## 用户 2026-09-13 的原话

> 「探针做，做另外的机制，扣的是 agy 的额度啊…涉及 agy 用 agy 的逻辑啊，不是照搬 codex 的方法啊」
> 「探针做、检查 token 做、自动切号开关也要做」

## 三条各自的机制（与 codex 逐条不同）

| | codex | agy |
|---|---|---|
| 检查 token | 问 OpenAI「这个 token 被作废了吗」 | **刷一次 access_token + 打一次 `fetchAvailableModels`**，两步都过才算能用 |
| 探针 | 直接 `POST /responses` | **起一次 `agy -p`** —— agy 只在进程启动时读凭证，没有"指定号发一次请求"这种东西 |
| 自动切号 | 代理逐请求挑号 | `bin/agy` 在 **exec 真身之前**调 `agy-rotate auto`，开关存在池里 |

## ★★★ 为什么探针不能自己拼 HTTP（实测，别再试）

直接打 `v1internal:streamGenerateContent` 恒 **429 RESOURCE_EXHAUSTED**，
即使该号额度满格、模型 id 取自它自己的 `fetchAvailableModels`、也带上了
`loadCodeAssist` 回的 `aicode-consumers`。**那个 429 长得和「额度用光了」一模一样** ——
用它做探针会把"我们拼错了"报成"你的号没额度了"，正是本仓最贵的那一类错。
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = (ROOT / "agy-rotate").read_text(encoding="utf-8")
SRC = ROOT / "codexbar" / "src"
APP = SRC / "App.tsx"
CARD = SRC / "components" / "AgyCard.tsx"
HOOK = SRC / "hooks" / "useAgyPool.ts"
RS = ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs"


def code(p):
    s = p.read_text(encoding="utf-8") if isinstance(p, Path) else p
    s = re.sub(r"\{?/\*[\s\S]*?\*/\}?", "", s)
    return re.sub(r"(?<![:/])//.*", "", s)


def fn(name, src=CLI):
    """CLI 里某个函数的**函数体**（AST 切边界，不用定长切片）。"""
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            lines = src.splitlines()[n.lineno - 1:n.end_lineno]
            body = "\n".join(lines)
            # 剥注释与 docstring —— 本仓注释里正写着闸要找的那些词（空守卫形态⑫）
            body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
            d = ast.get_docstring(n, clean=False)
            return body.replace(d, "") if d else body
    raise AssertionError(f"找不到函数 {name}")


class HealthIsZeroCostAndTwoSteps(unittest.TestCase):

    def test_it_refreshes_then_calls_the_api(self):
        """★★ 两步都要。只刷不打，换来的 token 可能对 API 没权限；
        只打不刷，过期的 access_token 会把"还能用"的号报成坏的。"""
        b = fn("cmd_health")
        self.assertIn("P.refresh(", b, "★★ 没有刷 token 这一步")
        self.assertIn("P.fetch_quota(", b, "★★ 没有真打一次 API")

    def test_it_spends_nothing(self):
        """★★★ 检查 token 必须**零消耗**。混进一次生成 = 把免费按钮变成花钱按钮，
        而它旁边就站着那个花钱的探针 —— 两个按钮的区分正是靠这一条。"""
        b = fn("cmd_health")
        for bad in ("_probe_one", "streamGenerateContent", "-p"):
            with self.subTest(token=bad):
                self.assertNotIn(bad, b, f"★★★ health 里出现了 {bad} —— 它会花钱")

    def test_revoked_is_told_apart_from_a_network_blip(self):
        """★★ `invalid_grant`（掉登录，要重走 OAuth）与「网络不通」必须分开 ——
        合并成一句话，用户会对着一次网络抖动去重新登录。"""
        b = fn("cmd_health")
        self.assertIn("invalid_grant", b, "★★ 没有区分「掉登录」与「网络问题」")


class TheProbeUsesAgysOwnQuota(unittest.TestCase):

    def test_it_runs_the_real_agy(self):
        """★★★ 探针起的是 agy 真身 —— 自己拼 HTTP 恒 429（见文件头）。"""
        b = fn("_probe_one")
        self.assertIn('"-p"', b, "★★★ 没有起 agy 真身")
        self.assertIn('"--output-format", "json"', b, "★ 没要 JSON ⇒ 拿不到用量")

    def test_the_criterion_is_that_the_model_emitted_text(self):
        """★★★ 与 codex 探针同一条纪律：判据是**模型真吐出字**，不是退出码 0。
        受理了不等于干成了 —— 流中途断掉照样 exit 0。"""
        b = fn("_probe_one")
        self.assertIn('d.get("status") != "SUCCESS"', b, "★★ 没看 status")
        self.assertIn("not ans", b, "★★★ 空回答被当成成功")

    def test_it_has_a_timeout(self):
        """★ 没有上界的话，一个卡住的 agy 会把 GUI 的按钮永远钉在「探测中…」。"""
        # ⚠️ 判据必须打在**那个关键字参数**上：`PROBE_TIMEOUT` 在超时那句报错文案里
        #    也有一份，只断言"名字出现过"时把 `timeout=` 删掉照样绿（实测）。
        self.assertIn("timeout=PROBE_TIMEOUT", fn("_probe_one"), "★ 探针没有硬上限")

    def test_it_puts_the_user_back_on_their_own_account(self):
        """★★★ 非当值号要先切过去（agy 只在启动时读凭证）。
        还原必须在 `finally` 里 —— 中途炸了也不能把用户留在别的号上。"""
        b = fn("cmd_probe")
        self.assertIn("finally:", b, "★★★ 没有 finally ⇒ 异常会把用户留在别人的号上")
        i = b.index("finally:")
        self.assertIn("P.install_live(cred)", b[i:], "★★★ finally 里没有还原")

    def test_the_result_is_recorded_in_its_own_key(self):
        """★ `last_probe` 是独立兄弟键。挂进 `quota` 里会在下一次刷新时被整体替换掉 ——
        「到底探成没有」事后无从查证（codex 那边为此栽过一次）。"""
        self.assertIn('a["last_probe"]', fn("cmd_probe"))


class TheAutoSwitchTogglesAreActuallyRead(unittest.TestCase):
    """★★★ 这一组守的是**开关不能只是个摆设**。

    只把状态存进池、而 `auto` 照切，就是本仓那条「写入侧标志会撒谎」——
    界面说关着、wrapper 照样换号，而用户完全看不出来。
    """

    def test_auto_honours_the_global_switch(self):
        b = fn("cmd_auto")
        self.assertIn('pool.get("auto_off")', b, "★★★ 全局开关没被读 —— 关了也照切")

    def test_auto_honours_the_per_account_switch(self):
        b = fn("cmd_auto")
        self.assertIn('a.get("rotate_off")', b, "★★★ 按号开关没被读 —— 摘出去的号照样被挑")

    def test_the_flag_is_stored_inverted(self):
        """★★ 存**反向**（`rotate_off`）：缺省必须等于「参与轮换」——
        存量号与 `login` 收编的新号都没有这个键，正向命名要写迁移，
        漏迁移的号会**静默退出轮换池**（症状：只在那两三个号里转，零报错）。"""
        b = fn("cmd_rotate")
        self.assertIn('accs[sub]["rotate_off"] = True', b)
        # 恢复时**删键**不是写 False，否则"缺省"有两种表示
        self.assertIn('pop("rotate_off", None)', b, "★★ 恢复时写了 False 而不是删键")

    def test_the_global_flag_is_stored_inverted_too(self):
        b = fn("cmd_autoswitch")
        self.assertIn('pool.pop("auto_off", None)', b, "★★ 开启时写了 False 而不是删键")

    def test_it_refuses_to_disable_the_last_one(self):
        """★ 全关掉 = 自动切号无号可挑。与 codex 的 `rotate --off` 同一条守卫。"""
        self.assertIn("最后一个还参与轮换的号", fn("cmd_rotate"))


class TheUiWiresAllThree(unittest.TestCase):

    def test_the_bridge_allows_them(self):
        rs = code(RS)
        i = rs.index("async fn run_agy_rotate(")
        m = re.search(r'ALLOWED: &\[&str\] = &\[([^\]]*)\]', rs[i:i + 600])
        allowed = set(re.findall(r'"([a-z-]+)"', m.group(1)))
        for c in ("health", "probe", "rotate", "auto-switch"):
            with self.subTest(cmd=c):
                self.assertIn(c, allowed, f"★★ `{c}` 不在白名单 ⇒ 前端那次 invoke 必被拒")
        self.assertNotIn("login", allowed, "★★★ GUI 能跑 login —— 必然挂死")

    def test_the_gemini_tab_has_all_three(self):
        c = code(APP)
        i = c.index('{provider === "gemini" && (')
        seg = c[i:c.index('{provider === "codex" && (', i)]
        self.assertIn("agyPool.health()", seg, "★★ 没有「检查 token」")
        self.assertIn("agyPool.probe()", seg, "★★ 没有「探针 全池」")
        self.assertIn("agyPool.setAuto(", seg, "★★ 没有自动切号开关")

    def test_the_probe_button_is_the_billed_one(self):
        """★★★ 探针是这一档唯一花钱的控件，必须用 `ProbeButton`（琥珀 + ⚡ + 两段确认）。
        换成普通按钮正好抹掉它与旁边免费按钮的区分。

        ⚠️ **这条 2026-09-13 取代了相反的那一条。** 当时写的是「Gemini 档不许有 ProbeButton」，
        因为那时探针只有 codex 一套、扣的是 codex 的额度。现在 agy 有了自己的探针、
        花的是自己的额度，旧闸锁死的是一个**已经不成立的前提**。
        """
        c = code(APP)
        i = c.index('{provider === "gemini" && (')
        seg = c[i:c.index('{provider === "codex" && (', i)]
        self.assertIn("<ProbeButton", seg, "★★★ 探针不是 ProbeButton ⇒ 与免费按钮混在一起")
        self.assertIn("<ProbeButton", code(CARD), "★★★ 卡上的探针不是 ProbeButton")

    def test_a_failed_read_does_not_report_the_switch_as_off(self):
        """★★ 读不到开关状态时保持 `null`（界面显示 `—`），**不写成"关着"** ——
        「这次没探到」和「用户关了它」是两件事（本仓 §7.0b）。"""
        h = code(HOOK)
        i = h.index('"auto-switch", "--json"')
        self.assertIn("catch", h[i:i + 260], "★ 没有兜住读失败")
        self.assertNotIn("setAutoOn(false)", h, "★★ 读不到就写成「关」")


class TheHarnessCanExerciseThem(unittest.TestCase):
    """★★★ 打桩缺口 = 零渲染，而零渲染的页面量出来正好是「零溢出、零报错」。

    2026-09-13 真踩到：这两条分支里把载荷写成了 `a.args`（stub 的签名是
    `invoke(cmd, args)`），`a` 不在作用域 ⇒ ReferenceError ⇒ 被调用方的 `catch` 吞掉 ⇒
    **`errors` 探针里一个字都没有**，页面只是安静地少了「当前」徽章与开关状态。
    """

    H = (ROOT / "codexbar" / "uishot" / "make_harness.py").read_text(encoding="utf-8")

    def test_the_stub_reads_the_right_payload_name(self):
        # ⚠️ **必须先剥注释**：上面那段说明里正写着 `a.args` 三个字（它在解释这个坑），
        #    不剥的话这条闸恒红 —— 本仓空守卫形态⑫，今天已经踩到第二次。
        seg = code(self.H)
        i = seg.index("case 'run_agy_rotate':")
        seg = seg[i:i + 1200]
        self.assertNotIn("a.args", seg.replace("args.args", ""),
                         "★★★ 又把载荷写成了 `a.args` —— `a` 不在作用域")
        self.assertIn("args.args", seg)

    def test_both_toggle_states_can_be_rendered(self):
        self.assertIn("p.get('agyauto')", self.H, "★★ 关掉那一态渲染不出来")

    def test_the_per_account_switch_can_be_rendered(self):
        self.assertIn("rotate_off", self.H, "★★ 按号开关那一档没有夹具")


if __name__ == "__main__":
    unittest.main()


class EveryOperationLeavesATrace(unittest.TestCase):
    """★★ 用户 2026-09-14：「运行日志也需要更新，例如我不同账号的探针、刷新等详细的操作，
    成功与否都要显示出来」。

    此前 agy 这一侧**一个字都不落盘** —— 界面上点了什么、结果如何，事后完全无从复盘
    （codex 那侧有 `proxy.log` / `quotad.log`）。而探针是**花钱**的动作，
    「到底探成没有、花了多少」只能从这里查；codex 那边为同一件事栽过一次
    （`last_probe` 那条：写回的 quota 会被整体替换，事后找不到 `source == "probe"`）。
    """

    def test_every_write_command_logs(self):
        for name in ("cmd_switch", "cmd_auto", "cmd_health", "cmd_probe", "cmd_quota"):
            with self.subTest(cmd=name):
                self.assertIn("_log(", fn(name), f"★★ {name} 不留痕 —— 事后无从复盘")

    def test_the_probe_logs_success_and_cost(self):
        """★★★ 成败与用量**都要**写进去。只写"跑过了"等于把最贵的那条信息丢掉。"""
        b = fn("cmd_probe")
        # ⚠️ 窗口必须**只圈住那一次 `_log(` 调用**：紧挨着的 `print(` 行里有一模一样的
        #    `"✓" if ok else "✗"`，定长切片会连它一起圈进来 ⇒ 把 `_log` 改坏了闸照样绿
        #    （实测，本仓「定长切片滑进下一段」那一族）。
        i = b.index('_log("probe')
        seg = b[i:b.index("\n", i)]
        self.assertIn('"✓" if ok else "✗"', seg, "★★★ 日志里看不出成败")
        self.assertIn("tok", seg, "★★ 日志里没有用量 —— 花了多少无从查证")

    def test_logging_never_breaks_the_operation(self):
        """★ 写不了日志绝不能让操作本身失败 —— 日志是附加品。"""
        b = fn("_log")
        self.assertIn("except Exception:", b, "★ `_log` 不是 fail-open")

    def test_the_file_has_an_upper_bound(self):
        """★ 这个文件由 GUI 按钮驱动，没人会去轮转它 —— 放任下去就是只增不减。"""
        b = fn("_log")
        self.assertIn("_LOG_KEEP", b, "★ 日志没有上界")

    def test_it_lands_in_the_store_not_next_to_the_script(self):
        """★★ 落点跟 store 走，不跟脚本走 —— 脚本会被打进 app（只读、更新即抹掉）。
        与 `AGY_POOL_STORE` 那次是同一条。"""
        self.assertIn("AGY_LOG = P.STORE /", CLI, "★★ 日志落在脚本旁边了")

    def test_the_ui_reads_it(self):
        """★★★ 只写不读等于没写。判据打在**读取那一侧**。"""
        rs = code(RS)
        i = rs.index("fn read_logs()")
        self.assertIn('"agy.log"', rs[i:i + 500], "★★★ 日志页不读 agy.log")

    def test_failures_are_not_the_same_colour_as_successes(self):
        """★★ `✗` 行和成功行同色，等于把"成功与否"藏起来 —— 用户点名要看的就是这个。"""
        lp = code(ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx")
        self.assertIn('l.text.includes("✗")', lp, "★★ 失败行没有单独染色")

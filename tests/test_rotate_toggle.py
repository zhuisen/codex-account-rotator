"""按号开关自动轮换(用户 2026-09-07:「A 账号我不想轮换,就禁掉,在总览界面操作」)。

## 三条不变量,每条都能静默出错

**① 缺省必须等于「参与轮换」。** 存的是 `rotate_off` 而不是 `rotate_enabled` ——
autosync 新入池的号和所有存量号都**没有**这个键。用正向命名就得写迁移,而漏迁移的号会
**静默退出轮换池**:症状是"代理只用那两三个号",没有任何地方会报错。
同理「恢复」必须**删键**而不是写 `False` —— 写了 `False` 就等于给"缺省"造了第二种表示,
下一个读它的人只要写 `slot.get("rotate_off") is None` 就会判错。

**② 不许关掉最后一个。** 全关 = 代理无号可挑 = codex 整个不能用。这条路是一步步走到的,
每一步看着都合理,直到最后一次 `--off` 把工具变砖。所以拦在动作发生的地方。

**③ 停用必须真的影响选号,而且连会话粘性一起。** 只把标记写进 state.json 而 `_pick` 不看,
是本仓点名过的「后端有字段 ≠ 已生效」形态 —— 界面显示"已停用",代理照用不误。
粘性(`conv`/`affinity`)尤其危险:一段已经粘在 A 上的对话会继续用 A,
而用户以为自己已经把它摘出去了。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CODEX_ROTATE_STORE", str(ROOT))
_spec = importlib.util.spec_from_file_location("px_rot", ROOT / "proxy" / "proxy.py")
PX = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PX)


def slot(label, **kw):
    d = {"label": label, "plan": "plus",
         "quota": {"primary": {"window_minutes": 300, "used_percent": 10.0, "resets_at": None},
                   "secondary": {}}}
    d.update(kw)
    return d


class CliContract(unittest.TestCase):
    """① 与 ② —— 真跑 CLI,但**只在临时 store 上**:绝不碰真实 state.json/auth。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cbx_rotate_")
        os.makedirs(os.path.join(self.dir, "auth"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "codex-home"), exist_ok=True)
        self.state = os.path.join(self.dir, "state.json")
        with open(self.state, "w", encoding="utf-8") as fh:
            json.dump({"active": "a1", "slots": {
                "a1": {"label": "plusA", "plan": "plus", "file": "a1.json"},
                "a2": {"label": "plusB", "plan": "plus", "file": "a2.json"},
            }}, fh)
        # ★ 2026-09-09 补:暂停当值号时 CLI 会**先把 live auth 交接出去**,所以
        #   fixture 必须有可读的凭证文件,否则测的是"交接失败"这条分支而不是主路径。
        #   原来的 fixture 没有它们 —— 语义扩大后这三条测试立刻变红,红得有信息量。
        #   ⚠️ 全是假凭证,只在 tmpdir 里,绝不碰真实 auth/。
        for name in ("a1.json", "a2.json"):
            with open(os.path.join(self.dir, "auth", name), "w", encoding="utf-8") as fh:
                json.dump({"tokens": {"access_token": "TESTONLY", "account_id": name[:2]}}, fh)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_cli(self, *args):
        # ★ CODEX_HOME 也要设 —— `LIVE = CODEX_HOME / "auth.json"` 不看 STORE。
        env = dict(os.environ, CODEX_ROTATE_STORE=self.dir,
                   CODEX_HOME=os.path.join(self.dir, "codex-home"))
        return subprocess.run([sys.executable, str(ROOT / "codex-rotate"), "rotate", *args],
                              capture_output=True, text=True, env=env)

    def slots(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)["slots"]

    def test_fresh_account_rotates_without_any_key(self):
        """★ 缺省 = 参与。新号槽位里没有这个键,不能因此被排除。"""
        self.assertNotIn("rotate_off", self.slots()["a1"])
        self.assertTrue(PX.__dict__ and not self.slots()["a1"].get("rotate_off"))

    def test_off_then_on_removes_the_key_instead_of_writing_false(self):
        self.assertEqual(self.run_cli("plusA", "--off").returncode, 0)
        self.assertIs(self.slots()["a1"]["rotate_off"], True)
        self.assertEqual(self.run_cli("plusA", "--on").returncode, 0)
        # ★★ 必须**删键**。写 `False` 会给"缺省"造出第二种表示,
        #    下一个用 `is None` 判断的人就会判错。
        self.assertNotIn("rotate_off", self.slots()["a1"],
                         "恢复轮换时写了 False 而不是删键 —— 缺省从此有两种表示")

    def test_refuses_to_disable_the_last_one(self):
        self.run_cli("plusA", "--off")
        r = self.run_cli("plusB", "--off")
        self.assertNotEqual(r.returncode, 0, "把最后一个号也停用了 —— 代理将无号可挑")
        self.assertIn("最后一个", r.stdout + r.stderr)
        self.assertFalse(self.slots()["a2"].get("rotate_off"), "被拒绝了却还是写进了盘")

    def test_accepts_aid_not_only_label(self):
        """★ UI 传的是 aid 不是 label(重名时 label 会指到错的号上)。"""
        self.assertEqual(self.run_cli("a1", "--off").returncode, 0)
        self.assertIs(self.slots()["a1"]["rotate_off"], True)

    def test_unknown_target_fails_loudly(self):
        r = self.run_cli("nope", "--off")
        self.assertNotEqual(r.returncode, 0)


class PickerHonoursTheFlag(unittest.TestCase):
    """③ —— 判据打在**真正的 `_pick` 行为**上,不是"源码里有那个字段"。"""

    def _pick(self, slots, prev_id=None, conv=None):
        """★ `_pick` 自己从盘上 `_load(STATE)`,所以必须**打桩读盘**。
        不打桩它就会读**真实的 `state.json`** —— 那既让断言依赖真实池子(随时会变),
        也违反本仓「测试不得读真实 auth/state」那条铁律。"""
        real = PX._load
        PX._load = lambda _p: {"slots": slots, "active": None}
        try:
            return PX._pick(prev_id, conv=conv)
        finally:
            PX._load = real

    def test_disabled_account_is_never_picked(self):
        aid, _sl, _why = self._pick({
            "a1": slot("plusA", rotate_off=True),
            "a2": slot("plusB"),
        })
        self.assertEqual(aid, "a2", "被停用的号仍然被选中了 —— 界面说停用,代理照用")

    def test_conv_stickiness_also_respects_it(self):
        """★★ 粘性必须一起过闸。一段已经粘在 A 上的对话若继续用 A,
        用户会以为自己已经把它摘出去了,而没有任何提示。"""
        slots = {"a1": slot("plusA", rotate_off=True), "a2": slot("plusB")}
        PX._conv["c-1"] = "a1"
        try:
            aid, _sl, why = self._pick(slots, conv="c-1")
            self.assertEqual(aid, "a2", "会话粘性绕过了「停用轮换」")
            self.assertNotEqual(why, "conv")
        finally:
            PX._conv.pop("c-1", None)

    def test_all_disabled_falls_back_instead_of_bricking(self):
        """★★ 全被停用时**忽略该设置**而不是返回 exhausted。

        CLI 已拒绝关掉最后一个,所以这里只可能来自手改 state.json 或竞态。
        在「codex 整个不能用」与「多用了一个不想用的号」之间选后者 ——
        前者会让每个请求都失败,而 502 实测被 codex 重试 30 次,越修越糟。
        """
        aid, _sl, _why = self._pick({
            "a1": slot("plusA", rotate_off=True),
            "a2": slot("plusB", rotate_off=True),
        })
        self.assertIsNotNone(aid, "全部停用后代理直接无号可用 —— 工具变砖")

    def test_the_fallback_is_not_silent(self):
        """★ 兜底必须留痕。悄悄绕过用户的设置,比不兜底更糟 ——
        用户没有任何办法发现"我关掉的号还在被用"。"""
        src = (ROOT / "proxy" / "proxy.py").read_text(encoding="utf-8")
        i = src.index("def _pick(")
        body = src[i:src.index("\ndef ", i + 10)]
        j = body.index("relaxed = [")
        self.assertIn("_plog(", body[j:j + 700],
                      "全停用兜底没有写日志 —— 设置被绕过而用户看不见")

    def test_a_dead_account_is_still_excluded(self):
        """反向:这条开关不该把别的排除条件顶掉。"""
        aid, _sl, _why = self._pick({
            "a1": slot("plusA", auth_dead=True),
            "a2": slot("plusB"),
        })
        self.assertEqual(aid, "a2")


class UiIsWiredToTheCli(unittest.TestCase):
    """★ 开关必须走 CLI,**不能走 localStorage** —— 代理在 app 没开时也要读这个设置,
    两个真源迟早分叉成「界面说停用了、代理还在用」(同 dawn-probe 那个开关)。"""

    def test_toggle_invokes_the_cli(self):
        app = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
        i = app.index("onToggleRotate=")
        body = app[i:i + 400]
        self.assertIn('"rotate"', body, "开关没有调 `codex-rotate rotate`")
        self.assertNotIn("localStorage", body, "开关写了 localStorage —— 真源分叉")
        self.assertIn("a.aid", body, "传的是 label 不是 aid —— 重名会操作到错的号上")

    def test_command_is_whitelisted(self):
        rs = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        i = rs.index("const ALLOWED_CMDS")
        self.assertIn('"rotate"', rs[i:i + 400],
                      "`rotate` 不在白名单里 —— 按钮点了会被 Rust 直接拒掉")

    def test_card_toggles_to_the_opposite_of_the_current_state(self):
        """★ 判据打在 **onClick 传的值**上,不是"`a.rotates` 这个词出现过" ——
        它同时出现在 title 与样式里,把 onClick 改成恒传 `true`(开关只能开不能关)时
        第一版断言照样绿(变异测试抓到)。本仓空守卫六型里的第 ② 型。"""
        card = (ROOT / "codexbar" / "src" / "components" / "AccountCard.tsx").read_text(encoding="utf-8")
        i = card.index("onToggleRotate(")
        self.assertIn("!a.rotates", card[i:i + 60],
                      "开关没有传当前状态的取反 —— 它会变成单向的,关不掉或开不回来")


if __name__ == "__main__":
    unittest.main()

"""代理轮换泳道的**身份**不变量（2026-09-12，用户实报）。

## 用户看到的

「总览我为我的账号更改名字了，代理轮换版块没有匹配上我对应的名字，而是变成新建名字」

实测当时（24h 窗口，真实数据）：

    plus7    122 req   ← 旧名
    Huo       12 req   ← 同一个号的新名，被画成**另一条泳道**
    plus6     10 req
    TokenDun   5 req   ← **中转站上游**，根本不是账号
    ...

## 两条根因，同一个形状

★★★ **`proxy.log` 里 `[...]` 里的东西是「显示名」，不是身份。** 它有两个毛病：

  ① **label 用户可改，而日志是只追加的历史。** 改名之前写下的行永远停在旧名字上 ⇒
     同一个号劈成两条泳道，且旧名那条在池子里查不到 ⇒ **plan / 额度 / 配色全丢**。
     这与四方评审 #4（dawn-probe 把 label 当 argv）是同一条根：**身份必须是 aid**。
  ② **账号和中转站上游共用同一个句式**（`→ POST /responses [X] …`），没有类型标记 ⇒
     下游**没有任何办法**分辨，于是中转站被当成账号画进泳道。

## 修法

`proxy.py` 的标签带上身份与类型（`Huo#b42e395c` / `TokenDun@relay`），
`rotation.py` 三路解析 + 把历史名字归一成当前 label，`rename` 记 `label_history`。

⚠️ **历史行不会消失**（本机 8MB），所以每条修法都必须对**裸名字**的旧行也成立 ——
下面每组闸都有一条专门打在旧格式上。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "traffic"))
import rotation as R                                              # noqa: E402

CLI = str(ROOT / "codex-rotate")
AID_A = "b42e395c-fb04-4175-b47e-e86b68a1d447"
AID_B = "d0a53c97-49ec-4a68-a863-81884dabdeb9"


def line(ts, body, rid=None):
    return "[proxy %s%s] %s" % (ts, (" #" + rid) if rid else "", body)


def post(ts, tag, reason="least-used"):
    return line(ts, "→ POST /responses [%s] %s conv=- body=-" % (tag, reason))


class TagParsing(unittest.TestCase):
    """五种形态都要认对。★ 后三种是**历史行**，它们永远不会消失。"""

    CASES = [
        ("→ POST /r [Huo#b42e395c] x",          ("Huo", "b42e395c", "acct")),
        ("→ POST /r [TokenDun@relay] relay",    ("TokenDun", None, "relay")),
        ("→ POST /r [plus6] affinity conv=a",   ("plus6", None, "acct")),
        ("→ POST /r [TokenDun] relay conv=-",   ("TokenDun", None, "relay")),
        ("relay stream err [Huohuo]: boom",     ("Huohuo", None, "relay")),
    ]

    def test_every_shape(self):
        for body, want in self.CASES:
            with self.subTest(body=body):
                self.assertEqual(R._first_tag(body), want)

    def test_the_errno_ghost_is_still_excluded(self):
        """★ 既有不变量：只取第一个方括号组。`[Errno 32]` 会造出一个幽灵账号，
        而它在泳道里长得和真账号一模一样。"""
        self.assertEqual(R._first_tag("stream err [plus5]: [Errno 32] Broken pipe")[0], "plus5")

    def test_a_label_containing_a_hash_is_not_chopped(self):
        """★★ 按**后缀形状**判，不是「含 # 就当身份」。`cmd_rename` 只禁空白，
        所以 `a#b` 是合法名字 —— 切掉一截之后仍是个合法名字，**不报错**。"""
        self.assertEqual(R._first_tag("← 200 [a#b]"), ("a#b", None, "acct"))
        self.assertEqual(R._first_tag("← 200 [x#deadbeef]"), ("x", "deadbeef", "acct"))

    def test_an_over_long_tag_is_dropped_not_truncated(self):
        self.assertEqual(R._first_tag("→ POST /r [%s] x" % ("z" * 65))[0], None)


class RenameKeepsOneLane(unittest.TestCase):
    """★★★ 用户报的那一条。"""

    LOG = "\n".join([
        post("09-12 10:00:00", "plus6"),                 # 改名前（历史行，裸名字）
        post("09-12 10:01:00", "plus6"),
        post("09-12 10:02:00", "Huo#b42e395c"),          # 改名后（新格式）
    ])

    def _accs(self, slots):
        reqs, _, _, _, _, _ = R.scan_proxy_log(
            self.LOG, now=_now(), start=0, end=2 ** 31,
            resolve=R.make_resolver(slots))
        out = {}
        for _ts, acc, _b in reqs:
            out[acc] = out.get(acc, 0) + 1
        return out

    def test_without_history_they_split(self):
        """★ 先证**基线是红的**：没有这一条，下一条测的可能是「它永远只有一条」。"""
        slots = {AID_A: {"label": "Huo"}}
        self.assertEqual(self._accs(slots), {"plus6": 2, "Huo": 1})

    def test_with_history_they_merge_under_the_current_name(self):
        slots = {AID_A: {"label": "Huo", "label_history": ["plus6"]}}
        self.assertEqual(self._accs(slots), {"Huo": 3},
                         "★★★ 改名后泳道仍被劈成两条（用户实报的那个缺陷）")

    def test_the_aid_suffix_alone_survives_a_rename_with_no_history(self):
        """★★ 这才是硬的那一半：带 `#aid8` 的行**不需要** `label_history` 也认得回来。
        历史表是给改格式之前那些裸名字行的补救，不是主判据。"""
        slots = {AID_A: {"label": "Huo"}}
        reqs, _, _, _, _, _ = R.scan_proxy_log(
            post("09-12 10:02:00", "plus6#b42e395c"), now=_now(), start=0, end=2 ** 31,
            resolve=R.make_resolver(slots))
        self.assertEqual([a for _t, a, _b in reqs], ["Huo"],
                         "★ aid 对得上却没归一 —— 那 `#aid8` 白加了")

    def test_an_ambiguous_aid_prefix_is_not_resolved(self):
        """★★ 宁可不并，也不并错。两个槽位撞前 8 位时解析到错的号，
        会把 A 的 token 记到 B 头上，而**画出来完全正常**。"""
        slots = {"abcdef12-1": {"label": "One"}, "abcdef12-2": {"label": "Two"}}
        self.assertEqual(R.make_resolver(slots)("whatever", "abcdef12"), "whatever")

    def test_an_unknown_label_is_kept_not_invented(self):
        """★ 查不到就原样返回。号可能真的被删了，把它并进别的号是更糟的错。"""
        self.assertEqual(R.make_resolver({AID_A: {"label": "Huo"}})("ghost", None), "ghost")


class RelayIsNeverAnAccount(unittest.TestCase):
    """★★ 中转站上游不是账号。两种格式都要挡 —— 只挡新格式等于只修未来，
    而用户看的正是历史窗口。"""

    def _accs(self, log):
        reqs, owner, markers, _, _, _ = R.scan_proxy_log(
            log, now=_now(), start=0, end=2 ** 31, resolve=lambda n, a: n)
        return ({a for _t, a, _b in reqs} | {a for _t, a, _k in markers}
                | set(owner.values()))

    def test_the_suffix_alone_excludes_an_affinity_line(self):
        """★★★ **只有后缀能挡的那条路径。**

        ⚠️ 这条闸的第一版用的是 `→ POST … [TokenDun@relay] relay`，而那行的 reason
        **也是** `relay` ⇒ 历史探测器同样能挡它 ⇒ 把 `@relay` 分支整个删掉，闸照样绿
        （空心闸形态⑩：绿是**另一条** early-return 给的）。变异工具当场拦下。

        `affinity resp_x → [X]` 是唯一一种「带 `@relay` 但 reason 不是 relay、
        行首也不是 `relay `」的行 —— `_finish` 对中转站和账号是同一段代码。
        它写的是 `resp_owner`，也就是 **token 归属的 join 键**：漏挡的后果不是多画一条泳道，
        是把中转站的消耗算成某个账号的。
        ★ 真实日志里目前**零条**（中转站的响应没匹配上 `_RESP_ID`），
          但那是「至今没发生」不是「不可能」—— 中转站是 OpenAI 兼容的，回 `resp_` 就会写。
        """
        log = line("09-12 10:00:00", "affinity resp_abc → [TokenDun@relay]", rid="resp_abc")
        self.assertEqual(self._accs(log), set(),
                         "★★★ 中转站被当成 token 归属对象 —— 它的消耗会记到账号头上")

    def test_a_real_account_affinity_line_still_attributes(self):
        """★ 反向闸：挡得太宽会让真账号的归属整个失效，而症状是「已归属 token」变成 0。"""
        log = line("09-12 10:00:00", "affinity resp_abc → [plus6]", rid="resp_abc")
        self.assertEqual(self._accs(log), {"plus6"})

    def test_new_format_relay_request_is_excluded(self):
        self.assertEqual(self._accs(post("09-12 10:00:00", "TokenDun@relay", "relay")), set())

    def test_legacy_relay_is_excluded_too(self):
        """★★★ 这一条才是用户现在看得到的 —— 本机 8MB 旧日志全是裸名字。"""
        self.assertEqual(self._accs(post("09-12 10:00:00", "TokenDun", "relay")), set())

    def test_a_real_account_on_the_same_shape_still_counts(self):
        """★ 反向闸。挡得太宽就把真账号一起挡了，而症状是泳道莫名变空。"""
        self.assertEqual(self._accs(post("09-12 10:00:00", "plus6", "affinity")), {"plus6"})

    def test_relay_stream_errors_do_not_become_account_markers(self):
        self.assertEqual(self._accs(line("09-12 10:00:00", "relay stream err [Huohuo]: boom")),
                         set())

    def test_a_real_stream_error_still_marks_its_account(self):
        self.assertEqual(self._accs(line("09-12 10:00:00", "stream err [plus6]: boom")),
                         {"plus6"})


class RetiredNamesDoNotPoseAsAccounts(unittest.TestCase):
    """★★ 用户 2026-09-12：「修改代理轮换已废弃的名字」。

    `make_resolver` 把**改过名**的历史行并回了当前 label。但号被 `remove` 掉之后
    （或 autosync 造出来的幽灵槽被清掉），它的旧名在池子里永远查不到 ——
    于是它继续以一条**看起来和真账号一模一样**的泳道出现，没有 plan / 额度 / 配色。

    ★ 两种情形处置**故意不同**，它们不是同一件事：
      · 窗口内零活动 → 整条丢掉（什么都没证明，留着只是噪音）；
      · 窗口内有活动 → **必须留下并标记**。那些消耗/失败真的发生过，
        丢掉会让合计悄悄变小 —— 本仓不许静默丢数据。
    """

    SRC = (ROOT / "traffic" / "rotation.py").read_text(encoding="utf-8")

    def test_the_two_cases_are_handled_differently(self):
        i = self.SRC.index("live = set(slots)")
        seg = self.SRC[i:i + 420]
        self.assertIn("del accs[a]", seg, "★ 零活动的退役名字没有被丢掉")
        self.assertIn("markers", seg,
                      "★★ 判据只看了 requests/tokens —— 只有 marker 的号（比如全是 send err）"
                      "会被当成零活动丢掉，而那正是它被移除的原因")

    def test_activity_is_measured_on_all_three_signals(self):
        """★ `requests` 对 GET 恒为 0（只有计费 POST 才切段）。只看它的话，
        一个今天真的失败了 4 次的号会被判成「什么都没发生」。"""
        i = self.SRC.index("live = set(slots)")
        seg = self.SRC[i:i + 420]
        for sig in ('r["requests"]', 'r["tokens"]', "m[1] == a"):
            self.assertIn(sig, seg, f"★ 活动判据少了 {sig}")

    def test_live_accounts_are_never_flagged(self):
        i = self.SRC.index('"retired":')
        self.assertIn('a["acc"] not in live', self.SRC[i:i + 80],
                      "★ retired 的判据不是「不在当前池里」—— 会把在池号也标成退役")

    def test_the_ui_only_recolours_and_never_adds_a_badge(self):
        """★★ 泳道名字列宽写死 152px 且**刻意不加省略号**，多一个徽章会把名字截成 `Pr…`,
        而这类缺陷 harness 抓不到（`textOverflow` 只改渲染，DOM 文本仍完整）。"""
        ts = (ROOT / "codexbar" / "src" / "pages" / "LogsPage.tsx").read_text(encoding="utf-8")
        # ⚠️ 第一版断言的是**字符串** `color:`，而把条件删成 `color: undefined` 之后
        #    那个字符串还在 ⇒ 闸照样绿（变异工具当场拦下）。判据必须打在**绑定**上：
        #    颜色是不是由 `retired` 决定，而不是"这行里出现过 color 这个词"。
        self.assertRegex(ts, r"color:\s*l\.retired\s*\?",
                         "★ 名字颜色不再由 retired 决定 —— 这个状态在界面上就不存在了")
        i = ts.index("color: l.retired")
        seg = ts[max(0, i - 400):i + 200]
        self.assertNotIn("borderRadius", seg, "★ 加了徽章 —— 名字列会被挤到截断")


def _store(slots):
    d = tempfile.mkdtemp(prefix="rot-ident-")
    Path(d, "state.json").write_text(json.dumps({"slots": slots}), encoding="utf-8")
    Path(d, "auth").mkdir(exist_ok=True)
    return d


def _run(store, *args):
    return subprocess.run([sys.executable, CLI, *args],
                          env=dict(os.environ, CODEX_ROTATE_STORE=store),
                          capture_output=True, text=True, timeout=120)


def _slots(store):
    return json.loads(Path(store, "state.json").read_text(encoding="utf-8"))["slots"]


class RenameRecordsTheOldName(unittest.TestCase):
    """★★★ 没有这一步，上面那些解析全是空转 —— 表里根本不会有历史名字。"""

    def test_rename_appends_to_label_history(self):
        d = _store({AID_A: {"label": "plus6", "file": "x.json"}})
        p = _run(d, "rename", "plus6", "Huo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(_slots(d)[AID_A]["label_history"], ["plus6"])

    def test_renaming_twice_keeps_both_old_names(self):
        """★ 链式改名：`plus6 → Tmp → Huo`，两段历史的日志都要能并回来。"""
        d = _store({AID_A: {"label": "plus6", "file": "x.json"}})
        _run(d, "rename", "plus6", "Tmp")
        _run(d, "rename", "Tmp", "Huo")
        self.assertEqual(_slots(d)[AID_A]["label_history"], ["plus6", "Tmp"])

    def test_renaming_back_does_not_leave_the_current_name_in_history(self):
        """★★ `plus6 → Huo → plus6` 之后，历史里留着 `Huo` 是对的，
        但**当前名字绝不能出现在自己的历史里** —— 那会让解析器看到两个候选而放弃。"""
        d = _store({AID_A: {"label": "plus6", "file": "x.json"}})
        _run(d, "rename", "plus6", "Huo")
        _run(d, "rename", "Huo", "plus6")
        h = _slots(d)[AID_A].get("label_history") or []
        self.assertNotIn("plus6", h)
        self.assertIn("Huo", h)


class AliasClaimsAnOldName(unittest.TestCase):
    """★ `rename` 从 2026-09-12 才记历史 —— 在那之前改过的名字只能由用户补。"""

    def test_alias_is_recorded(self):
        d = _store({AID_A: {"label": "Huo", "file": "x.json"}})
        p = _run(d, "alias", "plus6", "Huo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(_slots(d)[AID_A]["label_history"], ["plus6"])

    def test_an_old_name_cannot_point_at_two_accounts(self):
        """★★ 判据打在**冲突**上。一个名字指向两个号时解析器会放弃，
        于是这条 alias 静默无效 —— 那比报错糟得多。"""
        d = _store({AID_A: {"label": "Huo", "label_history": ["plus6"], "file": "x.json"},
                    AID_B: {"label": "Egan", "file": "y.json"}})
        p = _run(d, "alias", "plus6", "Egan")
        self.assertNotEqual(p.returncode, 0, "重复认领没有报错 —— 它会静默失效")
        self.assertIn("Huo", p.stderr + p.stdout)

    def test_claiming_its_own_current_name_is_refused(self):
        d = _store({AID_A: {"label": "Huo", "file": "x.json"}})
        self.assertNotEqual(_run(d, "alias", "Huo", "Huo").returncode, 0)


def _now():
    """固定"现在"：日志时间戳不带年份，`parse_proxy_ts` 要靠 now 补年。
    取 2026-09-12 23:59:59 本地时间，保证 09-12 的行落在它之前。"""
    import datetime
    return datetime.datetime(2026, 9, 12, 23, 59, 59).timestamp()


if __name__ == "__main__":
    unittest.main()

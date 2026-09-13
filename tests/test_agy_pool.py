"""agy 账号池的不变量（2026-09-13，用户要「agy 额度更新 + 自动轮换」）。

## 这一池与 codex 池的**结构性**差异，决定了下面每一条

| | codex | agy |
|---|---|---|
| 请求路径 | 经本地代理 → 每请求都能换号 | CLI 直连 Google，**没有代理** |
| 换号时机 | 代理里挑 | **启动前**换凭证文件（agy 只在启动时读它） |
| 额度 | 免费 GET `/usage` | `fetchAvailableModels`，**每账号**、零消耗、不需要 agy 在跑 |

## 实测记录（都是判据的来源，不是背景）

- ★★ `fetchAvailableModels` 的**三个请求头是必需的**：只带 Bearer → **403**。
- ★★ **刷新不会轮换 `refresh_token`**（响应里没有该字段）⇒ 刷新不作废 agy 自己那份。
  ⚠️ 与本仓对 grok 的铁律**正好相反**（grok 单次有效），照搬任何一边都会出事。
- ★★ agy 二进制里两个 client secret **首尾相连、无分隔符**；贪婪正则会把它俩粘成一个
  47 字符的串 → `invalid_client`，而那个报错与「凭证坏了」长得一模一样。
- ★★ 能用的 (client_id, secret) 是**交叉**配对的 —— 按出现顺序配会失败。

## ★ 本文件绝不碰真实数据

`AGY_POOL_STORE` / `AGY_TOKEN_FILE` 全部指向临时目录。**那个 token 文件是用户唯一的
agy 登录凭证**，写坏的代价是他要重新走一遍浏览器 OAuth —— 这不是"测试残留"级别的事故。
"""
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_pool(store, token_file):
    """在隔离目录下现载一份 `agy.pool`（模块级常量读 env，所以要在设好之后再 import）。"""
    os.environ["AGY_POOL_STORE"] = str(store)
    os.environ["AGY_TOKEN_FILE"] = str(token_file)
    spec = importlib.util.spec_from_file_location("agy_pool_t", ROOT / "agy" / "pool.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _sub_of(token_file):
    """当前登录态是哪个号。"""
    import base64
    d = json.loads(Path(token_file).read_text(encoding="utf-8"))
    p = d["id_token"].split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))["sub"]


def _cred(sub="u1", email="a@b.c", exp=4102444800):
    """造一份形状与真实凭证一致的假凭证（`id_token` 只需 base64 载荷可解）。"""
    import base64
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": sub, "email": email, "aud": "cid-1"}).encode()).decode().rstrip("=")
    return {"auth_method": "consumer", "id_token": "h.%s.s" % payload,
            "token": {"access_token": "at", "refresh_token": "rt",
                      "token_type": "Bearer", "expiry": "2099-01-01T00:00:00+00:00"}}


class TheAgyPoolStaysOutOfTheCodexSlots(unittest.TestCase):
    """★★★ 这是整池分开存放的**唯一理由**，也是最危险的那条。

    `state.json` 的 `slots` 里每一个 key 都会被 codex 的刷新器遍历
    （`_pick` / `cmd_keepalive` / `cmd_refresh_all`），而 `cmd_keepalive` 就是
    **拿 refresh_token 去打 OpenAI 的端点**。把 Google 的凭证放进去 = 进了那台刷新器的射程。
    本仓对 grok 的处置是一字不差的同一条理由。
    """

    SRC = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")
    CLI = (ROOT / "agy-rotate").read_text(encoding="utf-8")

    def test_the_pool_file_is_its_own_sidecar(self):
        self.assertIn('POOL = STORE / ".agy-pool.json"', self.SRC)

    def test_nothing_here_writes_state_json(self):
        """⚠️ 判据必须**只看代码**。第一版直接 `assertNotIn("state.json", 源码)`，
        而这两个文件的说明里正解释着「为什么不放进 state.json」—— 闸被自己的注释判红了
        （空心闸形态④的反面：假红）。一条会假红的闸，用户学会的是忽略它。"""
        import ast as _ast
        for name, src in (("agy/pool.py", self.SRC), ("agy-rotate", self.CLI)):
            with self.subTest(file=name):
                lits = [n.value for n in _ast.walk(_ast.parse(src))
                        if isinstance(n, _ast.Constant) and isinstance(n.value, str)]
                # 文档字符串是模块/类/函数体的第一个语句，不在这里剔除会把说明也算成代码；
                # 用"这个字面量有没有被当成路径用"更直接：看它是不是出现在非 docstring 的字面量里。
                docs = set()
                for n in _ast.walk(_ast.parse(src)):
                    if isinstance(n, (_ast.Module, _ast.FunctionDef, _ast.ClassDef)):
                        d = _ast.get_docstring(n, clean=False)
                        if d:
                            docs.add(d)
                code_lits = [x for x in lits if x not in docs]
                hit = [x for x in code_lits if "state.json" in x]
                self.assertEqual(hit, [],
                                 "★★★ agy 的代码碰了 state.json —— 凭证会进 codex 刷新器的射程")

    def test_credentials_live_in_their_own_directory(self):
        self.assertIn('CRED_DIR = STORE / "auth" / "agy"', self.SRC)

    def test_the_pool_file_is_gitignored(self):
        ig = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".agy-pool.json", ig,
                      "★ 池里有 OAuth client 与账号元数据 —— 仓库是公开的")


class NoOAuthSecretIsCommitted(unittest.TestCase):
    """★★★ 刷新需要 agy 那套 client_id + secret，但**这个仓库是公开的**。

    它们本来就印在用户机器上的 agy 二进制里，所以运行时现取。
    第一版我把 secret 硬编进了源码，提交时被 `secrets-scan` 钩子当场拦下 —— 那一拦是对的。
    """

    def test_no_google_client_secret_in_the_tree(self):
        bad = []
        for p in list(ROOT.glob("agy/*.py")) + [ROOT / "agy-rotate", ROOT / "bin" / "agy"]:
            if re.search(r"GOCSPX-[A-Za-z0-9_\-]{20,}", p.read_text(encoding="utf-8")):
                bad.append(p.name)
        self.assertEqual(bad, [], f"★★★ {bad} 里硬编了 Google client secret")

    def test_it_is_extracted_from_the_local_binary(self):
        src = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")
        self.assertIn("AGY_BIN.read_bytes()", src, "★ 没有从本机二进制现取 client")


class TheSecretRegexIsFixedLength(unittest.TestCase):
    """★★ agy 二进制里两个 secret **首尾相连、无分隔符**存放。

    贪婪的 `{20,40}` 会把它俩粘成一个 47 字符的串，拿去刷新得到 `invalid_client` ——
    而那个报错与「凭证坏了」长得一模一样，会让人去查凭证而不是查正则。
    """

    SRC = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")

    def test_the_pattern_is_exactly_28(self):
        m = re.search(r'_SEC_RE = re\.compile\(rb"GOCSPX-\[A-Za-z0-9_\\-\]\{(\d+)(,(\d+))?\}"\)', self.SRC)
        self.assertIsNotNone(m, "★ secret 正则的形状变了 —— 判据看不懂了，先修闸")
        self.assertIsNone(m.group(2), "★★ 用了区间量词 ⇒ 会把相连的两个 secret 粘起来")
        self.assertEqual(m.group(1), "28")

    def test_it_splits_two_adjacent_secrets(self):
        """★ 正面验一次：两个真形状的 secret 拼在一起，必须切成 2 个。"""
        pool = _load_pool(tempfile.mkdtemp(), Path(tempfile.mkdtemp()) / "t.json")
        blob = b"xx" + b"GOCSPX-" + b"A" * 28 + b"GOCSPX-" + b"B" * 28 + b"yy"
        self.assertEqual(len(pool._SEC_RE.findall(blob)), 2)


class ClientPairsAreProbedNotGuessed(unittest.TestCase):
    """★★ 能用的 (client_id, secret) 是**交叉**配对的：按出现顺序配 → `invalid_client`。

    「位置相邻 / 顺序相同」是个看起来很合理的假设，它在这里是错的 ——
    所以返回**所有组合**让调用方逐对试，成功的那一对才缓存。
    """

    SRC = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")

    def test_all_combinations_are_offered(self):
        i = self.SRC.index("def oauth_candidates(")
        seg = self.SRC[i:self.SRC.index("\ndef ", i + 10)]
        self.assertIn("for i in ids:", seg)
        self.assertIn("for s in secs:", seg, "★★ 没有做笛卡儿积 ⇒ 退回「按顺序配」")

    def test_only_invalid_client_is_worth_retrying(self):
        """★ 凭证本身失效（`invalid_grant`）换几对 client 都一样 ——
        继续试只是把同一个错误问四遍，还让用户等四倍的时间。"""
        i = self.SRC.index("def refresh(")
        seg = self.SRC[i:self.SRC.index("\ndef ", i + 10)]
        self.assertIn('!= "invalid_client"', seg, "★ 任何错误都重试整轮 client")

    def test_the_winner_is_cached_against_the_binary_signature(self):
        seg = self.SRC[self.SRC.index("def remember_client("):]
        self.assertIn("_bin_sig()", seg[:300], "★ 缓存没绑二进制签名 ⇒ agy 自动更新后不会重试")
        self.assertIn("st_mtime_ns", self.SRC, "★ 用了秒级 mtime —— 本仓在这上面栽过")


class RefreshDoesNotInvalidateAgysOwnToken(unittest.TestCase):
    """★★★ Google 默认**不轮换** `refresh_token`（实测响应里没有该字段）。

    所以只有响应真带了新的才覆盖；无脑覆盖会把 agy 手里那份写成空/错的，
    而症状要等到用户下次开 agy 才出现。
    ⚠️ 本仓对 grok 的铁律正好相反（单次有效，绝不刷）—— 两家行为是反的。
    """

    SRC = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")

    def test_the_old_refresh_token_survives_a_response_without_one(self):
        i = self.SRC.index("def refresh(")
        seg = self.SRC[i:self.SRC.index("\ndef ", i + 10)]
        self.assertIn('if j.get("refresh_token"):', seg,
                      "★★★ 无条件覆盖 refresh_token ⇒ 响应没带时会写成 None")


class FailureNeverRendersAsZero(unittest.TestCase):
    """★★★ `0` 是「额度用光了」的合法值。失败路径一旦悄悄写出 0，
    UI 会画一条正常的红条，而用户**没有第二个办法**分辨。同 grok/agy 额度的降级契约。"""

    CLI = (ROOT / "agy-rotate").read_text(encoding="utf-8")
    SRC = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")

    def test_quota_is_none_on_error(self):
        self.assertIn('a["quota"] = q if not err else None', self.CLI,
                      "★★★ 失败时写了数字 —— 与真的 0% 分不开")

    def test_fetch_quota_returns_none_not_empty_on_http_error(self):
        i = self.SRC.index("def fetch_quota(")
        seg = self.SRC[i:i + 1200]
        self.assertIn("return None, \"额度 HTTP", seg)

    def test_an_unknown_account_sorts_last_not_first(self):
        """★★ 取不到额度的号 `_score` 必须是**负数**。返回 0 会让它排在"用光的号"里，
        返回 1 会让它冒充满额被选中 —— 后者更糟：我们会把请求送给一个不知道状态的号。"""
        i = self.CLI.index("def _score(")
        seg = self.CLI[i:self.CLI.index("\ndef ", i + 10)]
        self.assertIn("-1.0", seg, "★★ 未知额度没有排到最后")


class SwitchingProtectsTheOnlyLoginTheUserHas(unittest.TestCase):
    """★★★ `antigravity-oauth-token` 是用户唯一的 agy 登录凭证。
    写坏的代价是他要重新走一遍浏览器 OAuth —— 那不是我们能替他做的。"""

    SRC = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")

    def test_install_backs_up_then_replaces_atomically(self):
        i = self.SRC.index("def _write_live_file(")
        seg = self.SRC[i:self.SRC.index("\ndef ", i + 10)]
        self.assertIn("codexbar-bak", seg, "★★★ 换号前没有备份")
        self.assertIn("os.replace(tmp, LIVE)", seg,
                      "★★★ 不是原子替换 ⇒ 并发读者可能读到半截 JSON")

    def test_it_really_swaps_the_live_file(self):
        d = Path(tempfile.mkdtemp())
        live = d / "tok.json"
        live.write_text(json.dumps(_cred("old", "old@x.y")), encoding="utf-8")
        pool = _load_pool(d, live)
        pool.install_live(_cred("new", "new@x.y"))
        self.assertEqual(pool.claims(pool.read_live())["sub"], "new")
        self.assertEqual(json.loads(Path(str(live) + ".codexbar-bak").read_text())["id_token"],
                         _cred("old", "old@x.y")["id_token"], "★ 备份里不是换之前那份")

    def test_removing_the_live_account_is_refused(self):
        """★ 移除当前登录的号会让用户**既不在池里、也没有别的登录态可回**。"""
        cli = (ROOT / "agy-rotate").read_text(encoding="utf-8")
        i = cli.index("def cmd_remove(")
        self.assertIn("正是当前登录的号", cli[i:i + 900])


class LoginSavesTheCurrentAccountBeforeLoggingOut(unittest.TestCase):
    """★★★ agy 的登录态**只有一份**，`/logout` 会就地清掉它。

    所以 `agy-rotate login` 必须在把用户送去 `/logout` **之前**就把当前号存进池 ——
    不存就丢了，他要重新走一遍浏览器 OAuth 才能拿回来。
    这不是"顺手做的"，它是这条命令存在的理由之一。
    """

    CLI = (ROOT / "agy-rotate").read_text(encoding="utf-8")

    def test_the_current_account_is_adopted_before_agy_starts(self):
        """★★★ 行为闸：给一个**什么都不做**的假 agy，跑完 `login` 之后，
        池里必须已经有登录前那个号 —— 那正是"先存再让你 logout"这件事的唯一证据。

        ⚠️ 第一版比的是源码里 `_adopt(` 与 `subprocess.run(` 的**文本次序**，
        而把 `_adopt` 挪进提前 return 的分支之后次序依然满足，闸照样绿
        （变异工具当场拦下）。次序对了不等于**那条路径上**做了。
        """
        import subprocess
        import sys as _s
        d = Path(tempfile.mkdtemp(prefix="agy-login-"))
        live = d / "tok.json"
        live.write_text(json.dumps(_cred("keepme", "keep@x.y")), encoding="utf-8")
        fake = d / "fake-agy"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        r = subprocess.run([_s.executable, str(ROOT / "agy-rotate"), "login"],
                           input="\n", capture_output=True, text=True, timeout=120,
                           env={**os.environ, "AGY_POOL_STORE": str(d),
                                "AGY_TOKEN_FILE": str(live), "AGY_REAL": str(fake)})
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        pool = json.loads((d / ".agy-pool.json").read_text(encoding="utf-8"))
        self.assertIn("keepme", pool["accounts"],
                      "★★★ 起 agy 之前没把当前号收进池 —— 用户 `/logout` 之后它就没了")
        self.assertTrue((d / "auth" / "agy" / "keepme.json").exists(),
                        "★★★ 池里记了名字却没存凭证 —— 那份登录态还是丢的")

    def test_it_waits_for_agy_instead_of_execing(self):
        """★★ 用 `subprocess.run` 不是 `os.execv`：execv 之后本进程就没了，**回不来收编**，
        新登录的号会静默地不进池 —— 而界面上一切正常。"""
        i = self.CLI.index("def cmd_login(")
        seg = self.CLI[i:self.CLI.index("\ndef ", i + 10)]
        # ⚠️ 判据要认**调用形态** `os.execv(`，不能只搜 `execv` —— 上面那行注释正解释着
        #    "为什么不用 execv"，搜词会被自己的说明判红（这一轮里第三次踩到同一个形状）。
        self.assertNotIn("os.execv(", seg)
        self.assertIn("subprocess.run(", seg)

    def test_no_change_is_reported_as_no_change(self):
        """★ 三态里最容易讲错的那个：**没换号** ≠ 失败，也 ≠ 成功加号。
        把它讲成成功，用户会以为池里有两个号了。"""
        i = self.CLI.index("def cmd_login(")
        seg = self.CLI[i:self.CLI.index("\ndef ", i + 10)]
        self.assertIn("if after == before:", seg, "★ 没有区分「登了同一个号」")

    def test_a_failed_login_says_where_the_old_one_went(self):
        i = self.CLI.index("def cmd_login(")
        seg = self.CLI[i:self.CLI.index("\ndef ", i + 10)]
        self.assertIn("池里那份没丢", seg,
                      "★ 登录没完成时没告诉用户旧号还在 —— 他会以为两个都没了")


class AutoSwitchIsFailOpenAndSticky(unittest.TestCase):
    """★★ 轮换是**增益不是前置条件**。做成前置条件就会出现
    「CodexBar 坏了导致 agy 用不了」，而那比没有轮换糟得多。"""

    CLI = (ROOT / "agy-rotate").read_text(encoding="utf-8")
    WRAP = (ROOT / "bin" / "agy").read_text(encoding="utf-8")

    def test_auto_swallows_everything(self):
        i = self.CLI.index("def cmd_auto(")
        seg = self.CLI[i:self.CLI.index("\ndef ", i + 10)]
        self.assertIn("except Exception", seg, "★★ auto 会把异常抛给 wrapper ⇒ 挡住 agy 启动")

    def test_it_does_not_switch_while_the_current_account_is_fine(self):
        """★ 无谓换号会打断 agy 的 prompt 缓存（上游那些项目把这叫 sticky，默认就是它）。

        ⚠️ 第一版只断言 `cmd_auto` 里出现过 `LOW_WATER` 和 `return` —— 把那条早退整个删掉，
        这两个词在函数后半段**还在**，闸照样绿（变异工具当场拦下）。所以改成真跑一遍看结果。
        """
        live, sub = self._pool(cur_remaining=0.9, other_remaining=1.0)
        self._run_auto(live)
        self.assertEqual(_sub_of(live), sub,
                         "★ 当前号还有 90% 就被换掉了 —— 白白打断 prompt 缓存")

    def test_it_does_switch_when_the_current_account_runs_low(self):
        """★ 反向闸。只测"不换"的话，一个**永远不换**的实现也能全绿 ——
        而那正好把整个功能变成摆设。"""
        live, sub = self._pool(cur_remaining=0.05, other_remaining=0.9)
        self._run_auto(live)
        self.assertNotEqual(_sub_of(live), sub, "★★ 当前号只剩 5% 却没换号")

    # ── 夹具 ──────────────────────────────────────────────────────────
    def _pool(self, cur_remaining, other_remaining):
        """造一个两号的池，当前登录的是 `cur`。→ (登录态文件, 当前号的 sub)"""
        d = Path(tempfile.mkdtemp(prefix="agy-auto-"))
        live = d / "tok.json"
        live.write_text(json.dumps(_cred("cur", "cur@x.y")), encoding="utf-8")
        (d / "auth" / "agy").mkdir(parents=True)
        for sub in ("cur", "other"):
            (d / "auth" / "agy" / f"{sub}.json").write_text(
                json.dumps(_cred(sub, f"{sub}@x.y")), encoding="utf-8")
        q = lambda r: {"gemini": {"remaining": r, "reset": "2099-01-01T00:00:00Z", "models": ["m"]}}
        (d / ".agy-pool.json").write_text(json.dumps({"accounts": {
            "cur": {"label": "cur", "quota": q(cur_remaining)},
            "other": {"label": "other", "quota": q(other_remaining)}}}), encoding="utf-8")
        self._store = d
        return live, "cur"

    def _run_auto(self, live):
        import subprocess
        import sys as _s
        r = subprocess.run([_s.executable, str(ROOT / "agy-rotate"), "auto"],
                           env={**os.environ, "AGY_POOL_STORE": str(self._store),
                                "AGY_TOKEN_FILE": str(live)},
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])

    def test_a_pool_of_one_never_switches(self):
        i = self.CLI.index("def cmd_auto(")
        seg = self.CLI[i:self.CLI.index("\ndef ", i + 10)]
        self.assertIn("len(accs) < 2", seg, "★ 只有一个号时还去换 —— 纯浪费")

    def test_selection_happens_before_exec(self):
        """★★★ agy **只在启动时**读凭证。`passthrough()` 走 `os.execv`，
        过了那行就没有本进程了 —— 选号必须在它之前。

        ⚠️ 锚点要取**调用点**不是定义。第一版 `index("passthrough()")` 命中的是
        `def passthrough()` 那一行，于是拿"定义在前"判成了"调用在前"，闸恒红。
        """
        body = self.WRAP[self.WRAP.index("def main("):]
        i = body.index("select_account(argv)")
        j = body.index("passthrough()")
        self.assertLess(i, j, "★★★ 选号排在 execv 之后 ⇒ 永远不会生效")

    def test_the_wrapper_is_fail_open_too(self):
        i = self.WRAP.index("def select_account(")
        seg = self.WRAP[i:self.WRAP.index("\ndef ", i + 10)]
        self.assertIn("if not rot.exists():", seg, "★ 轮换器不在时没有放行")
        self.assertIn("except Exception", seg)

    def test_an_explicit_account_beats_auto(self):
        """★ 用户 2026-09-13 要的「用特定指令跑特定账号」：`--as` / `AGY_ACCOUNT`。"""
        i = self.WRAP.index("def select_account(")
        seg = self.WRAP[i:self.WRAP.index("\ndef ", i + 10)]
        self.assertIn('os.environ.get("AGY_ACCOUNT")', seg)
        self.assertIn('a == "--as"', seg)
        self.assertIn('"switch", want', seg, "★ 指定号走的不是 switch")


class QuotaGroupingKeysOffTheNumbersNotTheNames(unittest.TestCase):
    """★ 服务端**不下发组名**，同一池里的模型 `(remainingFraction, resetTime)` 逐字相同。
    按模型名前缀猜分组，会在下一次改名时静默错位。"""

    SRC = (ROOT / "agy" / "pool.py").read_text(encoding="utf-8")

    def test_groups_are_keyed_by_the_value_pair(self):
        i = self.SRC.index("def fetch_quota(")
        seg = self.SRC[i:]
        self.assertIn('"%s|%s" % (q.get("remainingFraction"), q.get("resetTime"))', seg)

    def test_the_unlimited_bucket_is_dropped(self):
        """★★ 没有 `resetTime` 的那组（`tab_*` 之类）**不是额度池，是不限量**。
        把它算进"剩余最少"的比较里，选号会永远挑不中真正空闲的号。"""
        i = self.SRC.index("def fetch_quota(")
        self.assertIn('q.get("resetTime") is None', self.SRC[i:], "★ 不限量的那组没有剔除")

    def test_the_required_headers_are_present(self):
        """★★ 只带 Bearer → **403**（实测）。这三个头是必需的，不是装饰。"""
        for h in ("User-Agent", "X-Goog-Api-Client", "Client-Metadata"):
            with self.subTest(header=h):
                self.assertIn(h, self.SRC)
        i = self.SRC.index("def fetch_quota(")
        self.assertIn("**ANTIGRAVITY_HEADERS", self.SRC[i:i + 900], "★ 请求没带那三个头")


if __name__ == "__main__":
    unittest.main()


class TheGoogleTabShowsThePoolNotAReadOnlyCard(unittest.TestCase):
    """★★ 用户 2026-09-13：「google 的为什么灰色，只读？我们不是解决了吗？」

    池是在 CLI 层建好的，但界面上**没有任何东西读 `.agy-pool.json`** ——
    卡还是 2026-09-13 之前那张，写着「只读 · 不在轮换池」。
    那两句当时是真的，池建起来之后就成了假话，而卡片本身看不出任何异常。
    """

    APP = (ROOT / "codexbar" / "src" / "App.tsx").read_text(encoding="utf-8")
    CARD = (ROOT / "codexbar" / "src" / "components" / "AgyCard.tsx").read_text(encoding="utf-8")
    RS = (ROOT / "codexbar" / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")

    def test_one_card_per_account(self):
        self.assertIn("agyPool.accounts.map((a)", self.APP,
                      "★★ Google 档还是只画一张卡 —— 池里有几个号就该有几张")

    def test_it_falls_back_to_the_read_only_card_when_there_is_no_pool(self):
        """★ 池空时退回原来那张只读卡 —— 那条路 2026-09-13 之前一直成立，
        而「还没建池」与「池里有号」是两个不同的事实，不能用同一张卡讲。"""
        self.assertIn("agyPool.accounts.length > 0", self.APP)

    def test_the_read_only_badge_is_conditional(self):
        """★★★ 「只读」不能写死。它现在的意思是**还没建池**，不是"agy 不能轮换"。"""
        # ⚠️ 锚点取**渲染形态** `}}>只读</span>`：上面的注释里正解释着这三态，
        #    `index(">只读<")` 命中的是那段说明（本轮第四次踩到同一形状）。
        # 判据是**三支链的结构**，不是"附近有没有出现某个词"：
        #   `{isCurrent ? 当前 : onSwitch ? 切换 : 只读}` —— 三态各有各的意思，
        #   合并任意两支都会回到用户问的那个问题：「不是解决了吗」。
        i = self.CARD.index("{isCurrent ? (")
        j = self.CARD.index("}}>只读</span>")
        self.assertLess(i, j, "★★★ 「只读」不在那条三支链里 —— 它是写死的")
        self.assertIn(") : onSwitch ? (", self.CARD[i:j], "★ 没有「切换」那一支")
        self.assertIn(">当前</span>", self.CARD[i:j], "★ 没有「当前」那一支")

    def test_the_footer_follows_the_pool(self):
        """★ 「不在轮换池」同理 —— 它是事实陈述，跟着池走。"""
        i = self.CARD.index('"Google 订阅 · 不在轮换池"')
        self.assertIn("onSwitch || isCurrent", self.CARD[max(0, i - 400):i],
                      "★ 页脚写死了「不在轮换池」")

    def test_the_weekly_row_is_never_faked(self):
        """★★★ 云端按账号只给 **5h**（实测 0.9566 == 本机 RPC 的 `gemini-5h` 95.66）。

        给别的号补一格「周 100%」会让每张卡都显示满格周额度 ——
        而上游 `remainingFraction` 的缺省值恰好也是 1.0，这条链路上
        「没有」和「满格」只隔一个默认值。少一行是真话，补一行不是。
        """
        hook = (ROOT / "codexbar" / "src" / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8")
        i = hook.index("function toSnapshot(")
        seg = hook[i:hook.index("\n}", i)]
        self.assertNotIn('"weekly"', seg, "★★★ 给非当值号造了一个假的周窗口")
        self.assertIn('window: "5h"', seg)

    def test_the_live_account_keeps_the_local_rpc_snapshot(self):
        """★ 只有本机 RPC 带周窗口，所以当值号优先用它 —— 那是真实存在的额度。"""
        hook = (ROOT / "codexbar" / "src" / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8")
        self.assertIn("a.sub === liveSub && liveSnap?.available ? liveSnap", hook)

    def test_failure_still_never_becomes_full(self):
        """★★★ 取额度失败时 `quota` 必须是 `null`。返回空对象会让卡片画出一条
        正常的条，而 agy 这条链路上"满格"正是上游的缺省值。"""
        hook = (ROOT / "codexbar" / "src" / "hooks" / "useAgyPool.ts").read_text(encoding="utf-8")
        self.assertIn("quota: ok ? ({ groups } as unknown as AgyQuota) : null", hook)

    def test_the_gui_cannot_run_the_dangerous_subcommands(self):
        """★★★ `agy-rotate` 里有 `login`（起一个交互式 agy，GUI 里必然挂死）
        和 `remove`（不可逆）。界面能点的只有幂等的读/切。"""
        i = self.RS.index("async fn run_agy_rotate(")
        seg = self.RS[i:i + 700]
        self.assertIn('ALLOWED: &[&str] = &["quota", "switch"]', seg,
                      "★★★ 白名单不对 —— GUI 能跑 login/remove")

    def test_the_scripts_are_bundled(self):
        """★★★ 部署出去的 app 里必须有 `agy-rotate` 和它的模块，
        否则界面上的按钮在**装机版**上全是「找不到脚本」，而开发机上一切正常。"""
        import json as _j
        conf = _j.loads((ROOT / "codexbar" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        res = conf["bundle"]["resources"]
        for k in ("../../agy-rotate", "../../agy/pool.py"):
            with self.subTest(script=k):
                self.assertIn(k, res, f"★★★ {k} 没进打包清单")


class _FakeSecurity:
    """假的 `/usr/bin/security` —— 一个内存字典。

    ★★ **绝不碰真钥匙串。** 钥匙串没有"临时目录"这种东西，用真的去测，
      一条用例就能覆盖掉用户当前的 agy 登录态（代价 = 重走一遍浏览器 OAuth）。
      所以这里连 `AGY_KEYRING_SERVICE` 换个名字都不做 —— 那仍然会在用户的
      login.keychain 里留下条目。
    """

    def __init__(self, blob=None, writable=True):
        self.blob, self.writable, self.calls = blob, writable, []

    def run(self, argv, **kw):
        self.calls.append((list(argv), kw))

        class R:
            pass
        r = R()
        r.stdout = r.stderr = ""
        if argv[1] == "find-generic-password":
            r.returncode = 0 if self.blob is not None else 44
            r.stdout = self.blob or ""
        elif argv[1] == "add-generic-password":
            if self.writable:
                # 密文在 `-w` 后面（stdin 那条路实测会截断到 128 字节，见测试里的说明）
                self.blob = argv[argv.index("-w") + 1]
                r.returncode = 0
            else:
                r.returncode = 45          # 实测里钥匙串写失败就是这个码
        else:
            r.returncode = 1
        return r


def _kr_blob(mod, cred):
    import base64 as _b
    return mod._KR_PREFIX + _b.b64encode(json.dumps(cred).encode()).decode()


class TheRealLiveStoreIsTheKeychainNotTheFile(unittest.TestCase):
    """★★★ 2026-09-13 实测：**agy 1.2.2 的登录态在 macOS 钥匙串里**，
    `antigravity-oauth-token` 只是钥匙串写失败时的兜底。

    agy 自己的日志（`~/.gemini/antigravity-cli/log/`）：

        auth.go:148]  ChainedAuth: authenticated via keyring (effective: keyring)
        composite_token_storage.go:237] Failed to save token to keyring, falling back to file: exit status 45

    **判别实验**：文件里放 A 号、钥匙串里留 B 号，跑 `agy models` ⇒ 日志里是 B。
    也就是说在这之前 `agy-rotate switch` 是**静默空操作** —— 我们写的那份 agy 根本不读，
    而命令照常打印「已切到」。本仓最贵的那一课的又一例：
    **写入侧说成功 ≠ 被作用对象真的变了。**
    """

    def _mod(self, fake, live_cred=None):
        d = Path(tempfile.mkdtemp())
        live = d / "tok.json"
        if live_cred is not None:
            live.write_text(json.dumps(live_cred), encoding="utf-8")
        os.environ["AGY_KEYRING"] = "1"
        self.addCleanup(os.environ.__setitem__, "AGY_KEYRING", "0")
        m = _load_pool(d, live)
        m.subprocess = fake
        return m, live

    def test_read_prefers_the_keychain_over_the_file(self):
        """★★★ 核心不变量。两边不一致时读文件 ⇒ 报出一个 **agy 并不在用**的账号，
        而那看起来完全正常（有邮箱、有额度、有徽章）。"""
        fake = _FakeSecurity()
        m, _ = self._mod(fake, _cred("file-acct", "file@x.y"))
        fake.blob = _kr_blob(m, _cred("kc-acct", "kc@x.y"))
        self.assertEqual(m.claims(m.read_live())["sub"], "kc-acct",
                         "★★★ 读的是文件 —— 那不是 agy 在用的那个号")

    def test_the_file_is_still_the_fallback_when_the_keychain_is_empty(self):
        """★ 反方向：钥匙串空时必须回落到文件。只认钥匙串会让
        「钥匙串写失败过」的机器整个读不到登录态。"""
        m, _ = self._mod(_FakeSecurity(blob=None), _cred("file-acct", "file@x.y"))
        self.assertEqual(m.claims(m.read_live())["sub"], "file-acct")

    def test_install_writes_the_keychain_and_says_so(self):
        fake = _FakeSecurity()
        m, _ = self._mod(fake)
        self.assertEqual(m.install_live(_cred("new", "new@x.y")), "keyring")
        self.assertEqual(m.claims(m.read_live())["sub"], "new",
                         "★★★ 写完之后读回来不是那个号 —— 换号没生效")

    def test_a_failed_keychain_write_is_reported_not_swallowed(self):
        """★★★ 只写成兜底文件 = agy 极可能仍在用原来那个号。
        返回 `"file"` 是给调用方说实话用的；退化成 bool/None 就等于把它藏起来。"""
        m, live = self._mod(_FakeSecurity(writable=False))
        self.assertEqual(m.install_live(_cred("new", "new@x.y")), "file")
        self.assertTrue(live.exists(), "★ 钥匙串写不进去时连兜底文件都没写")

    def test_a_successful_keychain_write_does_not_manufacture_a_file(self):
        """★★ 钥匙串写成功时**不要凭空建那个文件**。agy 只在写失败时建它 ——
        我们造一份出来，等于给下一个人留下"它是主存储"的假象（正是这次踩的坑）。"""
        m, live = self._mod(_FakeSecurity())
        m.install_live(_cred("new", "new@x.y"))
        self.assertFalse(live.exists(), "★★ 凭空造了一个兜底文件")

    def test_an_existing_fallback_file_is_kept_in_sync(self):
        """★ 但文件**已经存在**时要跟着更新：留一份指向别的号的陈旧兜底，
        哪天钥匙串条目没了就会把那个号悄悄装回去。"""
        m, live = self._mod(_FakeSecurity(), _cred("old", "old@x.y"))
        m.install_live(_cred("new", "new@x.y"))
        self.assertEqual(json.loads(live.read_text())["id_token"],
                         _cred("new", "new@x.y")["id_token"])

    def test_the_write_is_read_back_and_compared(self):
        """★★★ 2026-09-13 实测：`security -w` 从 **stdin** 读时静默截断到 **128 字节**
        （`readpassphrase` 的缓冲区），而我们的凭证约 2.2 KB。

        当时全部症状都是"成功"：退出码 0、读回来还带着正确的 `go-keyring-base64:` 前缀 ——
        只有 agy 自己说 `You are not logged into Antigravity`。那一版**当场把用户的
        登录态截没了**（靠池里的备份复原）。

        所以判据不是"调用成功"，是**写完再读回来逐字比**。
        ⚠️ 这一条同时说明：密文只能走 argv（另一条路会截断），代价是它在这次调用期间
        对 `ps` 可见 —— agy 自己用的 go-keyring 也是 argv，我们没有扩大暴露面。
        """
        fake = _FakeSecurity()
        m, _ = self._mod(fake)
        m.install_live(_cred("new", "new@x.y"))
        kinds = [c[0][1] for c in fake.calls]
        self.assertIn("find-generic-password", kinds[kinds.index("add-generic-password"):],
                      "★★★ 写完没有读回来核对 —— 截断型损坏会原样留在那儿")

    def test_a_truncated_write_is_caught(self):
        """★★★ 正面把那次真实事故复现出来：钥匙串只存下前 128 字节。
        **写入侧的一切仍然是成功的**，只有读回来比长度才发现得了。"""
        class _Truncating(_FakeSecurity):
            def run(self, argv, **kw):
                r = _FakeSecurity.run(self, argv, **kw)
                if argv[1] == "add-generic-password" and self.blob:
                    self.blob = self.blob[:128]       # 真实的 readpassphrase 缓冲区
                return r
        m, live = self._mod(_Truncating())
        self.assertEqual(m.install_live(_cred("new", "new@x.y")), "file",
                         "★★★ 截断被当成写入成功 —— agy 会说「你没登录」而我们说「已切到」")

    def test_the_current_account_is_saved_before_being_overwritten(self):
        """★★★ 钥匙串**只有一格**，覆盖就没了。低层自己也要兜一道，
        不能只指望 CLI 层的 `_adopt`。"""
        fake = _FakeSecurity()
        m, _ = self._mod(fake)
        fake.blob = _kr_blob(m, _cred("cur", "cur@x.y"))
        m.install_live(_cred("new", "new@x.y"))
        self.assertIsNotNone(m.read_cred("cur"),
                             "★★★ 被覆盖掉的那个号没有收进池 —— 用户要重走 OAuth")

    def test_disabling_the_keyring_stops_every_call(self):
        """★★★ `AGY_KEYRING=0` 必须**两个方向都断**。测试环境靠它保命 ——
        只断读不断写的话，一条用例照样能覆盖用户真实的登录态。"""
        d = Path(tempfile.mkdtemp())
        os.environ["AGY_KEYRING"] = "0"
        m = _load_pool(d, d / "tok.json")
        fake = _FakeSecurity()
        m.subprocess = fake
        self.assertIsNone(m.keyring_read())
        self.assertFalse(m.keyring_write(_cred("x")))
        self.assertEqual(fake.calls, [], "★★★ 关了还在调 security")

    def test_switch_tells_the_user_when_it_only_hit_the_fallback(self):
        """★★ 命令层不许把落点吞掉：只写了文件时打印「已切到」而不说明，
        就是这次缺陷的原样复活。"""
        cli = (ROOT / "agy-rotate").read_text(encoding="utf-8")
        i = cli.index("def cmd_switch(")
        seg = cli[i:cli.index("\ndef ", i + 10)]
        seg = "\n".join(l for l in seg.splitlines() if not l.lstrip().startswith("#"))
        self.assertIn('where = P.install_live(', seg, "★ 落点被丢掉了")
        self.assertIn('where != "keyring"', seg, "★★ 没有按落点分支")
        self.assertIn("仍在用原来那个号", seg, "★★ 警告文案没说清后果")

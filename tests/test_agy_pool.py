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
        i = self.SRC.index("def install_live(")
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

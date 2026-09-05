"""探针的默认模型必须真的可用(2026-09-06)。

## 事故:探针整体失效,而且是静默的

默认模型写死 `gpt-5.4`,而它已不再被 ChatGPT 账号支持:

    HTTP 400 {"detail":"The 'gpt-5.4' model is not supported when using Codex with a ChatGPT account."}

于是**每一次探针都 400**、一个请求都没成功 ⇒ 5h 窗口永远锚定不了 ⇒
用户报「我探针了,额度还是没刷新」。

★★ 两层放大:
① `last_probe` 落地之前,探针结果**不留任何痕迹**,所以「到底探成没有」事后无从查证 ——
   我上一轮据此错误地回答了「探针没坏,只是一次推不动整数位」,那是照着代码注释推理、
   **没有真跑一次**。真跑一次就立刻看到 400。
② 报出来的只是一串原始 JSON,看不出是模型的问题,更看不出该怎么办。

## 修法与本闸

把上游的模型名写死在一个「必须长期能用」的工具里 = 预约一次故障,而且它坏得没有声音。
现在默认值**从 `~/.codex/models_cache.json`(codex 自己的权威清单)现挑**,写死的只是兜底。

本闸守三件:
① 默认模型确实在权威清单里(清单存在时);
② 偏好序里**不含已知被下架**的 `gpt-5.4`;
③ 「模型不被支持」的 400 要给出可执行的下一步,不是甩一串 JSON。
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CR = ROOT / "codex-rotate"
CACHE = Path(os.path.expanduser("~/.codex/models_cache.json"))


def load():
    loader = importlib.machinery.SourceFileLoader("cr_model", str(CR))
    spec = importlib.util.spec_from_loader("cr_model", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def cached_models():
    """权威清单里**可选**的模型 slug。清单不存在(CI)时返回 None。

    ⚠️ 第一版这里复制了生产代码的递归遍历(见 `id/slug/model` 任意层都收),
    于是**测试和被测代码带着同一个 bug**,`upgrade.model` 里的推荐模型两边都被当成可用 ——
    8 条断言全绿,而生产代码实际会挑一个这台机器上不存在的模型。
    **守卫测试的期望值必须独立推导,不能抄被测实现。**
    """
    if not CACHE.is_file():
        return None
    try:
        raw = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return None
    return {m["slug"] for m in (raw.get("models") or [])
            if isinstance(m, dict) and isinstance(m.get("slug"), str)
            and m.get("visibility") != "hide"}


def _fn():
    """只把 `_probe_model_default` 单独取出来跑,不 import 整个 CLI ——
    这样才能注入夹具 `CODEX_HOME`。"""
    import ast
    src = CR.read_text(encoding="utf-8")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "_probe_model_default")
    return node


def select_with(cache, home_cache=None):
    """在**隔离**的 CODEX_HOME 下跑选择器。→ 选中的模型。"""
    import ast, tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as d:
        base = Path(d); ch = base / "isolated"; ch.mkdir()
        home = base / "home"; (home / ".codex").mkdir(parents=True)
        (ch / "models_cache.json").write_text(json.dumps(cache))
        (home / ".codex" / "models_cache.json").write_text(
            json.dumps(home_cache if home_cache is not None else cache))
        ns = {"Path": Path, "json": json, "CODEX_HOME": ch}
        exec(compile(ast.Module(body=[_fn()], type_ignores=[]), "cr", "exec"), ns)
        with patch.object(Path, "home", return_value=home):
            return ns["_probe_model_default"]()


def M(slug, **kw):
    return dict(slug=slug, visibility="list", **kw)


class DefaultModelIsReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()
        cls.src = CR.read_text(encoding="utf-8")

    def test_default_is_non_empty(self):
        self.assertTrue(self.m.PROBE_MODEL)
        self.assertIsInstance(self.m.PROBE_MODEL, str)

    def test_default_is_in_the_authoritative_list(self):
        """★★ 事故本体。清单不在(CI)就跳过 —— 不能拿「本机没这个文件」当通过。"""
        models = cached_models()
        if models is None:
            self.skipTest("本机没有 ~/.codex/models_cache.json（CI 环境）")
        self.assertIn(self.m.PROBE_MODEL, models,
                      "默认探针模型不在 codex 的权威清单里 —— 每次探针都会 400，"
                      "而 5h 窗口因此永远锚定不了")

    def test_retired_model_is_not_in_the_preference_order(self):
        """★ `gpt-5.4` 已被上游下架（实测 400）。它不该再出现在偏好序里。"""
        i = self.src.index("def _probe_model_default")
        body = self.src[i:self.src.index("\nPROBE_MODEL", i)]
        m = re.search(r"prefer = \(([^)]*)\)", body)
        self.assertIsNotNone(m, "找不到偏好序 —— 断言可能打空了")
        prefer = re.findall(r'"([^"]+)"', m.group(1))
        self.assertTrue(prefer, "偏好序是空的")
        self.assertNotIn("gpt-5.4", prefer,
                         "已下架的 gpt-5.4 又回到偏好序里了（注意 gpt-5.4-mini 是另一个，仍可用）")

    def test_preference_order_is_cheap_first(self):
        """探针是计费的：只要证明「这个号能干活」就够，没理由用贵的。

        实测同代 luna $0.038/M vs sol $0.840/M，差 22 倍。
        """
        i = self.src.index("def _probe_model_default")
        body = self.src[i:self.src.index("\nPROBE_MODEL", i)]
        prefer = re.findall(r'"([^"]+)"', re.search(r"prefer = \(([^)]*)\)", body).group(1))
        if "gpt-5.6-luna" in prefer and "gpt-5.6-sol" in prefer:
            self.assertLess(prefer.index("gpt-5.6-luna"), prefer.index("gpt-5.6-sol"),
                            "贵的排在便宜的前面了")

    def test_unreadable_cache_falls_back_instead_of_crashing(self):
        """清单读不到 ⇒ 用兜底，**不能让探针起不来**。"""
        i = self.src.index("def _probe_model_default")
        body = self.src[i:self.src.index("\nPROBE_MODEL", i)]
        self.assertIn("except Exception", body,
                      "读清单没有兜底 —— 文件损坏会让整个 CLI 崩在 import 期")


class SelectorBehaviour(unittest.TestCase):
    """★★ **行为**闸(2026-09-06 评审补)。上面那组静态断言抓不到下面任何一条 ——
    它们只看源码字符串,而这三个 bug 都是「代码在,语义错」。"""

    def test_upgrade_recommendation_is_not_a_usable_model(self):
        """★★ 每条模型记录里有 `upgrade` 字段,指向**推荐升级到的另一个模型**。

        第一版的递归遍历见 `model` 键就收,于是清单里只有 `mini`、而 `luna` 只出现在
        `mini.upgrade` 里时,**照样选中 luna** —— 一个这台机器上根本不可用的模型,
        结果就是每次探针 400。而当时 8 条测试全绿,因为测试抄了同一个递归实现。
        """
        got = select_with({"models": [M("gpt-5.4-mini", upgrade={"model": "gpt-5.6-luna"})]})
        self.assertEqual(got, "gpt-5.4-mini",
                         "把 upgrade 推荐当成了可用模型 —— 选中的模型不在清单里")

    def test_codex_home_wins_over_default_home(self):
        """★★ 凭证与 sessions 都用文件顶部解析好的 `CODEX_HOME`,这里也必须用它。

        写死 `Path.home()/.codex` 会在隔离环境/多 home 下读到**另一台号池的清单**。
        """
        got = select_with({"models": [M("gpt-5.6-terra")]},
                          home_cache={"models": [M("gpt-5.5")]})
        self.assertEqual(got, "gpt-5.6-terra", "读的是 ~/.codex 而不是 CODEX_HOME")

    def test_hidden_models_are_not_selected(self):
        """`gpt-reserve` / `codex-auto-review` 是顶层模型记录,但 `visibility: hide` ——
        不是给人聊天用的。选中它们同样 400,症状与本次事故一模一样。"""
        got = select_with({"models": [dict(slug="gpt-reserve", visibility="hide")]})
        self.assertNotEqual(got, "gpt-reserve")

    def test_falls_back_inside_the_catalog_not_outside(self):
        """★ 偏好序一个都不在时,要从**清单内**挑。

        第一版的兜底排除了所有含 `mini` 的名字,于是「清单只剩新一代 mini」时
        反而返回一个清单外的旧默认值 —— 正是本次事故的形状。
        """
        self.assertEqual(select_with({"models": [M("gpt-9-mini")]}), "gpt-9-mini")

    def test_deeply_nested_json_does_not_kill_the_cli(self):
        """★ 递归遍历在 `try` 之外,深层 JSON 会 `RecursionError` 打死整个 CLI。

        改成一层取值之后这个风险自然消失 —— 这条守的是「别改回递归」。
        """
        deep = cur = {}
        for _ in range(2000):
            cur["x"] = {}
            cur = cur["x"]
        self.assertEqual(select_with({"models": [M("gpt-5.6-luna")], "junk": deep}),
                         "gpt-5.6-luna")


class UnsupportedModelSaysWhatToDo(unittest.TestCase):
    """③ 「模型不被支持」必须给可执行的下一步。"""

    @classmethod
    def setUpClass(cls):
        src = CR.read_text(encoding="utf-8")
        i = src.index("def _billed_probe(")
        cls.body = src[i:src.index("\ndef ", i + 10)]

    def test_anchor_found(self):
        self.assertIn("status != 200", self.body)

    def test_branch_exists(self):
        self.assertIn("not supported", self.body,
                      "没有单独处理「模型不被支持」—— 用户只会看到一串原始 JSON")

    def test_message_is_actionable(self):
        """要么告诉他去哪看清单，要么告诉他怎么覆盖。只说「失败了」不算。"""
        i = self.body.index("not supported")
        seg = self.body[i:i + 600]
        self.assertIn("--model", seg, "没给出临时覆盖的办法")
        self.assertIn("models_cache.json", seg, "没告诉用户去哪查可用清单")


if __name__ == "__main__":
    unittest.main()

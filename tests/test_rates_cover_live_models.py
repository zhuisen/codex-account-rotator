"""费率表必须覆盖本机**真的能跑**的模型（用户 2026-09-29：「搜索下 claude、codex、gemini、grok 不同模型的价格，更新去 AI 用量」）。

修前实测（2026-09-29，真快照）：`claude-fable-5-1` / `claude-opus-5-5` / `claude-sonnet-5-5` / `gpt-6-astra` /
`gpt-6-sol` / `gemini-3.8-flash(-high)` / `grok-4.7-build` **全都不在 RATES 里**，全走平台兜底价、费用列标 `*`；
其中 Codex 兜底还是旧的 gpt-5.6-sol 价（$5/$30，官方已降到 $4/$20）—— 静默算错，且不报错。

这份闸把「新模型上线了、表没跟」变成红：以各家 CLI **自己列出来的可用模型**为准（本机没装 / 列不出来就 skip，
skip 不是绿），再加一条不依赖本机的：兜底价必须等于它声称「按 X 档」的那一档。
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATES_TS = (ROOT / "codexbar" / "src" / "rates.ts").read_text(encoding="utf-8")


def _rates():
    """→ {model: (in, cacheRead, out)}，从 TS 源现解析，不抄一份。"""
    out = {}
    for m in re.finditer(r'^\s*"([^"]+)":\s*\{\s*in:\s*([\d.]+),\s*cacheRead:\s*([\d.]+),\s*out:\s*([\d.]+)',
                         RATES_TS, re.M):
        out[m.group(1)] = tuple(float(x) for x in m.groups()[1:])
    return out


def _fallback(key):
    m = re.search(r'^\s*%s:\s*\{\s*in:\s*([\d.]+),\s*cacheRead:\s*([\d.]+),\s*out:\s*([\d.]+)' % key,
                  RATES_TS, re.M)
    return tuple(float(x) for x in m.groups())


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


class EveryListedModelIsPriced(unittest.TestCase):
    def test_the_parser_sees_the_table(self):
        self.assertGreater(len(_rates()), 40, "★★ 没解析出费率表 —— 正则失准，下面几条全是空闸")

    def test_agy_models(self):
        out = _run(["agy", "models"])
        if not out:
            self.skipTest("本机没有可用的 `agy models`")
        ids = [ln.split("\t")[0].strip() for ln in out.splitlines() if ln.strip() and "\t" in ln]
        self.assertTrue(ids, "★★ `agy models` 一条都没解析出来 —— 闸此刻没有判别力")
        missing = [i for i in ids if i not in _rates()]
        self.assertEqual(missing, [], f"★★ agy 能跑、费率表没有: {missing}")

    def test_codex_models(self):
        p = Path.home() / ".codex" / "models_cache.json"
        if not p.exists():
            self.skipTest("本机没有 ~/.codex/models_cache.json")
        slugs = [m.get("slug") for m in json.loads(p.read_text(encoding="utf-8")).get("models", [])]
        # 这两个是 codex 内部用的路由名，不是可计费的公开模型。
        slugs = [s for s in slugs if s and s not in ("gpt-reserve", "codex-auto-review")]
        self.assertTrue(slugs)
        missing = [s for s in slugs if s not in _rates()]
        self.assertEqual(missing, [], f"★★ codex 能跑、费率表没有: {missing}")

    def test_grok_models(self):
        out = _run(["grok", "models"])
        if not out:
            self.skipTest("本机没有可用的 `grok models`")
        ids = re.findall(r"^\s*[-*]\s+(grok-[\w.\-]+)", out, re.M)
        self.assertTrue(ids, "★★ `grok models` 一条都没解析出来 —— 闸此刻没有判别力")
        missing = [i for i in ids if i not in _rates()]
        self.assertEqual(missing, [], f"★★ grok 能跑、费率表没有: {missing}")


class FallbacksMatchTheTierTheyClaim(unittest.TestCase):
    def test_codex_fallback_is_gpt_5_6_sol(self):
        """★ 兜底注释写「按 gpt-5.6-sol 档」——牌价一变，这里必须一起变（修前差了 $5/$30 vs $4/$20）。"""
        self.assertEqual(_fallback("codex"), _rates()["gpt-5.6-sol"])

    def test_agy_fallback_is_the_current_default_flash(self):
        self.assertEqual(_fallback("agy"), _rates()["gemini-3.8-flash-high"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

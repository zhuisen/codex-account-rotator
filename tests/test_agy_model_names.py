"""agy 模型名归一的回归闸。

★ 为什么值得一个测试：归一错了**不报错**，只是悄悄换一档价 ——
  `Claude Opus 4.6 (Thinking)` 归错会掉进 agy 兜底（Gemini Flash），把 Opus 按 Flash 计，
  单价差 6.7 倍，而页面上看起来一切正常。这正是「没有闸的规则迟早被违反」那一类。

夹具是 2026-08-19 从 `agy models` 抓的**两列真值**（左=官方 id，右=显示名）。
不在测试里实调 `agy models`：它要联网、实测会超时（exit 124），且测试不该依赖外部服务。
新增/改名模型时重跑一次 `agy models` 更新这张表。
"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "traffic"))
import scan  # noqa: E402

# (官方 id, 显示名) —— omc 传的是右边那个，agy 日志里打的也是右边那个
AGY_MODELS = [
    ("gemini-3.7-flash-high",    "Gemini 3.7 Flash (High)"),
    ("gemini-3.7-flash-medium",  "Gemini 3.7 Flash (Medium)"),
    ("gemini-3.7-flash-low",     "Gemini 3.7 Flash (Low)"),
    ("gemini-3.6-flash-high",    "Gemini 3.6 Flash (High)"),
    ("gemini-3.6-flash-medium",  "Gemini 3.6 Flash (Medium)"),
    ("gemini-3.6-flash-low",     "Gemini 3.6 Flash (Low)"),
    ("gemini-3.5-flash-high",    "Gemini 3.5 Flash (High)"),
    ("gemini-3.5-flash-medium",  "Gemini 3.5 Flash (Medium)"),
    ("gemini-3.5-flash-low",     "Gemini 3.5 Flash (Low)"),
    ("gemini-3.1-pro-high",      "Gemini 3.1 Pro (High)"),
    ("gemini-3.1-pro-low",       "Gemini 3.1 Pro (Low)"),
    ("claude-sonnet-4-6",        "Claude Sonnet 4.6 (Thinking)"),
    ("claude-opus-4-6-thinking", "Claude Opus 4.6 (Thinking)"),
    ("gpt-oss-120b-medium",      "GPT-OSS 120B (Medium)"),
]


class TestAgyModelNames(unittest.TestCase):
    def test_display_name_round_trips_to_official_id(self):
        for mid, disp in AGY_MODELS:
            with self.subTest(display=disp):
                self.assertEqual(scan._agy_model(disp), mid)

    def test_official_id_passes_through_unchanged(self):
        """已经是 id 形态的原样返回 —— 调用方显式传 `--model <id>` 时走这条。"""
        for mid, _ in AGY_MODELS:
            with self.subTest(model_id=mid):
                self.assertEqual(scan._agy_model(mid), mid)

    def test_missing_model_is_unknown_not_crash(self):
        """★ 取不到模型名要归 `unknown`，**不能崩、也不能伪装成某个具体模型**。"""
        for bad in (None, "", "   ", 123, [], {}):
            with self.subTest(value=bad):
                self.assertEqual(scan._agy_model(bad), "unknown")


if __name__ == "__main__":
    unittest.main()

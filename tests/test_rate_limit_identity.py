"""额度对象的**身份**判据：只有账号级额度能写进 `slot["quota"]`。

## 这个 bug 是什么

新版 Codex 在**同一个会话记录里**同时写多套额度，按 `limit_id` 区分：

| `limit_id` | `limit_name` | 本机 400 个 rollout 实测 |
|---|---|---|
| `codex` | 无 | ×27160，真实值（7/8/9% 已用），只有 1% 是 0% |
| `codex_bengalfox` | `GPT-5.3-Codex-Spark` | ×9635，**100% 都是 0%/0%** |
| `premium` | 无 | `primary` 是 `null`，本来就被跳过 |

`_find_rl` 的判据只有一句「`primary` 是个带 `used_percent` 的 dict」，**递归找到第一个就返回**，
从不看 `limit_id`。于是一套模型专属额度（恒 0% 已用）会被当成账号额度写进 `state.json`，
UI 显示 **100% 剩余**；等 `refresh-all` 从官方 usage API 读回来，数字又恢复正常。

★ **触发时机是「最新会话记录」被换掉**（新建 / 恢复 / 暂停 / 归档任务都会换），
  `_live_quota` 于是读到另一个会话的尾部 —— 所以它表现为**数字毫无征兆地跳**，
  而不是随用量渐变。用户看到的就是「一会 100%，一会 87%」。

## 为什么必须按 ID 判，不能按窗口形状判

实测 `codex_bengalfox` **有 2752 次带的是 `10080` 分钟的周窗口形状**，与账号额度完全同形。
「Spark 是 5h、账号是周」这个直觉是错的，靠窗口时长永远分不出来。

## 为什么分不出来时要返回 None 而不是猜一个

`_live_quota` 拿到 None 只是跳过这一行；全都没有时 `cmd_quota --save` 会**保留上一份快照**
（那里已有 `elif slot.get("quota"): pass  # keep the last snapshot`）。
所以「读不到」是安全的，而「读到了错的那套」会直接把一个假数字画到用户脸上 ——
这正是本仓库的头号铁律：**「读不到」和「确实是这个值」绝不能返回同一个东西。**
"""
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 取自本机真实 rollout（rollout-2026-08-25T23-56-35 等），不是编的
SPARK = {
    "limit_id": "codex_bengalfox", "limit_name": "GPT-5.3-Codex-Spark",
    "primary": {"used_percent": 0.0, "window_minutes": 300, "resets_at": 1787691403},
    "secondary": {"used_percent": 0.0, "window_minutes": 10080, "resets_at": 1788278203},
    "plan_type": "pro",
}
# ★ 同一套 Spark 额度也会以**周窗口**形状出现（实测 2752 次）——所以按窗口时长分辨是无效的
SPARK_WEEKLY = {
    "limit_id": "codex_bengalfox", "limit_name": "GPT-5.3-Codex-Spark",
    "primary": {"used_percent": 0.0, "window_minutes": 10080, "resets_at": 1788278203},
    "secondary": {"used_percent": None, "window_minutes": None, "resets_at": None},
}
ACCOUNT = {
    "limit_id": "codex", "limit_name": None,
    "primary": {"used_percent": 13.0, "window_minutes": 10080, "resets_at": 1788453083},
    "secondary": {"used_percent": None, "window_minutes": None, "resets_at": None},
    "plan_type": "pro",
}
# 限额 ID 出现之前的老协议：整条记录里只有一套额度，没有 limit_id
LEGACY = {
    "primary": {"used_percent": 42.0, "window_minutes": 300, "resets_at": 1788278203},
    "secondary": {"used_percent": 8.0, "window_minutes": 10080, "resets_at": 1788453083},
}


def load_cli():
    """`codex-rotate` 没有 .py 后缀，按路径加载。顶层只有常量（Path/字符串），无 I/O、无网络。"""
    loader = importlib.machinery.SourceFileLoader("codex_rotate_cli", str(ROOT / "codex-rotate"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class RateLimitIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_cli()

    def test_anchor_exists(self):
        """★ 先证明被测目标还在 —— 改名后下面全部会静默打空。"""
        self.assertTrue(hasattr(self.cli, "_find_rl"), "_find_rl 不见了 —— 断言可能打空了")

    def test_model_specific_limit_is_never_taken_as_the_account_quota(self):
        """★★ 复现原 bug：一条只带 Spark 额度的事件，绝不能被当成账号额度。

        取到它 ⇒ `slot["quota"]` 变成 0%/0% ⇒ UI 画出 100% 剩余（假的）。
        """
        got = self.cli._find_rl({"payload": {"rate_limits": SPARK}})
        self.assertIsNone(got,
                          "把 Spark 的模型专属额度当成了账号额度 —— "
                          "它恒 0% 已用，会被画成 100% 剩余")

    def test_window_shape_cannot_be_used_to_tell_them_apart(self):
        """★ 同一套 Spark 额度也会以周窗口形状出现（实测 2752 次）。

        这条挡的是"改成按 window_minutes 判"这种看起来能用的修法。
        """
        got = self.cli._find_rl({"payload": {"rate_limits": SPARK_WEEKLY}})
        self.assertIsNone(got, "Spark 以周窗口形状出现时被当成了账号额度")

    def test_picks_the_account_limit_when_both_are_present(self):
        """两套同时出现（实测在同一文件里交错 1666:110 次）时，必须挑账号那套。"""
        both = {"payload": {"rate_limits": [SPARK, ACCOUNT]}}
        got = self.cli._find_rl(both)
        self.assertIsNotNone(got, "两套都在时反而什么都没取到")
        self.assertEqual(got.get("limit_id"), "codex")
        self.assertEqual(got["primary"]["used_percent"], 13.0)

    def test_order_does_not_decide(self):
        """★ 反过来放一遍。原实现是"递归找到第一个就返回"，顺序一换结论就变 ——
        而真实数据里两者的先后**没有保证**。"""
        got = self.cli._find_rl({"payload": {"rate_limits": [ACCOUNT, SPARK]}})
        self.assertEqual((got or {}).get("limit_id"), "codex")

    def test_new_protocol_keyed_by_limit_id(self):
        """★ 新协议把额度收进以 limit_id 为键的字典（`rateLimitsByLimitId`，
        受影响机器上报的形状）。递归搜索会撞进这个字典并按**键的顺序**取到 Spark。"""
        for key in ("rateLimitsByLimitId", "rate_limits_by_limit_id"):
            with self.subTest(key=key):
                got = self.cli._find_rl({"payload": {key: {
                    "codex_bengalfox": SPARK, "codex": ACCOUNT}}})
                self.assertEqual((got or {}).get("limit_id"), "codex",
                                 "{} 形状下没挑到账号额度".format(key))

    def test_legacy_shape_without_limit_id_still_works(self):
        """限额 ID 出现之前的记录：整条只有一套额度、没有 limit_id —— 必须照旧接受，
        否则老会话的额度会全部读不到。"""
        got = self.cli._find_rl({"payload": {"rate_limits": LEGACY}})
        self.assertIsNotNone(got, "老协议（无 limit_id）被误挡了")
        self.assertEqual(got["primary"]["used_percent"], 42.0)

    def test_unknown_limit_ids_only_yields_nothing_rather_than_a_guess(self):
        """★★ 只有不认识的限额时 **返回 None，不许猜**。

        下游 `cmd_quota --save` 拿到 None 会保留上一份快照；而猜一个会把假数字画到脸上。
        将来 Codex 再加一套模型额度（这正是本次的成因），这条让它默认**安全**而不是默认**中毒**。
        """
        future = dict(SPARK, limit_id="codex_some_future_model", limit_name="GPT-9")
        self.assertIsNone(self.cli._find_rl({"payload": {"rate_limits": future}}),
                          "遇到没见过的 limit_id 时猜了一个 —— 新模型上线就会重演这个 bug")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""变异验证工具 —— **把我反复犯的六个过程错误变成做不到的事**。

## 为什么需要一个工具而不是一条规则

2026-09-10 一天之内，同一族错误犯了 6 次，全部是"手写变异脚本时漏了一步"：

| 漏掉的那一步 | 症状 |
|---|---|
| 没先证明基线是绿的 | 测试本来就红 ⇒ **任何**变异都"变红"，整轮绿灯全是假的 |
| 没证明选择器命中了用例 | `-k world_readable` 对 `WorldReadable` **大小写不匹配**，选中 0 条却报 "deselected" |
| 没证明文件真的被改了 | 锚点串对不上 ⇒ `replace` 静默无操作 ⇒ 报成「守卫是假的」 |
| 变异打在了同名的另一处 | `replace(anchor, mutant, 1)` 命中**第一处**，而被测的是第二处 |
| 只打了一个方向 | 「改成错的」红了，「整个删掉」照样绿 —— 而后者才是真实的退化方式 |
| 还原后没复跑 | 变异残留在工作区，后面所有结论都建立在被改过的代码上 |

这些都不是判断失误，是**流程漏项**。流程漏项要用工具挡，不是靠下次记得。

## 用法

    from mutate import Mutator
    m = Mutator("tests/test_x.py")               # 被测的测试文件
    m.baseline("MyClass")                        # 先证基线绿且选择器命中 > 0
    m.mutate("src/a.ts", old, new, "MyClass",    # 期望红
             expect="red", why="退回旧实现")
    m.mutate("src/a.ts", old2, "", "MyClass",    # 期望绿（良性改动不该假红）
             expect="green", why="良性换序")
    m.done()                                     # 还原 + 复跑 + 打总结

每一步任何一项校验不过就 `SystemExit(1)` —— **不许继续跑出一份看着完整的报告**。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class MutationError(SystemExit):
    def __init__(self, msg):
        super().__init__(f"\n⛔ 变异验证中止：{msg}\n")


def _run(test_file, k):
    """跑 pytest，返回 (passed, failed, selected)。**selected 是关键** ——
    选中 0 条时 pytest 退出码是 0，看起来和「全绿」一模一样。"""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "-q"] + (["-k", k] if k else []),
        capture_output=True, text=True, cwd=str(ROOT), timeout=900)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    passed = int((re.search(r"(\d+) passed", tail) or [0, 0])[1] or 0)
    failed = int((re.search(r"(\d+) failed", tail) or [0, 0])[1] or 0)
    return passed, failed, passed + failed, tail


class Mutator:
    def __init__(self, test_file):
        self.test_file = test_file
        self.backups = {}
        self.results = []

    def _backup(self, path):
        p = ROOT / path
        if path not in self.backups:
            self.backups[path] = p.read_text(encoding="utf-8")
        return p

    def baseline(self, k=None):
        """★ 第一步永远是这个。基线红 ⇒ 后面每个"红"都是假的。"""
        passed, failed, sel, tail = _run(self.test_file, k)
        if sel == 0:
            raise MutationError(
                f"选择器 `-k {k}` **一条用例都没选中**（{tail}）。\n"
                f"   pytest 对此退出码是 0 —— 和全绿长得一模一样。\n"
                f"   最常见的原因是大小写：`-k world_readable` 匹配不到 `WorldReadable`。")
        if failed:
            raise MutationError(
                f"基线就是红的（{tail}）。此时**任何**变异都会「变红」，绿灯全是假的。\n"
                f"   先把基线修绿再来。")
        print(f"  ✓ 基线：{sel} 条选中，全绿")
        return self

    def mutate(self, path, old, new, k=None, expect="red", why=""):
        """打一个变异并断言结果。

        `expect="red"`  —— 退回旧实现/删掉被测行为，闸**必须**红；
        `expect="green"` —— 良性改动（换序、改无关注释），闸**不许**红（防假红）。
        """
        p = self._backup(path)
        src = self.backups[path]
        n = src.count(old)
        if n == 0:
            raise MutationError(
                f"锚点在 {path} 里**一次都没出现** —— `replace` 会静默无操作，\n"
                f"   于是这一轮什么也没变异，而结果会被读成「守卫是假的」。\n"
                f"   锚点：{old[:80]!r}")
        if n > 1:
            raise MutationError(
                f"锚点在 {path} 里出现了 **{n} 次** —— `replace(...,1)` 只会改第一处，\n"
                f"   而被测的可能是第二处（本仓实测踩过）。请把锚点缩到唯一。\n"
                f"   锚点：{old[:80]!r}")
        mutated = src.replace(old, new)
        if mutated == src:
            raise MutationError(f"替换后文件内容**没有变化** —— 变异等于没打（{path}）")
        p.write_text(mutated, encoding="utf-8")
        try:
            passed, failed, sel, tail = _run(self.test_file, k)
            if sel == 0:
                raise MutationError(f"变异后选中 0 条（{tail}）—— 选择器坏了")
            ok = (failed > 0) if expect == "red" else (failed == 0)
            mark = "✓" if ok else "✗"
            print(f"  {mark} [{expect:5s}] {why or old[:40]} → {tail}")
            self.results.append((ok, why, expect, tail))
            if not ok:
                hint = ("闸是**空的**：把被测行为改坏了它却不红。"
                        if expect == "red" else
                        "闸**假红**：一个良性改动把它弄红了，它守的不是它声称守的东西。")
                raise MutationError(f"{hint}\n   变异：{why}\n   结果：{tail}")
        finally:
            p.write_text(src, encoding="utf-8")
        return self

    def done(self, k=None):
        """还原后**必须复跑** —— 否则残留的变异会污染后面所有结论。"""
        for path, src in self.backups.items():
            (ROOT / path).write_text(src, encoding="utf-8")
        passed, failed, sel, tail = _run(self.test_file, k)
        if failed:
            raise MutationError(f"还原后仍然是红的（{tail}）—— 工作区没恢复干净")
        print(f"  ✓ 已还原并复跑：{tail}")
        print(f"\n共 {len(self.results)} 个变异，全部符合预期。")
        return self


if __name__ == "__main__":
    print(__doc__)

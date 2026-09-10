"""全套件的「假数据落进真实文件」哨兵。

## 来历（2026-09-09，一次真实事故）

`tests/test_pause_semantics.py` 只覆盖了 `CODEX_ROTATE_STORE`，而 `codex-rotate` 里
`LIVE = CODEX_HOME / "auth.json"` 走的是**另一个**变量。于是测试把假凭证
`{"tokens":{"access_token":"TESTONLY-a2",...}}` 写进了真实的 `~/.codex/auth.json`。

后果是连锁的，且**没有一步会报错**：
  1. launchd 的 **autosync 监视器**把它当成"用户刚登录了一个新账号"，自动加进真实账号池，
     建出幻影槽位 `a2` / 标签 `plus8`，并把它设成 `active`；
  2. 真实 `state.json` 于是多了一个不存在的号，`auth/a2.json` 是 79 字节的假凭证；
  3. 排障时若照着（已被污染的）`state.json` 的 `active` 去"恢复"，会把假凭证再抄回
     `~/.codex/auth.json` —— **越修越坏**（我真的这么干了一次）。

## ★★ 判据换过一版，记下为什么

第一版是「快照 mtime/哈希，变了就红」。**它是错的**：`auth/` 被常驻进程持续改写
（proxy 刷 token、quotad 每 300s 写 state.json），实测 20 秒内 `auth/` 就变了一次 ——
于是 4 个无辜的测试被判有罪，而**真正的污染当时已经被清理掉、一个都没抓到**。
「文件变了」不是「测试写了假数据」，把两者当同一件事，闸就只会制造噪音。

现在的判据只认**假数据的指纹**，因此对常驻进程完全免疫：
  ① 真实凭证里出现 `TESTONLY` 之类的测试标记；
  ② 真实 `state.json` 的槽位**变多**（正常只有用户登录才会多，测试期间多出来 = 被注入）；
  ③ 槽位的 `file` 不是 UUID 形状（真实槽位一律 `<uuid>.json`，事故里那个是 `a2.json`）；
  ④ 真实 `~/.codex/auth.json` 的 access_token 短得不像 JWT（事故里那份只有 79 字节）。

## 另一件**故意不做**的事

不给全套件强行覆盖 `CODEX_HOME` / `CODEX_ROTATE_STORE`。试过，**会误伤合法的只读测试**
（`test_discover_enabled` 需要真实 `~/.codex` 才能把扫描源根映射回 `codex` 这个 key）。
隔离是**每个测试自己的责任**；这里只负责在它没做到时当场喊出来。
"""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIVE = Path.home() / ".codex" / "auth.json"
STATE = REPO / "state.json"
AUTH_DIR = REPO / "auth"

# 测试里用得到的假凭证标记。新增假数据时**把标记加进来**，别让它悄悄溜过去。
FAKE_MARKERS = ("TESTONLY", "FAKE-TOKEN", "dummy-token")
UUID_FILE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$")
# 真实 access_token 是 JWT，实测 4KB 量级；事故里那份整个文件才 79 字节。
MIN_REAL_TOKEN = 100


def _survey():
    """对真实数据取一份**语义**快照（不是 mtime）。读不到就记 None ——
    ★「读不到」和「内容为空」必须区分，否则文件被删会被当成"没变化"。"""
    out = {"slots": None, "bad_files": [], "fake_in_auth": [], "live_token_len": None}
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        slots = st.get("slots") or {}
        out["slots"] = len(slots)
        out["bad_files"] = sorted(f"{sl.get('label')}→{sl.get('file')}"
                                  for sl in slots.values()
                                  if not UUID_FILE.match(sl.get("file") or ""))
    except (OSError, ValueError):
        pass
    try:
        for p in AUTH_DIR.glob("*.json"):
            txt = p.read_text(encoding="utf-8", errors="replace")
            if any(m in txt for m in FAKE_MARKERS):
                out["fake_in_auth"].append(p.name)
        out["fake_in_auth"].sort()
    except OSError:
        pass
    try:
        tok = (json.loads(LIVE.read_text(encoding="utf-8")).get("tokens") or {}).get("access_token")
        out["live_token_len"] = len(tok or "")
    except (OSError, ValueError):
        pass
    return out


@pytest.fixture(scope="session")
def _baseline():
    return _survey()


@pytest.fixture(autouse=True)
def _real_data_canary(request, _baseline):
    """★ 每个测试都查一遍而不是整轮查一次:整轮只能告诉你"有人动了",
    当场失败能直接指名是哪个测试 —— 事故那次我是靠人工比对 mtime 才找到的。"""
    yield
    now = _survey()
    p = []
    if now["fake_in_auth"]:
        p.append(f"真实 auth/ 里出现了假凭证标记: {now['fake_in_auth']}")
    if now["bad_files"] and now["bad_files"] != _baseline["bad_files"]:
        p.append(f"真实 state.json 多了非 UUID 文件名的槽位: {now['bad_files']}"
                 f"（事故里 autosync 注入的就是 `a2.json`）")
    if (now["slots"] is not None and _baseline["slots"] is not None
            and now["slots"] > _baseline["slots"]):
        p.append(f"真实账号池槽位从 {_baseline['slots']} 涨到 {now['slots']}"
                 f" —— 测试期间只可能是被注入的")
    if now["live_token_len"] is not None and now["live_token_len"] < MIN_REAL_TOKEN:
        p.append(f"真实 ~/.codex/auth.json 的 access_token 只有 "
                 f"{now['live_token_len']} 字符，不像 JWT —— 多半被测试的桩覆盖了")
    if p:
        pytest.fail(
            "★★ 测试污染了真实数据\n   测试:" + request.node.nodeid + "\n   "
            + "\n   ".join(p)
            + "\n   —— 多半是漏设了 CODEX_HOME 或 CODEX_ROTATE_STORE。\n"
              "   注意 `LIVE = CODEX_HOME / \"auth.json\"` 与 `STORE` 是**两个**变量，\n"
              "   只设一个不够(2026-09-09 事故就是这么发生的)。"
        )

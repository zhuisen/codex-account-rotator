"""代理的「一个 provider、两种上游」路由闸（2026-09-09 定稿）。

这一版把中转站从「第二个 codex profile」改成「同一个代理的另一个上游」。收益是
`codex resume` 的会话列表不再分裂（picker 按 `model_provider` 过滤且无配置可绕），
代价是 `proxy.py` —— **全仓最危险的文件**（双计费 / failover / 去重都在里面）——
多了一条分叉。这个文件钉住那条分叉不会污染账号池那一档。

★ 最要紧的三条，每条都对应一个真实事故形状：
  ① **判不准时往免费那档倒。** 路由文件坏了/读不到 ⇒ 走账号池，绝不 fail-open 成
     按量付费的中转站。反过来的失败模式是"用户不知情地在花钱"。
  ② **中转站的 401 绝不触碰账号池凭证。** Fable 在 `env_key` 那版抓到过：中转站回 401
     会让 codex 去刷账号池当值号的 refresh_token 并喊 "log out and sign in again"，
     而 `codex logout` 在本仓是**杀号**操作。
  ③ **`chatgpt-account-id` 绝不发给第三方。** 那是 ChatGPT 订阅端点的私有头，
     原样转发等于把本机账号 id 泄露给一个无关服务。
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_proxy():
    """每次都新导入一份 —— 模块级有 `_relay_cache`，跨用例共用会互相污染。"""
    spec = importlib.util.spec_from_file_location("proxy_under_test", REPO / "proxy" / "proxy.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["proxy_under_test"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def px(tmp_path):
    """把代理的两个中转站文件指到 tmp_path。**绝不碰真实 relay/ 目录** ——
    那里有真 key，而且路由指错一次就是真金白银。"""
    m = _load_proxy()
    d = tmp_path / "relay"
    d.mkdir()
    m.RELAY_ROUTE = d / "route.local.json"
    m.RELAY_STORE = d / "relays.local.json"
    m._relay_cache = {"v": (None, None)}
    return m


def _write(m, route, relays):
    if route is not None:
        m.RELAY_ROUTE.write_text(json.dumps(route), encoding="utf-8")
    if relays is not None:
        m.RELAY_STORE.write_text(json.dumps(relays), encoding="utf-8")
    m._relay_cache = {"v": (None, None)}


REL = {"relays": [{
    "id": "tokendun", "label": "TokenDun", "enabled": True,
    "base_url": "https://api.example.com/v1", "key": "sk-TESTONLY-not-a-real-key",
}]}


class TestRouteResolution:
    def test_pool_profile_means_pool(self, px):
        _write(px, {"profile": "rotateproxy"}, REL)
        assert px._relay_upstream() is None

    def test_relay_id_resolves_to_upstream(self, px):
        _write(px, {"profile": "tokendun"}, REL)
        up = px._relay_upstream()
        assert up is not None
        assert up["host"] == "api.example.com"
        assert up["port"] == 443
        assert up["base"] == "/v1"
        assert up["key"] == "sk-TESTONLY-not-a-real-key"
        assert up["id"] == "tokendun"

    @pytest.mark.parametrize("route,relays,why", [
        ({"profile": "tokendun"}, {"relays": [dict(REL["relays"][0], enabled=False)]},
         "停用的中转站不该被路由到"),
        ({"profile": "tokendun"}, {"relays": []}, "登记表里没有这个 id"),
        ({"profile": "tokendun"}, {"relays": [dict(REL["relays"][0], key="")]},
         "没有 key 就发不出去"),
        ({"profile": "nonexistent"}, REL, "未登记的 id"),
        ({"profile": ""}, REL, "空 id"),
        ({"profile": None}, REL, "null id"),
        ({}, REL, "缺 profile 字段"),
        ([], REL, "路由文件不是对象"),
    ])
    def test_anything_unresolvable_falls_back_to_pool(self, px, route, relays, why):
        """★ 判不准一律回账号池。**方向是刻意的**：账号池是零边际成本那一档，
        判错的最坏结果是"没按预期扣费"；反过来是"用户不知情地在花钱"。"""
        _write(px, route, relays)
        assert px._relay_upstream() is None, why

    def test_corrupt_json_falls_back_to_pool(self, px):
        px.RELAY_ROUTE.write_text("{ not json", encoding="utf-8")
        px.RELAY_STORE.write_text(json.dumps(REL), encoding="utf-8")
        px._relay_cache = {"v": (None, None)}
        assert px._relay_upstream() is None

    def test_missing_files_fall_back_to_pool(self, px):
        assert px._relay_upstream() is None

    def test_plaintext_base_url_is_refused(self, px):
        """★ 绝不把 API key 明文发出去。`http://` 一律拒绝、退回账号池。"""
        _write(px, {"profile": "tokendun"},
               {"relays": [dict(REL["relays"][0], base_url="http://api.example.com/v1")]})
        assert px._relay_upstream() is None

    def test_cache_invalidates_when_relays_file_changes(self, px):
        """★★ 签名必须**两个文件都看**。只看 route.local.json 的话，改了 key/base_url
        却没切路由时，代理会一直用着旧凭证往旧地址发 —— 而用户以为已经改好了。"""
        _write(px, {"profile": "tokendun"}, REL)
        assert px._relay_upstream()["host"] == "api.example.com"
        px.RELAY_STORE.write_text(json.dumps(
            {"relays": [dict(REL["relays"][0], base_url="https://api.other.com/v2")]},
        ), encoding="utf-8")
        # 注意：**不手动清缓存**，就是要证明签名自己会失效。
        up = px._relay_upstream()
        assert up["host"] == "api.other.com" and up["base"] == "/v2"


class TestUpstreamIsolation:
    """中转站档绝不污染账号池的任何机制。"""

    # ★ 账号池的副作用函数。中转站路径调用其中任何一个都是"两套凭证串线"。
    POOL_SIDE_EFFECTS = {"_mark_dead", "_cool", "_pick", "_record_quota", "_slot_token"}

    def test_relay_path_never_calls_pool_machinery(self, px):
        """`_proxy_relay` **不得调用**任何账号池副作用函数。

        ★ 这是形状闸不是行为闸，但它守的正好是最贵的一类错：`_mark_dead` / `_cool` /
          `_slot_token(force=True)` 任何一条被误用，代价都是真号被弄坏或被杀。

        ★★ **判据必须是 AST 里的真实调用，不能是源码文本匹配。** 第一版用
          `name not in src`，结果被这个函数自己的**文档字符串**判红 —— 那些名字正是
          写在"绝不调用它们"这句话里的。文本匹配同时会漏（改成 `globals()["_cool"]`
          仍绿）和误报（注释里提一句就红），两个方向都错。
        """
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(px.Handler._proxy_relay)))
        called = {
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        } | {
            n.func.attr for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        leaked = called & self.POOL_SIDE_EFFECTS
        assert not leaked, f"中转站路径不得触碰账号池机制：{sorted(leaked)}"

    def test_the_ast_gate_can_actually_go_red(self, px):
        """★ 闸自证：把一个账号池副作用塞进等价的函数体，上面那道必须变红。

        本仓记过两次"空守卫"（守卫写了、但永远不可能失败）。一道判不了红的闸
        比没有闸更糟：它让人以为这一类已经被守住了。
        """
        import ast
        import textwrap
        mutant = textwrap.dedent("""
            def _proxy_relay(self, body, up, rid):
                _mark_dead(up["id"], "x")
                return None
        """)
        tree = ast.parse(mutant)
        called = {
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert called & self.POOL_SIDE_EFFECTS, "闸对已知阳性必须报警，否则它是空的"

    def test_relay_401_is_not_forwarded_to_codex(self, px):
        """★ 本仓不变量：401 永不出现在 codex 面前（账号池档也从不转发它）。
        转过去会触发 codex 的重新登录流程 —— 而 `codex logout` 在本仓是杀号操作。"""
        import inspect
        src = inspect.getsource(px.Handler._proxy_relay)
        assert "resp.status == 401" in src, "必须显式处理 401"
        assert "ABORT_STATUS" in src, "401 必须换成不可重试的本地错误码，不能原样转发"

    def test_account_id_header_dropped_for_relay(self, px):
        """★ `chatgpt-account-id` 是 ChatGPT 私有头，绝不发给第三方中转站。"""
        import inspect
        src = inspect.getsource(px.Handler._open)
        assert "if account_id and not up:" in src, \
            "必须在 up 存在时跳过 chatgpt-account-id —— 否则本机账号 id 泄露给中转站"

    def test_finish_skips_quota_and_affinity_without_aid(self, px):
        """★ 中转站不回 ChatGPT 的额度头。硬记会把一个账号的额度写成中转站的响应，
        而额度账本是被 UI 直接消费的。"""
        import inspect
        src = inspect.getsource(px.Handler._finish)
        assert "if aid:" in src and "_record_quota" in src
        assert "if conv and aid:" in src, "粘性也必须跳过"
        assert "if aid and not got:" in src, "affinity 表存 None 会被 _pick 读成一个叫 None 的号"


class TestTheCacheIsRaceSafe:
    """★★ 代理是 `ThreadingHTTPServer`，`_relay_cache` 被并发读写。

    ⚠️ **类名必须 `Test*` 开头。** 本文件是 pytest 风格的**普通类**（不继承
       `unittest.TestCase`），而 pytest 默认只收集 `Test*`。我第一版命名成
       `TheCacheIsRaceSafe` —— 加了两条用例，总数**纹丝不动仍是 20**，
       整个类被静默跳过。这是空守卫的又一种形态：**闸写了，但根本没跑。**
       （本文件里其它类叫 `TestXxx` 就是这个原因；别的测试文件用
       `unittest.TestCase` 子类，pytest 无视命名照收，所以那边可以随便起名。）

    原实现两次独立赋值（`["sig"]=` 然后 `["up"]=`），线程 A 写完第一行、还没写第二行时，
    线程 B 读到的是**新签名配旧上游** —— 钱去了用户没选的地方，且不报错：
    刚切到中转站却发去账号池，或刚切回账号池却还在扣中转站余额。
    """

    def test_the_cache_holds_one_atomic_pair(self, px):
        """判据是**写入点**：签名与上游必须在**一次**赋值里绑成一个值。
        单个 dict 赋值在 GIL 下是原子的；两次就有窗口，线程 B 会读到
        「新签名 + 旧上游」，于是把请求发去用户没选的那一边。

        ★ 第一版断言 `set(px._relay_cache) == {"v"}` —— **是个空守卫**：
          夹具会先把缓存整个换成 `{"v": ...}`，所以改模块级字面量对它不可见
          （变异实测未变红）。属性在**函数的写入点**上，判据也必须打在那里。
        """
        import ast
        import inspect
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(px._relay_upstream)))
        writes = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Assign)
                  for tgt in n.targets
                  if isinstance(tgt, ast.Subscript)
                  and isinstance(tgt.value, ast.Name) and tgt.value.id == "_relay_cache"]
        assert len(writes) == 1, \
            f"`_relay_cache` 被写了 {len(writes)} 次 —— 多于一次就有竞态窗口"
        assert isinstance(writes[0].value, ast.Tuple), \
            "写进去的不是元组 —— 签名与上游必须绑在一起"
        # 行为侧对照:真的跑一次，缓存里确实是一对。
        _write(px, {"profile": "tokendun"}, REL)
        px._relay_upstream()
        sig, up = px._relay_cache["v"]
        assert sig is not None and up is not None

    def test_a_file_change_during_the_read_is_not_cached(self, px):
        """★★ 签名在**读文件之前**取。两者之间文件被改写的话，缓存会固化
        「新签名 + 旧内容」—— 新签名等于最新文件状态，于是**直到下一次再改动为止**
        代理都在用旧上游。修法是读完再取一次签名，不一致就不缓存。

        ★ 桩直接打在判据上（`_route_sig`），不是去改文件：`PosixPath` 的方法不可赋值，
          而且打在判据上更准 —— 它就是这段逻辑要比较的那两个值。
        """
        _write(px, {"profile": "tokendun"}, REL)
        real_sig = px._route_sig
        calls = {"n": 0}

        def racing_sig():
            calls["n"] += 1
            # 第 1 次（读之前）与第 2 次（读之后）不同 = 读的期间文件被改过。
            return ("A",) if calls["n"] == 1 else ("B",)

        px._route_sig = racing_sig
        px._relay_upstream()
        px._route_sig = real_sig
        cached_sig, _ = px._relay_cache["v"]
        assert cached_sig is None, "★ 把「新签名 + 旧内容」缓存下来了 —— 旧上游会一直用下去"

    def test_a_stable_read_does_get_cached(self, px):
        """★ 反向对照。少了这条，一个**从不缓存**的实现也能让上面那条绿 ——
        而那会让每个请求都读两个文件（本仓量过"没人看时零开销"）。"""
        _write(px, {"profile": "tokendun"}, REL)
        px._relay_upstream()
        cached_sig, cached_up = px._relay_cache["v"]
        assert cached_sig is not None and cached_up is not None
        assert cached_up["host"] == "api.example.com"


class TestReservedName:
    def test_pool_profile_constant_matches_cxp(self, px):
        """`rotateproxy` 是账号池档的保留名。它同时是 `~/.codex/rotateproxy.config.toml`
        的文件名与 codex 里的 `model_provider` id —— 三处必须是同一个字符串。"""
        assert px.POOL_PROFILE == "rotateproxy"
        cxp = (REPO / "proxy" / "cxp").read_text(encoding="utf-8")
        assert "rotateproxy" in cxp

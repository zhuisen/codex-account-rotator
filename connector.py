#!/usr/bin/env python3
"""账号池 Connector —— 把「只装了看板那一半」的机器接进轮换。

## 为什么存在

用户 2026-09-19 报「下载了 CodexBar，敲 `codex` 没走 rotateproxy」。查下来不是 bug：
`.dmg` 里只有**用量看板**那一半，轮换那一半（代理 / launchd 服务 / 入口 / provider 配置）
要 clone 仓库手动装。`codex-rotate integration` 已经能**说清楚**没接上（v1.7.0），
这个模块负责**把它接上**。

## 三条硬边界（都是本仓用真金白银换来的）

★★★ **绝不调用 `codex login` / `codex logout`。** 它们会把当时躺在 `~/.codex/auth.json`
     里的号在**服务端** revoke（受控实验三轮确证，本机死过 3 个号）。加号只能由用户自己
     跑 `codex-rotate login`。Connector 只碰**配置**，不碰凭证。

★★★ **绝不 load→dump 重写 `~/.codex/config.toml`。** 那是用户自己的文件，里面有 MCP、
     hooks、模型偏好。只在**托管标记之间**写，标记之外一个字节都不动（与
     `relay/store.py::split_managed` 同一条不变量，那边是被 2026-09-10 的事故逼出来的：
     原来命中标记就 `unlink()` 整份）。

★★ **不需要 sudo。** 全部落在用户级：`~/Library/LaunchAgents`、`~/.local/bin`、`~/.codex`、
    以及 app 自己的数据目录。任何需要管理员权限的做法都不要。

## 运行时装在哪：`<store>/runtime/`，**不是** app bundle 里面

`.dmg` 装机时脚本在 `CodexBar.app/Contents/Resources/scripts/`。**不能**让 launchd 指向那里：

  · `deploy.sh` / 应用更新会**整个替换** bundle —— 常驻服务的入口在替换窗口里消失；
  · 用户把 App 拖进废纸篓，他的 `codex` 跟着废掉，而两件事看起来毫无关系。

所以 `apply` 会把运行时**复制**到 `<store>/runtime/`（store = app 数据目录），
launchd 与 symlink 全部指向那份拷贝。App 没了，轮换照常。

⚠️ **clone 装机（仓库自带 `.git`）不复制**，原地用 —— 那是既有的、文档写明的装法，
   复制反而会让用户改了仓库却不生效。判据是 `src` 与 `store` 是否同一个目录。
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

MARK_BEGIN = "# >>> codexbar-connector managed — 本区由 CodexBar 写入,标记之外的内容原样保留 >>>"
MARK_END = "# <<< codexbar-connector managed <<<"

PROXY_PORT = int(os.environ.get("CRP_PORT", "8011"))

#: 运行时需要哪些文件。★ 少一个的症状是「服务装上了但起不来」，而 launchd 只会安静地反复重启。
RUNTIME_FILES = [
    "codex-rotate", "portalock.py", "resume_provenance.py", "connector.py",
    "proxy/proxy.py", "proxy/cxp", "proxy/cxd", "proxy/auth-token",
    "proxy/codex-profile-scope.sh",
    "daemon/quota_daemon.py",
    "scripts/install-launchd.sh", "scripts/codex-wrapper-with-logout-guard.sh",
    "relay/__init__.py", "relay/store.py", "relay/monitor.py", "relay-ctl",
    "traffic/quota_anchors.py", "traffic/rotation.py",
    # ★ agy 账号池那一套。**漏了它 `~/.local/bin/agy-rotate` 会是个悬空 symlink** ——
    #   点一下报「No such file」，而用户完全看不出与 Connector 有关。
    #   2026-09-19 实测漏过一次，现在有 `EveryEntryTargetIsInTheRuntime` 守着。
    "agy-rotate", "agy/__init__.py", "agy/pool.py",
]

#: `~/.local/bin` 里建哪些入口。★ `codex` **不在这里** —— 它改变裸 `codex` 的行为，
#: 必须是用户单独勾选的一步（见 `STEP_WRAPPER`）。
ENTRIES = {
    "cxp": "proxy/cxp",
    "cxd": "proxy/cxd",
    "codex-rotate": "codex-rotate",
    "agy-rotate": "agy-rotate",
}

STEP_WRAPPER = "wrapper"


# ── 小工具 ────────────────────────────────────────────────────────────────────

def _read(p):
    """读不到返回 `None`，**不是空字符串**（本仓铁律「读不到 ≠ 没有」）。"""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def split_managed(text):
    """切成 (之前, 托管区, 之后)。没有标记时托管区为 `None`。

    ★ 与 `relay/store.py::split_managed` **同形**但标记不同 —— 那边管中转站 profile，
      这边管 `config.toml`。刻意不 import 它：那个模块只在装了 relay 的机器上才有，
      而 Connector 要能在一台**什么都还没装**的机器上跑。
    """
    if text is None or MARK_BEGIN not in text or MARK_END not in text:
        return (text or ""), None, ""
    a = text.index(MARK_BEGIN)
    b = text.index(MARK_END) + len(MARK_END)
    return text[:a], text[a:b], text[b:].lstrip("\n")


def _atomic_write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(str(tmp), str(path))
    finally:
        if tmp.exists():
            tmp.unlink()


def _codex_home():
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def _local_bin():
    return Path(os.environ.get("CODEXBAR_LOCAL_BIN") or (Path.home() / ".local" / "bin"))


def _launch_agents():
    return Path(os.environ.get("CODEXBAR_LAUNCH_AGENTS")
                or (Path.home() / "Library" / "LaunchAgents"))


# ── 要写的内容（plan 与 apply 共用同一份渲染，否则预览与实际会分叉）──────────────

def provider_block(runtime):
    """`~/.codex/config.toml` 里那一段。

    ★ `auth.command` 指向运行时里的 `proxy/auth-token` —— 它是代理用来拿当值号
      access token 的钩子。写绝对路径而不是相对：codex 的 cwd 是用户的项目目录。
    """
    return "\n".join([
        MARK_BEGIN,
        "[model_providers.rotateproxy]",
        'name = "codex-rotate proxy"',
        f'base_url = "http://127.0.0.1:{PROXY_PORT}"',
        'wire_api = "responses"',
        "# ★ 必须为 false:codex 的 responses_websocket 端点硬编码 wss://chatgpt.com/…,",
        "#   **不认 base_url**。开着就完全绕过代理、只烧 auth.json 那一个号,",
        "#   而代理日志里一条记录都没有。",
        "supports_websockets = false",
        "",
        "[model_providers.rotateproxy.auth]",
        f'command = {json.dumps(str(runtime / "proxy" / "auth-token"), ensure_ascii=False)}',
        MARK_END,
        "",
    ])


def profile_block():
    """`~/.codex/rotateproxy.config.toml`（`--profile rotateproxy` 读的那份 overlay）。

    ⚠️ **codex 自己会往这份文件里回写**（hooks 信任哈希、项目信任、NUX 计数器 ——
      本机实测 12 行）。所以这里同样只写托管区，整文件覆盖会毁掉 oh-my-codex 的 hooks。
    """
    return "\n".join([
        MARK_BEGIN,
        'model_provider = "rotateproxy"',
        "supports_websockets = false",
        MARK_END,
        "",
    ])


def _merge_managed(path, block):
    """把 `block` 放进 `path` 的托管区：已有就替换，没有就追加。标记之外原样保留。"""
    before, managed, after = split_managed(_read(path))
    if managed is None:
        base = before.rstrip("\n")
        text = (base + "\n\n" if base else "") + block
    else:
        text = before + block + ("\n" + after if after.strip() else "")
    _atomic_write(path, text.rstrip("\n") + "\n")


# ── plan ─────────────────────────────────────────────────────────────────────

def _runtime_dir(src, store):
    """clone 装机原地用；安装包装机用 `<store>/runtime/`（理由见模块 docstring）。"""
    if Path(src).resolve() == Path(store).resolve():
        return Path(src).resolve()
    return Path(store).resolve() / "runtime"


def _launchctl(args, timeout=20):
    """所有 `launchctl` 调用的**唯一出口**，带隔离口 `CODEXBAR_LAUNCHCTL=0`。

    ★★★ **2026-09-19 真事故 —— 我自己的测试把用户的常驻服务全 bootout 了。**
    `remove()` 里的 `launchctl bootout gui/<uid>/com.doushutangmu.codex-rotate.*` 用的是
    **真实 label**，而 label 不随任何环境变量改变。测试只隔离了 plist 路径
    （`CODEXBAR_LAUNCH_AGENTS`），于是跑一次 `test_connector` 就把真机上的
    proxy / quotad / autosync / dawnprobe 四个服务全停了 —— 轮换当场断掉，
    而测试全绿、没有任何一处会为此变红。

    ★ 修法与 2026-09-06「夹具写进真账本」同一条：**加一个只影响这一件事的隔离口**，
      而不是「记得在每个测试里打桩」（那是"写下来但没有闸"的老路，下一个新测试照样踩）。
      `tests/__init__.py` 与 `tests/test_isolation_bootstrap.py` 两处都设它，
      闸在 `test_isolation_bootstrap`。

    返回 `None` 表示**没执行**（被隔离，或 launchctl 不可用）—— 与「执行了但失败」分开。
    """
    if os.environ.get("CODEXBAR_LAUNCHCTL") == "0":
        return None
    try:
        return subprocess.run(["launchctl", *args], capture_output=True,
                              text=True, timeout=timeout)
    except Exception:
        return None


def _svc_loaded(name):
    """服务在不在。⚠️ 不用 `pgrep -f`（自匹配恒真，本仓记过）——问 launchctl。"""
    r = _launchctl(["list"], timeout=10)
    if r is None:
        return None                       # ★ 三态：查不了/没查 ≠ 没装
    return f"com.doushutangmu.codex-rotate.{name}" in (r.stdout or "")


def plan(src, store):
    src = Path(src).resolve()
    store = Path(store).resolve()
    runtime = _runtime_dir(src, store)
    inplace = runtime == src
    steps = []

    def add(sid, title, why, state, detail, preview="", optional=False):
        steps.append({"id": sid, "title": title, "why": why, "state": state,
                      "detail": detail, "preview": preview, "optional": optional})

    # ★★ **四态，不是三态**：`todo`（没装）/ `done`（我们装的）/ `external`（**你自己装的，
    #    已经在工作，我们不碰**）/ `blocked`（这份安装缺东西，装不了）。
    #    把 `external` 并进 `todo` 会让 Connector 去覆盖用户手工写的配置 —— 而那正是
    #    本仓「绝不 load→dump 重写用户文件」那条不变量要防的事；并进 `done` 又会让
    #    「我们装的」和「碰巧也能用」分不开，撤销时不知道该不该动它。
    #    实测于 2026-09-19：作者机器上 provider/profile/wrapper 全是手工配的，
    #    第一版把它们全报成 `todo`，等于建议用户覆盖自己正在用的配置。

    # ① 运行时
    missing = [f for f in RUNTIME_FILES if not (src / f).exists()]
    if missing:
        add("runtime", "准备运行时", "代理与常驻服务的代码要有个稳定的家",
            "blocked",
            f"这份安装里缺 {len(missing)} 个运行时文件（如 {missing[0]}）——"
            "无法接入。请改用 clone 安装，或升级到包含运行时的版本。")
    elif inplace:
        add("runtime", "准备运行时", "仓库安装，原地使用", "done",
            f"clone 安装，直接用 {src}（不复制 —— 否则你改了仓库却不生效）")
    else:
        have = runtime.exists() and all((runtime / f).exists() for f in RUNTIME_FILES)
        add("runtime", "准备运行时",
            "★ 复制到数据目录，**不指向 App 内部** —— 否则 App 更新/删除会把常驻服务弄断",
            "done" if have else "todo",
            f"{len(RUNTIME_FILES)} 个文件 → {runtime}",
            preview=str(runtime))

    # ② provider 块
    cfg = _codex_home() / "config.toml"
    blk = provider_block(runtime)
    cfg_txt = _read(cfg)
    _, managed, _ = split_managed(cfg_txt)
    if managed is not None:
        pstate, pdetail = "done", f"托管区已在 {cfg}"
    elif cfg_txt and "[model_providers.rotateproxy]" in cfg_txt:
        pstate = "external"
        pdetail = (f"{cfg} 里**已经有**你自己写的 `[model_providers.rotateproxy]`，"
                   "它正在工作 —— Connector 不会碰它。要改请手动编辑。")
    else:
        pstate, pdetail = "todo", f"只写托管标记之间那一段，{cfg} 里你自己的内容一个字节都不动"
    add("provider", "写入 model provider",
        "codex 靠它知道请求要发给本机代理", pstate, pdetail, preview=blk)

    # ③ profile overlay
    prof = _codex_home() / "rotateproxy.config.toml"
    pblk = profile_block()
    prof_txt = _read(prof)
    _, pmanaged, _ = split_managed(prof_txt)
    if pmanaged is not None:
        fstate, fdetail = "done", f"托管区已在 {prof}"
    elif prof_txt and "rotateproxy" in prof_txt:
        fstate = "external"
        fdetail = f"{prof} 已存在且指向 rotateproxy —— 你自己建的，Connector 不碰。"
    else:
        fstate, fdetail = "todo", str(prof)
    add("profile", "建 profile overlay",
        "缺了它 codex **不报错**，会静默退回单号直连 —— 和正常运行长得一模一样",
        fstate, fdetail, preview=pblk)

    # ④ 入口
    bin_ = _local_bin()
    ours, theirs, miss = [], [], []
    for n, rel in ENTRIES.items():
        link = bin_ / n
        if link.is_symlink() and os.readlink(link) == str(runtime / rel):
            ours.append(n)
        elif link.exists() or link.is_symlink():
            theirs.append(n)          # ★ 存在但不是我们建的 —— 已经能用，别动
        else:
            miss.append(n)
    if miss:
        estate, edetail = "todo", "缺：" + "、".join(miss)
    elif theirs:
        estate = "external"
        edetail = "已存在（你自己建的，Connector 不碰）：" + "、".join(theirs)
    else:
        estate, edetail = "done", "四个入口都指向本运行时"
    add("entries", "建命令入口",
        "`cxp` 走代理轮换 · `cxd` 单号直连 · `codex-rotate` 管池子", estate, edetail,
        preview="\n".join(f"{n} → {runtime / rel}" for n, rel in ENTRIES.items()))

    # ⑤ 常驻服务
    names = ["autosync", "quotad", "proxy", "dawnprobe"]
    loaded = {n: _svc_loaded(n) for n in names}
    if any(v is None for v in loaded.values()):
        st = "todo"
        det = "查不了 launchctl —— 状态未知（这不等于没装）"
    elif all(loaded.values()):
        st, det = "done", "四个服务都在跑"
    else:
        st = "todo"
        det = "缺：" + "、".join(n for n in names if not loaded[n])
    # ★ Windows 上常驻服务走 `install-windows.ps1`(schtasks),而 `apply` 目前只调
    #   `install-launchd.sh`。**如实说装不了**,别让步骤名写着 launchd 却在 Windows 上跑 ——
    #   那样失败信息会指不到真因。本仓 Windows 侧整体仍是未验证的 beta。
    if sys.platform.startswith("win"):
        st, det = "blocked", ("Windows 上请跑 scripts\\install-windows.ps1 —— "
                              "Connector 目前只会装 macOS 的 launchd 服务。")
    add("services", "装常驻服务（launchd）" if not sys.platform.startswith("win")
        else "装常驻服务（Windows 计划任务）",
        "轮换代理要一直在；额度要自动刷新。**全部用户级，不需要 sudo**",
        st, det,
        preview="com.doushutangmu.codex-rotate.{autosync,quotad,proxy,dawnprobe}\n"
                "⚠️ dawnprobe 是唯一会自动花钱的定时器，**默认关闭**，装了也不会自己跑")

    # ⑥ 让裸 `codex` 也走轮换（**单独一步，默认不选**）
    wrapper = bin_ / "codex"
    want = str(runtime / "scripts" / "codex-wrapper-with-logout-guard.sh")
    if wrapper.is_symlink() and os.readlink(wrapper) == want:
        wstate, wdetail = "done", f"{wrapper} → 本运行时的 wrapper"
    elif wrapper.exists() or wrapper.is_symlink():
        wstate = "external"
        wdetail = (f"{wrapper} 已存在（你自己放的）。装这一步会把它**备份**为 "
                   f"`codex.before-codexbar` 再替换 —— 不会直接覆盖。")
    else:
        wstate, wdetail = "todo", f"{wrapper} → {want}"
    add(STEP_WRAPPER, "让 `codex` 本身也走轮换",
        "不装这一步，敲 `codex` 仍是官方单号直连；装了之后 `cxd` 是唯一的直连入口",
        wstate, wdetail, preview=want, optional=True)

    # ★ `external` 也算「已经在工作」—— 它确实在工作，只是不是我们装的。
    ready = all(s["state"] in ("done", "external") for s in steps if not s["optional"])
    blocked = any(s["state"] == "blocked" for s in steps)
    return {"steps": steps, "runtime": str(runtime), "inplace": inplace,
            "ready": ready, "blocked": blocked, "port": PROXY_PORT,
            "codex_home": str(_codex_home()), "local_bin": str(bin_)}


# ── apply ────────────────────────────────────────────────────────────────────

def _copy_runtime(src, runtime):
    for rel in RUNTIME_FILES:
        s, d = src / rel, runtime / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        if s.suffix in ("", ".sh") or os.access(s, os.X_OK):
            d.chmod(d.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _link(target, link):
    """建 symlink。★ **只覆盖 symlink，不覆盖普通文件** —— 用户可能在那儿放了自己的东西。"""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        backup = link.with_name(link.name + ".before-codexbar")
        link.rename(backup)
        return f"已把原有的 {link.name} 备份为 {backup.name}"
    link.symlink_to(target)
    return ""


def apply(src, store, want):
    src, store = Path(src).resolve(), Path(store).resolve()
    runtime = _runtime_dir(src, store)
    done, notes = [], []

    if "runtime" in want and runtime != src:
        _copy_runtime(src, runtime)
        done.append("runtime")

    if "provider" in want:
        _merge_managed(_codex_home() / "config.toml", provider_block(runtime))
        done.append("provider")

    if "profile" in want:
        _merge_managed(_codex_home() / "rotateproxy.config.toml", profile_block())
        done.append("profile")

    if "entries" in want:
        for name, rel in ENTRIES.items():
            n = _link(runtime / rel, _local_bin() / name)
            if n:
                notes.append(n)
        done.append("entries")

    if STEP_WRAPPER in want:
        n = _link(runtime / "scripts" / "codex-wrapper-with-logout-guard.sh",
                  _local_bin() / "codex")
        if n:
            notes.append(n)
        done.append(STEP_WRAPPER)

    if "services" in want:
        script = runtime / "scripts" / "install-launchd.sh"
        env = dict(os.environ, CODEX_ROTATE_STORE=str(store))
        r = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                           timeout=180, env=env)
        if r.returncode != 0:
            # ★ 失败要如实上报,不能吞成 ok —— 否则用户以为装好了,而代理根本没起。
            return {"ok": False, "done": done, "notes": notes,
                    "error": f"装 launchd 服务失败（exit {r.returncode}）：\n"
                             + (r.stderr or r.stdout)[-600:]}
        done.append("services")

    return {"ok": True, "done": done, "notes": notes, "error": None}


# ── remove ───────────────────────────────────────────────────────────────────

def remove(store, drop_runtime=False):
    """撤销。★ **只删我们自己建的东西** —— symlink 要先核对它指向我们的运行时。"""
    store = Path(store).resolve()
    runtime = store / "runtime"
    removed, kept = [], []

    for name in ["autosync", "quotad", "proxy", "dawnprobe"]:
        lbl = f"com.doushutangmu.codex-rotate.{name}"
        _launchctl(["bootout", f"gui/{os.getuid()}/{lbl}"])
        p = _launch_agents() / f"{lbl}.plist"
        if p.exists():
            p.unlink()
            removed.append(p.name)

    for name in list(ENTRIES) + ["codex"]:
        link = _local_bin() / name
        if not link.is_symlink():
            if link.exists():
                kept.append(f"{name}（不是我们建的 symlink，没动）")
            continue
        tgt = os.readlink(link)
        if str(runtime) in tgt or str(store) in tgt:
            link.unlink()
            removed.append(name)
        else:
            kept.append(f"{name}（指向 {tgt}，不是我们建的，没动）")

    for p in (_codex_home() / "config.toml", _codex_home() / "rotateproxy.config.toml"):
        before, managed, after = split_managed(_read(p))
        if managed is None:
            continue
        rest = (before + after).strip()
        if rest:
            _atomic_write(p, rest + "\n")
            removed.append(f"{p.name} 的托管区")
        else:
            p.unlink()
            removed.append(p.name)

    if drop_runtime and runtime.exists() and runtime != store:
        shutil.rmtree(runtime, ignore_errors=True)
        removed.append("runtime/")

    return {"ok": True, "removed": removed, "kept": kept}


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv):
    if not argv:
        print("usage: connector.py plan|apply|remove --src S --store D [--steps a,b] [--json]",
              file=sys.stderr)
        return 2
    sub = argv[0]

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    src = opt("--src", os.environ.get("CODEXBAR_SCRIPTS") or str(Path(__file__).resolve().parent))
    store = opt("--store", os.environ.get("CODEX_ROTATE_STORE") or src)
    as_json = "--json" in argv

    if sub == "plan":
        out = plan(src, store)
    elif sub == "apply":
        steps = [s for s in (opt("--steps", "") or "").split(",") if s]
        if not steps:
            print("apply 需要 --steps（逗号分隔）", file=sys.stderr)
            return 2
        out = apply(src, store, steps)
    elif sub == "remove":
        out = remove(store, drop_runtime="--drop-runtime" in argv)
    else:
        print(f"未知子命令 {sub}", file=sys.stderr)
        return 2

    if as_json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok", True) and not out.get("blocked") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

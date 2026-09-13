"""★★ PATH 入口闸：界面让用户去终端敲的命令，`docs/INSTALL.md` §2 必须给它建软链。

## 这条闸的由来（2026-09-13，用户实报）

    doushutangmu@… ~ % agy-rotate login
    zsh: command not found: agy-rotate

总览的 `+` 按钮弹的 toast 写着「加号：终端里跑 `agy-rotate login`」，
而装机文档只建了 `codex-rotate` / `cx` / `cxp` 三条软链 —— **界面承诺了一个
PATH 上不存在的命令**。本机当时能跑，只因为我手工 `ln -s` 了一次：
那条软链**不可复现**，换台机器、重装、或者别人 clone 都必然踩同一个坑。

## 判据为什么这么取

- **"用户要敲的命令"从界面源码里解析**，不在这里手列。手列一份清单，
  下一个新 CLI 出现时会再漏一次（本仓 `test_bundled_scripts.py` 同款理由）。
- 签名是「**名字 + 空格 + 子命令**」，不是「名字出现过」：
  `agy-quota` / `grok-quota` / `relay-ctl` 在源码里也出现，但那是传给 Rust 的
  进程名，用户从不敲它们 —— 只按名字匹配会把它们一起要求上 PATH，那是错的。
- **断言前必须剥注释**（本仓空守卫形态⑫）：`AccountCard.tsx` 的一句 JSDoc 里就写着
  `codex-rotate rename`，而注释不是界面文案。注释里提一句不该产生装机义务。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "docs" / "INSTALL.md"
UI_DIR = ROOT / "codexbar" / "src"

#: `agy-rotate login` / `codex-rotate credits` —— 名字后面跟着一个子命令词。
#: 名字本身从文件系统取（见 `root_clis()`），这里只负责"后面跟没跟子命令"。
#: ★ 外层 `(?:)` 不能省：`|` 的优先级最低，少了它整条正则会退化成
#: 「名字+短横线选项 **或者** 任意一个小写词」，于是**恒真** —— 实测一次，
#: 6 个 CLI 全被判成"界面让用户敲"，包括只作为进程名出现的那三个。
_SUBCMD = r"(?:[ \t]+--?\w|[ \t]+[a-z][a-z-]{2,})"

# 块注释 / JSX 注释；行注释单独处理（`https://` 里那对斜杠不能当注释剥）。
_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"(?<![:/])//.*")


def strip_comments(src):
    """剥掉 `/* */`、`{/* */}` 与 `//` 行注释。

    ★ `(?<![:/])` 是为了别把 `https://…` 的后半截当注释剥掉 —— 那会把同一行
    后面的真文案一起删掉，制造一条**假绿**（"界面没提这个命令"）。
    """
    return _LINE.sub("", _BLOCK.sub("", src))


def root_clis():
    """仓库根上所有带 shebang 的可执行文件 —— 候选 PATH 入口的真源。"""
    out = []
    for p in sorted(ROOT.iterdir()):
        if not p.is_file() or not (p.stat().st_mode & 0o111):
            continue
        try:
            with p.open("rb") as fh:
                if fh.read(2) == b"#!":
                    out.append(p.name)
        except OSError:
            pass
    return out


def ui_text():
    parts = []
    for p in sorted(UI_DIR.rglob("*")):
        if p.suffix in (".ts", ".tsx"):
            parts.append(strip_comments(p.read_text(encoding="utf-8")))
    return "\n".join(parts)


def commands_the_ui_tells_users_to_type(text=None, names=None):
    text = ui_text() if text is None else text
    names = root_clis() if names is None else names
    return sorted(n for n in names
                  if re.search(r"(?<![\w-])" + re.escape(n) + _SUBCMD, text))


def symlinked_in_install():
    """INSTALL.md 里**真的 `ln -sf` 出来**的 `~/.local/bin/<name>` 集合。

    ★ 不能只 grep `~/.local/bin/xxx`：文档里还有一段正文警告
    「agy 自带更新会改写 `~/.local/bin/agy`」—— 那是说明不是安装动作，
    把它算进来就等于让一句散文冒充一条软链。
    """
    body = INSTALL.read_text(encoding="utf-8")
    return set(re.findall(r"ln -sf[^\n]*?~/\.local/bin/([\w.-]+)", body))


class TheProbeItselfWorks(unittest.TestCase):
    """★ 先证探针有效。匹配数为 0 的正则会让整条闸恒绿 ——
    本仓老教训：扫描器查了 0 个对象却报"干净"。"""

    def test_the_repo_has_root_clis(self):
        self.assertGreaterEqual(len(root_clis()), 4,
                                f"只找到 {root_clis()} —— shebang 探针可能失效了")

    def test_the_ui_mentions_at_least_two_of_them(self):
        found = commands_the_ui_tells_users_to_type()
        self.assertGreaterEqual(len(found), 2,
                                f"界面里只解析到 {found} 条命令 —— 正则或剥注释逻辑坏了")

    def test_install_doc_parses(self):
        self.assertGreaterEqual(len(symlinked_in_install()), 3,
                                "INSTALL.md 里一条软链都没解析到")

    def test_comments_do_not_create_an_obligation(self):
        """★ 形态⑫的正面自检：三种注释里提到的命令**都不算**界面文案。
        不做这一条的话，`AccountCard.tsx` 那句 JSDoc 就会凭空要求一条软链。"""
        fake = ("// 见 zzz-tool rename\n"
                "/* 或者 zzz-tool switch */\n"
                "{/* zzz-tool login */}\n"
                "const ok = 1;\n")
        self.assertEqual(commands_the_ui_tells_users_to_type(strip_comments(fake), ["zzz-tool"]), [])

    def test_a_real_ui_string_does_create_one(self):
        """★ 反方向：剥注释不能把真文案一起剥掉（否则上一条恒绿）。"""
        real = 'const t = "加号：终端里跑 `zzz-tool login`";\n'
        self.assertEqual(commands_the_ui_tells_users_to_type(strip_comments(real), ["zzz-tool"]),
                         ["zzz-tool"])

    def test_a_bare_process_name_does_not_create_one(self):
        """★ `invoke("run", {bin: "zzz-tool"})` 这种传给 Rust 的进程名不是用户要敲的东西。"""
        bare = 'await invoke("spawn", { bin: "zzz-tool" });\n'
        self.assertEqual(commands_the_ui_tells_users_to_type(strip_comments(bare), ["zzz-tool"]), [])


class EveryCommandTheUiNamesIsOnPath(unittest.TestCase):

    def test_install_doc_symlinks_it(self):
        linked = symlinked_in_install()
        for name in commands_the_ui_tells_users_to_type():
            with self.subTest(cmd=name):
                self.assertIn(name, linked,
                              f"界面让用户敲 `{name} …`，但 INSTALL.md §2 没建软链 "
                              f"⇒ 用户拿到的是 command not found")

    def test_every_symlink_points_at_something_that_exists(self):
        """★ 反方向：文档写了但仓库里没有的入口，照着装会建出一条死链，
        而死链的症状（command not found）和"压根没建"一模一样。"""
        body = INSTALL.read_text(encoding="utf-8")
        dead = [src for src in re.findall(r'ln -sf "\$PWD/([^"]+)"', body)
                if not (ROOT / src).exists()]
        self.assertEqual(dead, [], f"INSTALL.md 指向不存在的文件: {dead}")

    def test_the_doc_chmods_what_it_links(self):
        """★ 软链建了但没 `chmod +x`，跑起来是 `permission denied` ——
        又是一条"装完了却用不了"，而文档看着是完整的。"""
        body = INSTALL.read_text(encoding="utf-8")
        linked = re.findall(r'ln -sf "\$PWD/([^"]+)"', body)
        chmod = re.search(r"chmod \+x ([^\n]+)", body)
        self.assertIsNotNone(chmod, "INSTALL.md §2 没有 chmod 行了")
        listed = set(chmod.group(1).split())
        missing = [s for s in linked if s not in listed]
        self.assertEqual(missing, [], f"建了软链却没 chmod: {missing}")


if __name__ == "__main__":
    unittest.main()

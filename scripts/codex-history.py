#!/usr/bin/env python3
"""Read local Codex history across providers; optionally hand a UUID to cxp."""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import unicodedata
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import UUID


class HistoryError(RuntimeError):
    pass


def read_sessions(home, cwd=None):
    database = home / "state_5.sqlite"
    if not database.is_file():
        raise HistoryError(f"找不到会话索引：{database}")
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute("""
                SELECT id, name, title, cwd, model_provider, updated_at, rollout_path
                FROM threads
                WHERE archived = 0 AND trim(first_user_message) <> ''
                  AND (thread_source = 'user' OR thread_source IS NULL)
                  AND source IN ('cli', 'vscode')
                  AND model_provider IN ('openai', 'rotateproxy')
                ORDER BY updated_at DESC, id DESC
            """)]
    except sqlite3.Error as exc:
        raise HistoryError("无法读取 Codex 会话索引；数据库不可用或当前版本 schema 不兼容。") from exc
    for row in rows:
        try:
            row["id"] = str(UUID(row["id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise HistoryError("会话索引包含无效 UUID，已停止。") from exc
        if not isinstance(row["cwd"], str) or not isinstance(row["rollout_path"], str):
            raise HistoryError("会话索引缺少有效的目录或历史文件路径。")
    if cwd is not None:
        rows = [row for row in rows if Path(row["cwd"]).resolve() == cwd.resolve()]
    return rows


def display_text(value, limit=100):
    text = "".join(c for c in str(value or "") if c.isspace() or not unicodedata.category(c).startswith("C"))
    return " ".join(text.split())[:limit]


def match_sessions(rows, query):
    query = query.casefold()
    return [row for row in rows if query in " ".join(
        str(row.get(key) or "") for key in ("id", "name", "title", "cwd")
    ).casefold()]


def print_rows(rows, start=0, show_commands=False):
    for index, row in enumerate(rows, start + 1):
        title = display_text(row["name"] or row["title"]) or "（未命名）"
        timestamp = datetime.fromtimestamp(row["updated_at"]).strftime("%Y-%m-%d %H:%M")
        missing = " [文件缺失]" if not Path(row["rollout_path"]).is_file() else ""
        print(f"{index:>3}. {timestamp}  {row['model_provider']:<11} {title}{missing}")
        print(f"     {row['id']}  {display_text(row['cwd'], 160)}")
        if show_commands:
            print(f"     cxp resume {row['id']}")


def select_session(rows):
    filtered, page = rows, 0
    while True:
        start = page * 20
        visible = filtered[start:start + 20]
        print(f"\n找到 {len(filtered)} 条会话 · 第 {page + 1}/{max(1, (len(filtered) + 19) // 20)} 页")
        print_rows(visible, start)
        try:
            answer = input("序号恢复 · /关键词搜索 · / 清除搜索 · n/p 翻页 · 回车/q 取消 > ").strip()
        except EOFError:
            return None
        if answer.casefold() in ("", "q"):
            return None
        if answer.startswith("/"):
            filtered, page = match_sessions(rows, answer[1:].strip()), 0
        elif answer.casefold() == "n" and start + 20 < len(filtered):
            page += 1
        elif answer.casefold() == "p" and page > 0:
            page -= 1
        elif answer.isascii() and answer.isdigit() and len(answer) <= 8:
            index = int(answer) - 1
            if start <= index < start + len(visible):
                return filtered[index]
            print("请选择当前页显示的序号。")


def resume_session(row, home):
    path = Path(row["rollout_path"]).resolve()
    if not path.is_file() or not path.is_relative_to((home / "sessions").resolve()):
        raise HistoryError("历史文件缺失或不在当前 CODEX_HOME/sessions 内；未恢复会话。")
    try:
        with path.open("rb") as source:
            header = source.readline(1024 * 1024)
        metadata = json.loads(header)
        if metadata.get("type") != "session_meta" or metadata.get("payload", {}).get("id") != row["id"]:
            raise HistoryError("历史文件 UUID 与索引不一致；未恢复会话。")
    except (ValueError, AttributeError) as exc:
        raise HistoryError("无法验证历史文件头；未恢复会话。") from exc
    executable = shutil.which("cxp")
    if not executable:
        raise HistoryError("找不到 cxp；请先恢复现有代理入口。")
    print(f"恢复 {row['id']}，交给官方 Codex 与 rotateproxy。", flush=True)
    os.execv(executable, [executable, "resume", row["id"]])


def main(argv=None):
    parser = argparse.ArgumentParser(description="跨 provider 查找旧会话；只读索引，不修改 codex resume。")
    parser.add_argument("--all", action="store_true", help="包含所有项目目录")
    parser.add_argument("--search", default="", help="按名称、标题、UUID 或项目路径搜索")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="输出 JSON 清单")
    mode.add_argument("--select", action="store_true", help="交互选择后调用 cxp resume UUID")
    args = parser.parse_args(argv)
    if args.select and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        raise HistoryError("--select 需要交互终端；请用默认清单或 --json，不会自动恢复最近会话。")
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
    rows = match_sessions(read_sessions(home, None if args.all else Path.cwd()), args.search)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
    elif args.select and rows:
        selected = select_session(rows)
        if selected is not None:
            resume_session(selected, home)
    else:
        print(f"找到 {len(rows)} 条会话（openai + rotateproxy；时间为本机时区）")
        print_rows(rows, show_commands=True)
        if not rows and not args.all:
            print("当前目录无匹配结果；--all 可搜索其他项目。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HistoryError, OSError) as exc:
        print(f"codex-history: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已取消；未恢复会话。", file=sys.stderr)
        sys.exit(130)

#!/usr/bin/env python3
"""map registry 的 `## Coordinator Recovery` 唯一短记录：读取、覆盖写入与格式检查。

只处理 fresh-session-boundaries.md §Coordinator Recovery 定义的一节；其余 registry 正文不解析。
show 只输出该节，避免整读不断增长的 map registry；set 原地覆盖并把被替换的旧恢复段移入
同目录 `history-<registry>`（不匹配 lane_graph 的 registry-*.md 扫描）；check 报告重复节、缺字段、
超长字段与 map registry 的模板外章节；compact 把模板外章节一次性移入 history。

用法：
  recovery_record.py show <registry>
  recovery_record.py set <registry> [--body-file PATH] [--archive HEADING_PREFIX ...]
  recovery_record.py check <registry> [...]
  recovery_record.py compact <registry>
  recovery_record.py --self-test
"""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import io
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HEADING = "## Coordinator Recovery"
FIELDS = ("Map/Spec", "Registry", "Gate/状态", "现场", "证据", "下一步")
ENTRY = "合同入口"
SECTION_RE = re.compile(r"^## .*$", re.M)
MAP_ROLE_RE = re.compile(r"^role: map$", re.M)
# 六项各写一句或证据指针；上限按已验收的短记录（DD-275 最长字段 718 字、整节 2210 字）留余量。
FIELD_MAX = 800
BODY_MAX = 3000


def sections(text: str) -> list[tuple[int, int, str]]:
    """返回全部二级节 (start, end, heading)。"""
    heads = list(SECTION_RE.finditer(text))
    return [(m.start(), heads[i + 1].start() if i + 1 < len(heads) else len(text), m.group(0))
            for i, m in enumerate(heads)]


def recovery_sections(text: str, extra: tuple[str, ...] = ()) -> list[tuple[int, int, str]]:
    prefixes = (HEADING,) + extra
    return [s for s in sections(text) if s[2].startswith(prefixes)]


def body_problems(body: str) -> list[str]:
    keys = [line.split("：", 1)[0].strip() for line in body.splitlines() if "：" in line]
    keys = [k for k in keys if k in FIELDS]
    problems = []
    if tuple(keys) != FIELDS:
        problems.append(f"六项字段缺失或乱序: {keys}")
    nxt = next((line for line in body.splitlines() if line.startswith("下一步：")), "")
    if ENTRY not in nxt:
        problems.append(f"下一步缺少 `{ENTRY}: <file>§<section>`")
    for line in body.splitlines():
        key = line.split("：", 1)[0].strip()
        if key in FIELDS and len(line) > FIELD_MAX:
            problems.append(f"{key} {len(line)} 字超过 {FIELD_MAX}：细节写进 artifacts_root，本项只留一句与证据指针")
    if len(body) > BODY_MAX:
        problems.append(f"恢复节 {len(body)} 字超过 {BODY_MAX}：已消费 lane 与历史批次只留证据指针")
    return problems


def extra_map_sections(text: str) -> list[str]:
    """map registry 只含 yaml row 与唯一恢复节；其余二级节（批次结果、Active lanes 等）属于工件。"""
    if not MAP_ROLE_RE.search(text):
        return []
    return [h for _, _, h in sections(text) if not h.startswith(HEADING)]


def text_problems(text: str) -> list[str]:
    found = recovery_sections(text)
    problems = []
    if len(found) > 1:
        problems.append(f"{len(found)} 个恢复节: " + " | ".join(h for _, _, h in found))
    if found:
        start, end, head = found[-1]
        if head != HEADING:
            problems.append(f"标题须为 `{HEADING}`，实际 `{head}`")
        problems += body_problems(text[start:end].split("\n", 1)[1] if "\n" in text[start:end] else "")
    extra = extra_map_sections(text)
    if extra:
        problems.append("map registry 模板外章节 " + " | ".join(extra)
                        + "：运行 `recovery_record.py compact <registry>` 移入 history，"
                          "批次结果写 artifacts_root，恢复节用证据指针引用")
    return problems


def check(path: Path) -> list[str]:
    return [f"{path}: {p}" for p in text_problems(path.read_text(encoding="utf-8"))]


def atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        h.write(text)
    os.replace(tmp, path)


def move_to_history(path: Path, text: str, spans: list[tuple[int, int, str]]) -> tuple[str, Path, int]:
    """把 spans 原文追加到 history-<registry>；返回 (去掉 spans 的正文, history 路径, 首个 span 位置)。"""
    history = path.with_name("history-" + path.name)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    moved = "".join(f"\n<!-- moved {stamp} from {path.name} -->\n" + text[s:e].rstrip("\n") + "\n"
                    for s, e, _ in spans)
    prior = history.read_text(encoding="utf-8") if history.exists() else f"# {path.name} 历史恢复段\n"
    atomic_write(history, prior.rstrip("\n") + "\n" + moved)
    kept, cursor = [], 0
    for s, e, _ in spans:
        kept.append(text[cursor:s])
        cursor = e
    kept.append(text[cursor:])
    return "".join(kept), history, spans[0][0]


def set_record(path: Path, body: str, archive: tuple[str, ...]) -> Path:
    body = body.strip("\n")
    problems = body_problems(body)
    if problems:
        raise ValueError("; ".join(problems))
    text = path.read_text(encoding="utf-8")
    extra = [h for h in extra_map_sections(text) if not h.startswith(archive or ("\0",))]
    if extra:
        raise ValueError("map registry 模板外章节 " + " | ".join(extra)
                         + "：先运行 `recovery_record.py compact <registry>`")
    old = recovery_sections(text, archive)
    new_section = f"{HEADING}\n\n{body}\n\n"
    history = path.with_name("history-" + path.name)
    if old:
        rest, history, pos = move_to_history(path, text, old)
        text = rest[:pos] + new_section + rest[pos:]
    else:
        text = text.rstrip("\n") + "\n\n" + new_section
    atomic_write(path, text.rstrip("\n") + "\n")
    readback = path.read_text(encoding="utf-8")
    if body not in readback or check(path):
        raise ValueError(f"readback 不一致: {check(path)}")
    return history


def compact(path: Path) -> Path:
    """一次性迁移：把 map registry 的模板外章节原文移入 history-<registry>，保留 yaml row 与恢复节。"""
    text = path.read_text(encoding="utf-8")
    extra = extra_map_sections(text)
    spans = [s for s in sections(text) if s[2] in extra]
    history = path.with_name("history-" + path.name)
    if not spans:
        return history
    rest, history, _ = move_to_history(path, text, spans)
    atomic_write(path, re.sub(r"\n{3,}", "\n\n", rest).rstrip("\n") + "\n")
    if extra_map_sections(path.read_text(encoding="utf-8")):
        raise ValueError(f"compact readback 仍有模板外章节: {path}")
    return history


def show(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    found = recovery_sections(text)
    if not found:
        print(f"{path}: Unknown（无 {HEADING} 节，按 registry/tracker/Git 重建）")
        return 1
    if len(found) > 1:
        print(f"WARN {len(found)} 个恢复节，输出最后一个；用 set 合并")
    start, end, _ = found[-1]
    print(text[start:end].rstrip("\n"))
    return 0


def self_test() -> int:
    good = "\n".join(f"{k}：x" for k in FIELDS[:-1]) + f"\n下一步：fan-in；{ENTRY}: a.md§B"
    with tempfile.TemporaryDirectory() as td:
        reg = Path(td) / "registry-9-map.md"
        reg.write_text("# map\n\n## Coordinator Recovery\n\n- 自由文本\n\n## 当前覆盖恢复段\n\nold\n\n"
                       "## Coordinator Recovery 2026-10-14 second\n\n- 旧\n\n## 进度\n\nkeep\n", encoding="utf-8")
        problems = check(reg)
        assert any("2 个恢复节" in p for p in problems), problems
        assert any("六项字段" in p for p in problems), problems
        history = set_record(reg, good, ("## 当前覆盖恢复段",))
        text = reg.read_text(encoding="utf-8")
        assert text.count(HEADING) == 1 and "## 进度\n\nkeep" in text and "old" not in text, text
        assert check(reg) == [], check(reg)
        hist = history.read_text(encoding="utf-8")
        assert "- 自由文本" in hist and "second" in hist and "当前覆盖恢复段" in hist, hist
        assert not any(fnmatch.fnmatch(history.name, g) for g in ("registry-*.md", "lane-registry.md")), history
        try:
            set_record(reg, good.replace(ENTRY, "入口"), ())
            raise AssertionError("缺合同入口必须失败")
        except ValueError:
            pass
        assert reg.read_text(encoding="utf-8") == text
        empty = Path(td) / "registry-10-map.md"
        empty.write_text("# map\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            assert check(empty) == [] and show(empty) == 1
        set_record(empty, good, ())
        assert check(empty) == []

        # map registry 只允许 yaml row + 唯一恢复节；批次结果等模板外章节被 check 报出，set 拒写。
        row = "<!-- wayfinder-lane-registry:v2 -->\n```yaml\nlane_id: m\nrole: map\n```\n"
        bloated = Path(td) / "registry-11-map.md"
        bloated.write_text(row + "\n## 交付边界\n\n- 约束\n\n## 批次 01 结果\n\n- 长篇\n\n"
                           f"{HEADING}\n\n{good}\n", encoding="utf-8")
        problems = check(bloated)
        assert any("模板外章节" in p and "批次 01 结果" in p for p in problems), problems
        before = bloated.read_text(encoding="utf-8")
        try:
            set_record(bloated, good, ())
            raise AssertionError("map registry 有模板外章节时 set 必须拒写")
        except ValueError as error:
            assert "compact" in str(error), error
        assert bloated.read_text(encoding="utf-8") == before
        # 非 map 的 lane registry 可以有附注章节。
        lane = Path(td) / "registry-11-lane.md"
        lane.write_text(row.replace("role: map", "role: backend") + "\n## 附注\n\nx\n", encoding="utf-8")
        assert check(lane) == [], check(lane)
        # compact 把模板外章节移入 history，恢复节保留；之后 check 通过。
        history = compact(bloated)
        text = bloated.read_text(encoding="utf-8")
        assert check(bloated) == [] and "批次 01" not in text and good in text, text
        hist = history.read_text(encoding="utf-8")
        assert "## 批次 01 结果" in hist and "## 交付边界" in hist, hist

        # 单个字段或整节超长 → 拒写，提示改成证据指针。
        long_field = good.replace("证据：x", "证据：" + "长" * (FIELD_MAX + 1))
        assert any("证据" in p and str(FIELD_MAX) in p for p in body_problems(long_field))
        long_body = "\n".join(f"{k}：" + "长" * (FIELD_MAX - 10) for k in FIELDS[:-1]) + \
            f"\n下一步：x；{ENTRY}: a.md§B"
        assert any(str(BODY_MAX) in p for p in body_problems(long_body))
    print("recovery_record self-test: pass (show, set, archive history, check, readback, "
          "map sections, compact, field/body limits)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("registry", type=Path)
    w = sub.add_parser("set")
    w.add_argument("registry", type=Path)
    w.add_argument("--body-file", type=Path, help="六项正文；省略时读 stdin")
    w.add_argument("--archive", action="append", default=[],
                   help="一并移入 history 的其他旧恢复节标题前缀，如 '## 当前覆盖恢复段'")
    c = sub.add_parser("check")
    c.add_argument("registry", type=Path, nargs="+")
    k = sub.add_parser("compact")
    k.add_argument("registry", type=Path)
    args = ap.parse_args()
    if args.cmd == "compact":
        try:
            history = compact(args.registry)
        except ValueError as error:
            print(f"recovery compact failed: {error}", file=sys.stderr)
            return 1
        print(f"recovery compact: {args.registry}; history: {history}")
        return 0
    if args.cmd == "show":
        return show(args.registry)
    if args.cmd == "set":
        body = args.body_file.read_text(encoding="utf-8") if args.body_file else sys.stdin.read()
        try:
            history = set_record(args.registry, body, tuple(args.archive))
        except ValueError as error:
            print(f"recovery set failed: {error}", file=sys.stderr)
            return 1
        print(f"recovery set: {args.registry}; history: {history}")
        return 0
    problems = [p for r in args.registry for p in check(r)]
    print("\n".join(problems) or "recovery check: pass")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

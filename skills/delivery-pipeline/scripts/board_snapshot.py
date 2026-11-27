#!/usr/bin/env python3
"""生成本机看板快照，或单独更新看板的 Linear 缓存。"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import Future
from contextlib import redirect_stdout
from datetime import datetime, timezone
from functools import cache
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
from runpy import run_path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from types import UnionType
from typing import Callable, Literal, TypedDict, cast, get_args, get_origin, get_type_hints, is_typeddict
from unittest.mock import patch

sys.dont_write_bytecode = True
import driver  # noqa: E402
import issue_status  # noqa: E402
from lane_graph import GH_ISSUE_RE, STATE_GROUP, parse_registry_file  # noqa: E402


Stage = Literal["spec", "tickets", "implement", "integrate", "review", "merge_review", "merged"]
LiveStatus = Literal["working", "not_working", "unknown"]
LaneGroup = Literal["done", "active", "review", "problem", "void"]
LinearStatus = Literal["ok", "partial", "failed"]


class LinearIssue(TypedDict):
    title: str
    status: str
    status_type: str
    parent: str | None
    description: str | None
    children: list[str] | None
    fetched_at: str


class BoardLinear(TypedDict):
    status: LinearStatus
    fetched_at: str | None
    attempted_at: str
    reason: str | None


class LinearCache(BoardLinear):
    version: Literal[1]
    issues: dict[str, LinearIssue]
    failed: dict[str, str]


class TicketLinearIssue(TypedDict):
    title: str
    status: str


class CandidateSpec(TypedDict):
    key: str
    url: str
    status: str


class MmfCandidate(TypedDict):
    mmf_id: str
    title: str
    spec: CandidateSpec | None
    source: Literal["epic_table", "linear_child"]


MmfEdge = TypedDict("MmfEdge", {
    "from": str, "to": str, "kind": Literal["开工", "上线", "Unknown"], "text": str,
})


class ProbeLane(TypedDict):
    lane_id: str
    overlay: dict[str, str | None]


LiveProbe = Callable[[list[ProbeLane]], dict[str, LiveStatus]]
LIVE_PROBES: dict[str, LiveProbe] = {}


def probe_lanes(runtime_prefix: str, lanes: list[ProbeLane]) -> dict[str, LiveStatus]:
    """按已解析的 runtime 前缀批量探测，每条缺少结果的 lane 为 unknown。"""
    probe = LIVE_PROBES.get(runtime_prefix)
    observed = probe(lanes) if probe is not None else {}
    return {lane["lane_id"]: observed.get(lane["lane_id"], "unknown") for lane in lanes}


class Lane(TypedDict):
    lane_id: str
    role: str
    state: str
    group: LaneGroup
    agent: str
    model: str
    worktree: str | None
    branch: str | None
    blocked_reason: str | None
    updated_at: str | None
    live: LiveStatus


class Halt(TypedDict):
    id: str
    kind: str
    label: str
    reason: str
    options: list[str]


class MmfLinks(TypedDict):
    plan_review: str | None
    merge_review: str | None
    linear: str | None


class TicketLinearFields(TypedDict, total=False):
    linear_issue: TicketLinearIssue


class Ticket(TicketLinearFields):
    id: str
    title: str
    deps: list[str]
    stage: Literal[Stage, "Unknown"]
    lane: Lane | None
    executing: bool
    linear: str | None


class MmfOptionalFields(TypedDict, total=False):
    archived_at: str
    mmf_id: str
    attribution_source: Literal["linear"]


class Mmf(MmfOptionalFields):
    map: str
    title: str
    stage: Literal[Stage, "Unknown"]
    halt: Halt | None
    links: MmfLinks
    updated_at: str | None
    direct_lanes: list[Lane]
    executing: bool
    tickets: list[Ticket]


class InboxKind(TypedDict, total=False):
    kind: Literal["spec", "item"]


class InboxItem(Mmf, InboxKind):
    repo: str
    attribution: Literal["unassigned"]


class EpicLinearFields(TypedDict, total=False):
    linear_status: str
    candidates: list[MmfCandidate]
    mmf_edges: list[MmfEdge]


class Epic(EpicLinearFields):
    key: str
    url: str | None
    title: str
    ended: bool
    mmfs: list[Mmf]


class Repo(TypedDict):
    name: str
    epics: list[Epic]


class ProbeResult(TypedDict):
    runtime: str
    status: Literal["ok", "missing", "failed"]
    reason: str | None


class BoardError(TypedDict):
    map: str
    reason: str


class BoardLinearFields(TypedDict, total=False):
    linear: BoardLinear


class BoardSnapshot(BoardLinearFields):
    schema: Literal[1]
    generated_at: str  # ISO 时间
    lanes_root: str
    repos: list[Repo]
    inbox: list[InboxItem]
    probes: list[ProbeResult]
    errors: list[BoardError]


SAMPLES = Path(__file__).resolve().with_name("board_samples")
SPEC_ARCHIVES = "spec-archives.json"
LINEAR_CACHE = "board-linear.json"
LINEAR_FIELDS = ["id", "title", "status", "statusType", "parentId"]
_field_types = cache(get_type_hints)


def _validate(value, field_type, path: str) -> None:
    origin = get_origin(field_type)
    args = get_args(field_type)
    if is_typeddict(field_type):
        if not isinstance(value, dict):
            raise ValueError(f"{path}: 需要对象")
        for field, child_type in _field_types(field_type).items():
            child_path = f"{path}.{field}"
            if field not in value:
                if field in field_type.__optional_keys__:
                    continue
                raise ValueError(f"{child_path}: 缺少必填字段")
            _validate(value[field], child_type, child_path)
    elif origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"{path}: 需要对象")
        for key, child in value.items():
            _validate(key, args[0], f"{path} 的键")
            _validate(child, args[1], f"{path}.{key}")
    elif origin is list:
        if not isinstance(value, list):
            raise ValueError(f"{path}: 需要数组")
        for index, child in enumerate(value):
            _validate(child, args[0], f"{path}[{index}]")
    elif origin is UnionType:  # JSON 联合类型均为 T | None。
        if value is not None:
            _validate(value, args[0], path)
    elif origin is Literal:
        if not any(type(value) is type(choice) and value == choice for choice in args):
            raise ValueError(f"{path}: 取值必须为 {', '.join(map(str, args))}")
    elif type(value) is not field_type:
        raise ValueError(f"{path}: 需要 {field_type.__name__}")


def validate_snapshot(value: object) -> BoardSnapshot:
    """校验 schema 1 的必填字段与类型，错误包含 JSON 字段路径。"""
    _validate(value, BoardSnapshot, "$")
    return cast(BoardSnapshot, value)


def validate_linear_cache(value: object) -> LinearCache:
    """校验 version 1 的 Linear 缓存，错误包含 JSON 字段路径。"""
    _validate(value, LinearCache, "$")
    return cast(LinearCache, value)


_BOARD_STAGE: dict[str, Stage] = {"todo": "implement", "started": "implement",
                                  "review": "review", "acceptance": "merge_review", "done": "merged"}


def _text(value) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _issue_base(ref: str | None) -> str | None:
    match = issue_status.URL_RE.match(ref or "")
    return match[0][:match.start(1)] if match else None


def _linear(ref: str | None, base: str | None) -> str | None:
    match = issue_status.URL_RE.match((ref or "").strip())
    if match:
        return match.group(0)
    key = issue_status.issue_key(ref)
    return base + key if base and key else None


def _lane(row: dict) -> Lane:
    state = row.get("state") or "Unknown"
    return {"lane_id": row["lane_id"], "role": row.get("role") or "Unknown", "state": state,
            "group": STATE_GROUP.get(state, "void"), "agent": row.get("agent") or "Unknown",
            "model": row.get("model") or "Unknown", "worktree": row.get("worktree"), "branch": row.get("branch"),
            "blocked_reason": row.get("blocked_reason") or row.get("close_reason"),
            "updated_at": row.get("updated_at"), "live": "unknown"}


def _ticket_row(rows):
    # 同一票有重试或合并 lane 时，优先展示当前仍有效的实施 lane。
    return max(rows, key=lambda row: (STATE_GROUP.get(row.get("state")) != "void",
                                      row.get("role") != "integration", row.get("updated_at") or ""),
               default=None)


def _halt(action: dict | None) -> Halt | None:
    if not action:
        return None
    args = action.get("args") or action
    return {"id": _text(action.get("id")) or "Unknown", "kind": _text(args.get("kind")) or "Unknown",
            "label": _text(args.get("label")) or "Unknown", "reason": _text(args.get("reason")) or "Unknown",
            "options": [value for value in (args.get("options") or ()) if isinstance(value, str)]}


def _review_link(path: Path, review: dict | None) -> str | None:
    html = _text((review or {}).get("html"))
    if not html or html.startswith(("http://", "https://", "file://")):
        return html
    return str(path / html)


def _tracker_issue(ref: str | None) -> str | None:
    if not ref:
        return None
    github = GH_ISSUE_RE.fullmatch(ref.split(maxsplit=1)[0])
    return github[0] if github else issue_status.issue_key(ref)


def _spec_ref(data: dict, plan: dict, epic_key: str | None) -> str | None:
    excluded = {None, epic_key}
    excluded.update(_tracker_issue(_text(ticket.get("url")) or _text(ticket.get("id")))
                    for ticket in (plan.get("tickets") or ()))
    for raw in ((data.get("gates") or {}).get("spec"), plan.get("spec")):
        ref = _text(raw)
        if _tracker_issue(ref) not in excluded:
            return ref
    return None


def _mmf(path: Path, name: str, d: dict | None, lanes: dict[str, dict],
         map_issue: str | None, spec_ref: str | None) -> Mmf:
    by_item = driver.lanes_by_item(lanes)
    data = d or {}
    plan = data.get("plan") or {}
    planned = plan.get("tickets") or ()
    ids = {t["id"] for t in planned}
    refs = [spec_ref, map_issue, _text((data.get("gates") or {}).get("spec")), _text(plan.get("spec"))]
    workspace = next((base for ref in [*refs, *(_text(t.get("url")) for t in planned)]
                      if (base := _issue_base(ref))), None)
    linear = next((link for ref in refs if (link := _linear(ref, workspace))), None)

    if d is None:
        stage = "Unknown"
    elif issue_status.is_merged(data):
        stage = "merged"
    elif current := issue_status.spec_stage(data, by_item):
        stage = _BOARD_STAGE[current]
    else:
        stage = "tickets" if spec_ref else "Unknown"

    tickets = []
    for ticket in planned:
        ident = ticket["id"]
        rows = by_item.get(ident, ())
        current_stage = issue_status.ticket_stage(data, rows)
        ticket_link = _linear(_text(ticket.get("url")) or ident, workspace)
        row = _ticket_row(rows)
        tickets.append({"id": ident, "title": _text(ticket.get("title")) or "Unknown",
                        "deps": [dep for dep in (ticket.get("deps") or ()) if dep in ids],
                        "stage": "integrate" if current_stage == "review" else _BOARD_STAGE.get(current_stage, "Unknown"),
                        "lane": _lane(row) if row else None, "executing": False, "linear": ticket_link})

    reviews = data.get("reviews") or {}
    direct_roles = {"integration", "testing", "review"}
    direct = [_lane(row) for _, row in sorted(lanes.items())
              if row.get("work_item") not in ids and (
                  row.get("role") in direct_roles if d is not None else row.get("role") != "map"
              )]
    updated = max((row.get("updated_at") or "" for row in lanes.values()), default="")
    return {"map": name, "title": _text(plan.get("mmf")) or _text(plan.get("title")) or "Unknown",
            "stage": stage, "halt": _halt(data.get("halt")), "updated_at": updated or None,
            "links": {"plan_review": _review_link(path, reviews.get("plan")),
                      "merge_review": _review_link(path, reviews.get("merge")), "linear": linear},
            "direct_lanes": direct, "executing": False, "tickets": tickets}


def _read_repo(source: str) -> str | None:
    common = driver.closeout.common_dir(source)
    if common is None:
        return None
    if Path(common).name == ".git":
        return Path(common).parent.name
    result = driver.run_git(source, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).name if result.returncode == 0 else None


def _load_live_probes() -> None:
    scripts = Path(__file__).resolve().parent
    if scripts.name == "scripts":
        paths = scripts.parents[1].glob("*/scripts/board_probe.py")
    else:
        paths = (scripts / "board_probes").glob("*.py")
    for path in sorted(paths):
        run_path(str(path))["register"](LIVE_PROBES)


def _probe_overlay(row: dict, prefix: str, read_registry: Callable) -> dict[str, str | None]:
    overlay = row.get(prefix)
    if isinstance(overlay, str):
        try:
            overlay = json.loads(overlay)
        except ValueError:
            return {}
    elif overlay is None and prefix in row:
        # 旧的多行覆盖段仍用原 registry 解析器读取。
        try:
            overlay = read_registry(row["_file"]).get(row["lane_id"], {}).get(prefix)
        except OSError:
            return {}
    if not isinstance(overlay, dict):
        return {}
    return {key: value for key, value in overlay.items() if value is None or isinstance(value, str)}


def _apply_live_probes(maps: list[tuple[Mmf, dict[str, dict]]]) -> list[ProbeResult]:
    batches: dict[str, list[tuple[str, Lane, dict]]] = {}
    for mmf, rows in maps:
        lanes = [*mmf["direct_lanes"], *(t["lane"] for t in mmf["tickets"])]
        for lane in lanes:
            if lane is not None and lane["state"] == "running":
                row = rows[lane["lane_id"]]
                prefix = (row.get("runtime") or "Unknown").split("-", 1)[0]
                batches.setdefault(prefix, []).append((mmf["map"], lane, row))

    @cache
    def read_registry(path: str) -> dict[str, dict]:
        return {row["lane_id"]: row for row in parse_registry_file(Path(path))}

    results: list[ProbeResult] = []
    for prefix, batch in sorted(batches.items()):
        if prefix not in LIVE_PROBES:
            results.append({"runtime": prefix, "status": "missing", "reason": "没有注册探针"})
            continue
        counts = Counter(lane["lane_id"] for _, lane, _ in batch)
        inputs: list[ProbeLane] = []
        try:
            for name, lane, row in batch:
                lane_id = lane["lane_id"]
                # registry 的 lane ID 在各 map 内唯一，批次跨 map 时补足坐标。
                request_id = f"{name}/{lane_id}" if counts[lane_id] > 1 else lane_id
                inputs.append({"lane_id": request_id, "overlay": _probe_overlay(row, prefix, read_registry)})
            observed = probe_lanes(prefix, inputs)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            results.append({"runtime": prefix, "status": "failed", "reason": str(error)})
            continue
        missing = 0
        for (_, lane, _), item in zip(batch, inputs):
            lane["live"] = observed[item["lane_id"]]
            missing += lane["live"] == "unknown"
        reason = f"{missing} 条 running lane 未匹配到现场" if missing else None
        results.append({"runtime": prefix, "status": "missing" if missing else "ok", "reason": reason})

    for mmf, _ in maps:
        mmf["executing"] = any(lane["state"] == "running" and lane["live"] == "working"
                               for lane in mmf["direct_lanes"])
        for ticket in mmf["tickets"]:
            lane = ticket["lane"]
            ticket["executing"] = lane is not None and lane["state"] == "running" and lane["live"] == "working"
    return results


def _read_snapshot(lanes_root: str) -> tuple[BoardSnapshot, set[str], set[str]]:
    root = Path(lanes_root).expanduser().absolute()
    errors: list[BoardError] = []
    archives: dict[str, str] = {}
    try:
        archives = json.loads((root / SPEC_ARCHIVES).read_text(encoding="utf-8"))
        _validate(archives, dict[str, str], "$.archives")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as error:
        errors.append({"map": SPEC_ARCHIVES, "reason": str(error)})
        archives = {}
    inbox: list[InboxItem] = []
    spec_keys: set[str] = set()
    inbox_spec_keys: set[str] = set()
    epics_by_repo: dict[str, dict[str, Epic]] = {}
    repo_at = cache(_read_repo)
    maps: list[tuple[Mmf, dict[str, dict]]] = []

    def add(path, name, data, lanes):
        if data is None and not lanes:
            raise ValueError("缺少可读的 driver.json 与 registry")
        plan = (data or {}).get("plan") or {}
        mrow = driver.map_row(lanes) or {}
        source = mrow.get("source_worktree_path")
        repo = (repo_at(source) if source else None) or _text(plan.get("repo")) or "Unknown"
        ref = _text(mrow.get("epic")) or _text(plan.get("epic"))
        key = issue_status.issue_key(ref)
        spec = _spec_ref(data or {}, plan, key)
        mmf = _mmf(path, name, data, lanes, _text(mrow.get("work_item")), spec)
        _validate(mmf, Mmf, "$.mmf")
        if spec_key := issue_status.issue_key(spec):
            spec_keys.add(spec_key)
            if not key:
                inbox_spec_keys.add(spec_key)
        if not key or not spec:
            inbox_item: InboxItem = {**mmf, "repo": repo, "attribution": "unassigned",
                                     "kind": "spec" if spec else "item"}
            inbox.append(inbox_item)
            mmf = inbox_item
        else:
            if archived_at := archives.get(issue_status.issue_key(spec) or ""):
                mmf["archived_at"] = archived_at
            base = _issue_base(ref) or _issue_base(mmf["links"]["linear"])
            url = base + key if base else None
            epic = epics_by_repo.setdefault(repo, {}).setdefault(key, {
                "key": key, "url": url, "title": "Unknown", "ended": True, "mmfs": []})
            epic["url"] = epic["url"] or url
            epic["mmfs"].append(mmf)
            epic["ended"] = epic["ended"] and (mmf["stage"] == "merged" or bool(mmf.get("archived_at")))
        maps.append((mmf, lanes))

    # 根层保留旧布局的 map；同一 map 已迁入目录时，目录现场优先。单份根层 registry 不可读只记错误。
    root_rows: dict[str, dict] = {}
    try:
        root_files = driver.closeout.registry_files(root)
    except OSError as error:
        errors.append({"map": root.name, "reason": str(error)})
        root_files = []
    for registry_file in root_files:
        try:
            for row in driver.closeout.parse_rows(registry_file):
                root_rows[row["lane_id"]] = row
        except OSError as error:
            errors.append({"map": registry_file.name, "reason": str(error)})
    root_maps = {lid: {lid: row} for lid, row in root_rows.items() if row.get("role") == "map"}
    aliases = {rows[lid]["work_item"]: lid for lid, rows in root_maps.items() if rows[lid].get("work_item")}
    for lid, row in root_rows.items():
        ref = row.get("map")
        key = aliases.get(ref, ref)
        if row.get("role") != "map" and key in root_maps:
            root_maps[key][lid] = row

    for path in sorted(root.iterdir()):
        if path.name == "artifacts" or path.is_symlink() or not path.is_dir():
            continue
        old = root_maps.pop(path.name, {})
        try:
            state = driver.load(path)
            current = state["lanes"]
            if not current:
                # 部分旧目录用自定义 registry 文件名，原写入器留下了同名锁。
                for lock in sorted(path.glob("*.md.lock")):
                    registry = lock.with_suffix("")
                    if registry.is_file():
                        current.update((row["lane_id"], row) for row in parse_registry_file(registry))
            map_id = (driver.map_row(current) or {}).get("lane_id")
            lanes = old | root_maps.pop(map_id, {}) | current
            add(path, path.name, state["driver"], lanes)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            errors.append({"map": path.name, "reason": str(error)})
    for name, lanes in sorted(root_maps.items()):
        try:
            add(root, name, None, lanes)
        except (OSError, ValueError) as error:
            errors.append({"map": name, "reason": str(error)})
    repos = [{"name": name, "epics": sorted(epics.values(), key=lambda epic: epic["key"])}
             for name, epics in sorted(epics_by_repo.items())]
    snapshot = validate_snapshot({"schema": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                                  "lanes_root": lanes_root, "repos": repos, "inbox": inbox,
                                  "probes": _apply_live_probes(maps), "errors": errors})
    return snapshot, spec_keys, inbox_spec_keys


def read_snapshot(lanes_root: str) -> BoardSnapshot:
    return _read_snapshot(lanes_root)[0]


def refresh_archives(lanes_root: str, call=issue_status.linear_call) -> dict[str, str]:
    root = Path(lanes_root).expanduser().absolute()
    existing: dict[str, str] = {}
    try:
        loaded = json.loads((root / SPEC_ARCHIVES).read_text(encoding="utf-8"))
        _validate(loaded, dict[str, str], "$.archives")
        existing = dict(loaded)
    except (FileNotFoundError, OSError, ValueError):
        existing = {}
    board = read_snapshot(str(root))
    keys = {issue_status.issue_key(mmf["links"]["linear"])
            for repo in board["repos"] for epic in repo["epics"] for mmf in epic["mmfs"]}
    # 有 map 读取失败时保留未重新核验的既有归档缓存，不因部分失败清空已确认记录。
    archived: dict[str, str] = dict(existing) if board["errors"] else {}
    for key in sorted(k for k in keys if k):
        issue = call("get_issue", {"id": key, "fields": ["id", "archivedAt"]})
        if issue.get("id") != key or "archivedAt" not in issue:
            raise ValueError(f"{key} 归档回读不符")
        if at := _text(issue["archivedAt"]):
            archived[key] = at
        else:
            archived.pop(key, None)
    driver.write_json(root / SPEC_ARCHIVES, archived)
    return archived


def _linear_rows(call: Callable, parent: str) -> dict[str, dict]:
    args = {"parentId": parent, "includeArchived": True, "fields": LINEAR_FIELDS}
    rows: dict[str, dict] = {}
    while True:
        page = call("list_issues", args)
        for row in page if isinstance(page, list) else page["issues"]:
            key = issue_status.issue_key(row["id"])
            if key is None:
                raise ValueError(f"{parent} 子项缺少 Linear issue key")
            rows[key] = row
        if isinstance(page, list) or not page.get("hasNextPage"):
            return rows
        cursor = page.get("cursor")
        if not cursor or cursor == args.get("cursor"):
            raise ValueError(f"{parent} 子项列表缺少下一页游标")
        args = {**args, "cursor": cursor}


def _linear_fact(raw: dict, parent: str | None, children: list[str] | None, at: str) -> LinearIssue:
    fact: LinearIssue = {"title": raw["title"], "status": raw["status"], "status_type": raw["statusType"],
                         "parent": parent, "children": children, "fetched_at": at,
                         "description": raw.get("description") if children is not None else None}
    _validate(fact, LinearIssue, "$.issue")
    return fact


class _LinearDeadline(TimeoutError):
    pass


def _collect_linear(root: Path, call: Callable, at: str) -> tuple[dict[str, LinearIssue], dict[str, str]]:
    board, specs, inbox = _read_snapshot(str(root))
    epics = {epic["key"] for repo in board["repos"] for epic in repo["epics"]}
    details: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    parents: dict[str, str] = {}
    issues: dict[str, LinearIssue] = {}
    failed: dict[str, str] = {}
    linear_errors = (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError)

    def lookup(ref):
        if ref in aliases:
            return aliases[ref]
        raw = call("get_issue", {"id": ref, "fields": [*LINEAR_FIELDS, "uuid", "description"]})
        key = issue_status.issue_key(raw["id"])
        if key is None or issue_status.issue_key(ref) not in (None, key):
            raise ValueError(f"{ref} issue 回读不符")
        details[key] = raw
        aliases.update({ref: key, key: key})
        if uuid := _text(raw.get("uuid")):
            aliases[uuid] = key
        return key

    def record(ref, error):
        if isinstance(error, _LinearDeadline):
            raise error
        failed[ref] = str(error) or type(error).__name__

    def read_group(ref, *, epic):
        key = aliases.get(ref, ref)
        if key in failed or (key in issues and issues[key]["children"] is not None):
            return
        try:
            key = lookup(ref)
            rows = _linear_rows(call, key)
            issues[key] = _linear_fact(details[key], None, list(rows), at)
        except linear_errors as error:
            record(key, error)
            return
        if epic:
            parents.update(dict.fromkeys(rows, key))
            specs.update(rows)
            return
        for child, raw in rows.items():
            if child in issues and issues[child]["children"] is not None:
                continue
            try:
                issues[child] = _linear_fact(raw, key, None, at)
            except linear_errors as error:
                record(child, error)

    for key in sorted(epics):
        read_group(key, epic=True)
    for key in sorted(inbox):
        try:
            raw = details[lookup(key)]
        except linear_errors as error:
            record(key, error)
            continue
        if parent := _text(raw.get("parentId")):
            read_group(parent, epic=True)
    for key in sorted(specs):
        read_group(key, epic=False)
    for key, raw in details.items():
        if key in issues and issues[key]["children"] is not None:
            ref = _text(raw.get("parentId"))
            issues[key]["parent"] = aliases.get(ref) or issue_status.issue_key(ref) or parents.get(key)
    return issues, failed


def refresh_linear(lanes_root: str, call=issue_status.linear_call, deadline_s: float = 120) -> LinearCache:
    """通过只读 Linear 通道刷新缓存，失败时保留上次读回的事实。"""
    deadline = monotonic() + deadline_s
    at = datetime.now(timezone.utc).isoformat()
    root = Path(lanes_root).expanduser().absolute()
    path = root / LINEAR_CACHE
    result: LinearCache = {"version": 1, "attempted_at": at, "fetched_at": None,
                           "status": "failed", "reason": None, "issues": {}, "failed": {}}
    try:
        previous = validate_linear_cache(json.loads(path.read_text(encoding="utf-8")))
        result.update(fetched_at=previous["fetched_at"], issues=previous["issues"])
    except (OSError, ValueError):
        pass

    # 有界等待包含采集本机坐标及所有 Linear 调用。只由调用方提交缓存。
    future: Future[tuple[dict[str, LinearIssue], dict[str, str]]] = Future()

    def remaining():
        seconds = deadline - monotonic()
        if seconds <= 0:
            raise _LinearDeadline
        return seconds

    def read(tool, args):
        remaining()
        return call(tool, args)

    def collect():
        try:
            remaining()
            future.set_result(_collect_linear(root, read, at))
        except Exception as error:
            future.set_exception(error)

    try:
        Thread(target=collect, daemon=True).start()
        fresh, failed = future.result(timeout=remaining())
        remaining()
    except TimeoutError:
        result["reason"] = f"Linear 更新超过 {deadline_s:g} 秒时限"
    else:
        result["failed"] = failed
        if failed and not fresh:
            result["reason"] = f"Linear 更新全部失败：{next(iter(failed.values()))}"
        else:
            # 失败节点及其旧子项仍可用。同一子项本次有新回读时以新值为准。
            old = result["issues"]
            retained: dict[str, LinearIssue] = {}
            pending = list(failed)
            while pending:
                key = pending.pop()
                if key in old and key not in retained:
                    retained[key] = old[key]
                    pending.extend(old[key]["children"] or ())
            result.update(status="partial" if failed else "ok", fetched_at=at,
                          reason="部分 Linear 条目读取失败" if failed else None, issues=retained | fresh)
    driver.write_json(path, result)
    return result


def _expect_rejection(snapshot: object, path: str) -> None:
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        if str(error).startswith(path + ":"):
            return
        raise AssertionError(f"期望拒绝 {path}，实际为 {error}") from error
    raise AssertionError(f"应拒绝 {path}")


def _test_required_fields(snapshot: BoardSnapshot, value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in list(value.items()):
            child_path = f"{path}.{key}"
            del value[key]
            _expect_rejection(snapshot, child_path)
            value[key] = child
            _test_required_fields(snapshot, child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _test_required_fields(snapshot, child, f"{path}[{index}]")


def _running_lanes(snapshot: BoardSnapshot) -> list[Lane]:
    mmfs = [mmf for repo in snapshot["repos"] for epic in repo["epics"] for mmf in epic["mmfs"]]
    lanes = [lane for mmf in [*mmfs, *snapshot["inbox"]] for lane in mmf["direct_lanes"]]
    for mmf in [*mmfs, *snapshot["inbox"]]:
        for ticket in mmf["tickets"]:
            if (lane := ticket["lane"]) is not None:
                lanes.append(lane)
    return [lane for lane in lanes if lane["state"] == "running"]


def _test_local_snapshot() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp) / "lanes"
        source = Path(temp) / "source-repo"
        subprocess.run(["git", "init", "-q", str(source)], check=True)

        def registry(path, *rows):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(
                "<!-- wayfinder-lane-registry:v2 -->\n```yaml\n"
                + "".join(f"{key}: {value}\n" for key, value in row.items()) + "```\n"
                for row in rows), encoding="utf-8")

        def write_driver(name, plan=None, **milestones):
            folder = root / name
            folder.mkdir(parents=True, exist_ok=True)
            data = {"grant": {"plan_sha": "fixture"}, "published": "fixture", **milestones,
                    "gates": {"spec": "https://linear.app/demo/issue/DEMO-2"}, "plan": plan or {}}
            (folder / "driver.json").write_text(json.dumps(data), encoding="utf-8")
            return data

        rows = {"01": [{"lane_id": "done-01", "work_item": "01", "role": "backend", "state": "integrated"}],
                "02": [{"lane_id": "running-02", "work_item": "02", "role": "backend", "state": "running"}]}
        short = "https://linear.app/demo/issue/DEMO-1"
        d = write_driver("active", {"repo": "other", "mmf": "Active", "tickets": [
            {"id": "01", "url": "https://linear.app/demo/issue/DEMO-11"},
            {"id": "02", "deps": ["01", "outside-this-map"]}, {"id": "03", "deps": ["02"]}]})
        registry(root / "active" / "registry.md",
                 {"lane_id": "active-map", "role": "map", "work_item": "DEMO-2",
                  "epic": short, "source_worktree_path": source}, *rows["01"], *rows["02"])
        write_driver("sibling", {"repo": "source-repo", "epic": short + "/slug"}, status="done")
        write_driver("ended", {"repo": "plan-repo", "epic": "https://linear.app/demo/issue/DEMO-3"},
                     remote={"merge": "ok"})
        write_driver("unknown-repo", {"epic": "DEMO-3"}, status="done")
        registry(root / "registry-loose.md", {"lane_id": "loose-map", "work_item": "DEMO-4", "role": "map"},
                 {"lane_id": "loose-lane", "map": "loose-map", "work_item": "DEMO-15", "role": "backend",
                  "state": "blocked"})
        legacy = root / "legacy" / "ticket-worker.md"
        registry(legacy, {"lane_id": "legacy-worker", "work_item": "DEMO-16", "role": "backend",
                          "state": "closed"})
        legacy.with_suffix(".md.lock").touch()
        for name, repo, state in [("inbox-run", "source-repo", "running"),
                                  ("inbox-block", "plan-repo", "blocked"),
                                  ("inbox-merged", "source-repo", "closed")]:
            write_driver(name, {"repo": repo, "tickets": [{"id": "01"}]},
                         status="done" if state == "closed" else None)
            registry(root / name / "registry-01.md",
                     {"lane_id": name + "-01", "work_item": "01", "role": "backend", "state": state})
        loose = write_driver("direct-issue", {"epic": short, "repo": "source-repo",
                                             "tickets": [{"id": "DEMO-31"}]})
        loose["gates"]["spec"] = "https://linear.app/demo/issue/DEMO-31"
        (root / "direct-issue" / "driver.json").write_text(json.dumps(loose), encoding="utf-8")
        registry(root / "direct-issue" / "registry.md",
                 {"lane_id": "direct-issue", "role": "map", "work_item": "DEMO-31", "epic": short})
        epic_spec = write_driver("epic-as-spec", {"epic": short, "repo": "source-repo",
                                                  "tickets": [{"id": "01"}]})
        epic_spec["gates"]["spec"] = short
        (root / "epic-as-spec" / "driver.json").write_text(json.dumps(epic_spec), encoding="utf-8")
        registry(root / "epic-as-spec" / "registry.md",
                 {"lane_id": "epic-as-spec", "role": "map", "work_item": "DEMO-1", "epic": short})
        (root / "broken").mkdir()
        (root / "broken" / "driver.json").write_text("{bad json", encoding="utf-8")
        for folder in (root / "artifacts", root / "active" / "artifacts"):
            registry(folder / "registry-old.md", {"lane_id": "old-world", "work_item": "DEMO-99", "role": "map"})

        def fingerprint():
            return {p.relative_to(root): (sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in root.rglob("*") if p.is_file()}

        # 每次从 CLI 入口运行，禁止 socket 和 Git 之外的子进程。
        offline = """
import runpy, sys
from pathlib import Path
sys.argv.pop(0)
sys.path.insert(0, str(Path(sys.argv[0]).parent))
def guard(event, args):
    if event.startswith('socket.') or (event == 'subprocess.Popen' and args[0] != 'git'):
        raise AssertionError(f'快照尝试非本地读取：{event}')
sys.addaudithook(guard)
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        before = fingerprint()
        outputs = [subprocess.check_output([sys.executable, "-B", "-c", offline, __file__, "--lanes-root", str(root)],
                                          text=True) for _ in range(2)]
        assert fingerprint() == before  # S2
        snapshots = [validate_snapshot(json.loads(output)) for output in outputs]  # S8
        for snapshot in snapshots:
            del snapshot["generated_at"]
        snapshot, repeated = snapshots
        assert snapshot == repeated and snapshot["lanes_root"] == str(root)  # S2
        assert [(e["map"], bool(e["reason"])) for e in snapshot["errors"]] == [("broken", True)]  # S3
        assert "old-world" not in outputs[0]  # S7

        repos = {r["name"]: r["epics"] for r in snapshot["repos"]}
        assert set(repos) == {"source-repo", "plan-repo", "Unknown"}  # S5
        assert {e["key"] for epics in repos.values() for e in epics} == {"DEMO-1", "DEMO-3"}  # S8
        [epic] = repos["source-repo"]
        assert epic["key"] == "DEMO-1" and not epic["ended"] and repos["plan-repo"][0]["ended"]
        assert [m["map"] for m in epic["mmfs"]] == ["active", "sibling"]  # S4
        active = epic["mmfs"][0]
        assert active["stage"] == "implement" and active["title"] == "Active"
        [first, running, undispatched] = active["tickets"]
        assert [(t["id"], t["stage"]) for t in active["tickets"]] == [
            ("01", "integrate"), ("02", "implement"), ("03", "implement")]  # S1
        assert first["lane"]["state"] == "integrated" and running["lane"]["state"] == "running"
        assert running["deps"] == ["01"] and undispatched["deps"] == ["02"]
        assert undispatched["lane"] is None and running["lane"]["live"] == "unknown"
        from issue_status import targets
        assert targets(d, rows) == {"DEMO-2": "started", "DEMO-11": "review"}

        inbox = {m["map"]: m for m in snapshot["inbox"]}
        assert set(inbox) == {"inbox-run", "inbox-block", "inbox-merged", "loose-map", "legacy", "direct-issue", "epic-as-spec"}
        assert inbox["direct-issue"]["kind"] == "item"
        assert inbox["direct-issue"]["links"]["linear"] == "https://linear.app/demo/issue/DEMO-31"
        assert inbox["epic-as-spec"]["kind"] == "item"
        assert inbox["epic-as-spec"]["links"]["linear"] == short
        assert inbox["inbox-run"]["kind"] == "spec"
        assert inbox["loose-map"]["kind"] == "item"
        assert inbox["loose-map"]["direct_lanes"][0]["lane_id"] == "loose-lane"
        assert inbox["legacy"]["direct_lanes"][0]["lane_id"] == "legacy-worker"
        for name, repo, stage in [("inbox-run", "source-repo", "implement"),
                                  ("inbox-block", "plan-repo", "implement"),
                                  ("inbox-merged", "source-repo", "merged")]:
            m = inbox[name]
            assert (m["repo"], m["stage"], m["executing"], m["attribution"]) == (repo, stage, False, "unassigned")
            assert m["links"]["linear"] == "https://linear.app/demo/issue/DEMO-2"  # S19

        archived_fixture = write_driver("archived-only", {"repo": "source-repo", "epic": short})
        archived_fixture["gates"]["spec"] = "https://linear.app/demo/issue/DEMO-42"
        (root / "archived-only" / "driver.json").write_text(json.dumps(archived_fixture), encoding="utf-8")
        archived_time = "2026-11-25T00:18:14Z"
        def archive_lookup(tool, args):
            assert tool == "get_issue" and args["fields"] == ["id", "archivedAt"]
            key = args["id"]
            return {"id": key, "archivedAt": archived_time if key == "DEMO-42" else None}
        assert refresh_archives(str(root), archive_lookup) == {"DEMO-42": archived_time}
        refreshed = read_snapshot(str(root))
        archived_mmf = next(m for r in refreshed["repos"] for e in r["epics"] for m in e["mmfs"]
                            if m["map"] == "archived-only")
        assert archived_mmf["stage"] == "implement" and archived_mmf["archived_at"] == archived_time

        states = {"A": "running", "Z": "running", "B": "created", "C": "awaiting_human",
                  "D": "blocked", "E": "terminal", "F": "integrated", "H": "unrecognized"}
        write_driver("execution-q", {"tickets": [{"id": ticket} for ticket in [*states, "G"]]})
        registry(root / "execution-q" / "registry.md", *(
            {"lane_id": ticket, "work_item": ticket, "role": "backend", "state": state,
             "runtime": "fixture-agent"} for ticket, state in states.items()))
        write_driver("execution-p", {"tickets": [{"id": "I"}]})
        registry(root / "execution-p" / "registry.md",
                 {"lane_id": "map-p", "work_item": "DEMO-20", "role": "map", "state": "running",
                  "runtime": "fixture-agent"},
                 {"lane_id": "merge-p", "work_item": "DEMO-20", "role": "integration", "state": "running",
                  "runtime": "fixture-agent"},
                 {"lane_id": "I", "work_item": "I", "role": "backend", "state": "integrated",
                  "runtime": "fixture-agent"})

        def fixture_probe(lanes):
            assert {lane["lane_id"] for lane in lanes} == {"A", "Z", "merge-p"}
            return {"A": "working", "merge-p": "working"}

        with patch.dict(LIVE_PROBES, {"fixture": fixture_probe}):
            observed = {m["map"]: m for m in read_snapshot(str(root))["inbox"]}
        q = observed["execution-q"]
        assert [t["id"] for t in q["tickets"] if t["executing"]] == ["A"]  # S13
        assert next(t for t in q["tickets"] if t["id"] == "Z")["lane"]["live"] == "unknown"
        p = observed["execution-p"]
        assert p["executing"] and not p["tickets"][0]["executing"] and not q["executing"]  # S14

        # SP-08：复合 gates.spec 含本机路径后缀时，只提取合法 Linear URL。
        compound = write_driver("compound-ref", {"repo": "source-repo"})
        compound["gates"]["spec"] = "https://linear.app/demo/issue/DEMO-55 ; /tmp/spec.md"
        (root / "compound-ref" / "driver.json").write_text(json.dumps(compound), encoding="utf-8")
        compound_snap = read_snapshot(str(root))
        compound_item = next(m for m in compound_snap["inbox"] if m["map"] == "compound-ref")
        assert compound_item["links"]["linear"] == "https://linear.app/demo/issue/DEMO-55"

        # SP-15：计划外 backend 补票不计入 MMF direct_lanes，不让 mmf.executing 为真。
        write_driver("supplement-only", {"repo": "source-repo", "epic": short, "tickets": [{"id": "A"}]})
        registry(root / "supplement-only" / "registry-sup.md",
                 {"lane_id": "sup-1", "work_item": "SUPPLEMENT", "role": "backend", "state": "running",
                  "runtime": "fixture-local"})
        with patch.dict(LIVE_PROBES, {"fixture": lambda ls: {l["lane_id"]: "working" for l in ls}}):
            sup_snap = read_snapshot(str(root))
        sup_mmf = next(m for r in sup_snap["repos"] for e in r["epics"] for m in e["mmfs"]
                       if m["map"] == "supplement-only")
        assert sup_mmf["direct_lanes"] == [] and not sup_mmf["executing"]

        # SP-14 / STD-02：map 临时损坏时 refresh_archives 不清空已有归档缓存。
        (root / "archived-only" / "driver.json").write_text("{broken", encoding="utf-8")
        kept = refresh_archives(str(root), lambda tool, args: {"id": args["id"], "archivedAt": None})
        assert kept.get("DEMO-42") == archived_time
        (root / "archived-only" / "driver.json").write_text(json.dumps(archived_fixture), encoding="utf-8")
        restored = read_snapshot(str(root))
        restored_mmf = next(m for r in restored["repos"] for e in r["epics"] for m in e["mmfs"]
                            if m["map"] == "archived-only")
        assert restored_mmf.get("archived_at") == archived_time

        # SP-12 / STD-03：根层单份 registry 不可读只记 errors，不中断其余健康 map。
        unreadable = root / "registry-unreadable.md"
        unreadable.write_text("", encoding="utf-8")
        unreadable.chmod(0o000)
        try:
            resilient = read_snapshot(str(root))
            assert any(e["map"] == "registry-unreadable.md" for e in resilient["errors"])
            assert any(r["name"] == "source-repo" for r in resilient["repos"])
        finally:
            unreadable.chmod(0o600)
            unreadable.unlink()


def _test_linear_refresh() -> None:
    def issue(key, title, parent=None):
        return {"id": key, "title": title, "status": "Todo", "statusType": "unstarted",
                "parentId": parent, "description": f"正文 {key}"}

    with TemporaryDirectory() as temp:
        root = Path(temp)
        cache_path = root / LINEAR_CACHE
        url = "https://linear.app/demo/issue/"
        for spec, epic, ticket in [("DEMO-2", "DEMO-1", "DEMO-12"), ("DEMO-3", "DEMO-1", "DEMO-13"),
                                   ("DEMO-5", None, "DEMO-15")]:
            folder = root / spec
            folder.mkdir()
            (folder / "driver.json").write_text(json.dumps({"gates": {"spec": url + spec if epic else spec}, "plan": {
                "repo": "fixture", "epic": url + epic if epic else None, "tickets": [{"id": ticket}],
            }}))
            (folder / "registry.md").write_text(
                f"<!-- wayfinder-lane-registry:v2 -->\n```yaml\nlane_id: map-{spec}\n"
                f"role: map\nwork_item: {spec}\n```\n")

        native_children = {"DEMO-1": ["DEMO-2", "DEMO-3"], "DEMO-2": ["DEMO-12"], "DEMO-3": ["DEMO-13"],
                           "DEMO-4": ["DEMO-5", "DEMO-6"], "DEMO-5": ["DEMO-15"], "DEMO-6": []}
        parents = {child: key for key, children in native_children.items() for child in children}
        original = {key: issue(key, f"旧 {key}", parents.get(key)) for key in set(native_children) | parents.keys()}
        # Inbox Spec 返回父项 UUID。缓存里仍然使用 issue key。
        original["DEMO-4"]["uuid"] = "6f63519f-4802-4038-a26c-b8ac847f1d07"
        original["DEMO-5"]["parentId"] = original["DEMO-4"]["uuid"]
        calls = []

        def linear(tool, args):
            assert tool in {"get_issue", "list_issues"}, tool
            ident = args["id"] if tool == "get_issue" else args["parentId"]
            key = "DEMO-4" if ident == original["DEMO-4"]["uuid"] else ident
            calls.append((tool, key))
            if tool == "get_issue":
                return data[key]
            if key == fail_list:
                raise RuntimeError("子项列表读取失败")
            return {"issues": [data[child] for child in native_children[key]], "hasNextPage": False}

        def fingerprints():
            return {path.relative_to(root): sha256(path.read_bytes()).hexdigest()
                    for path in root.rglob("*") if path.is_file() and path != cache_path}

        def update(call=linear):
            with patch.object(issue_status, "linear_call", call), redirect_stdout(StringIO()) as stdout:
                assert main(["--lanes-root", temp, "--refresh-linear"]) == 0
            summary = json.loads(stdout.getvalue())
            assert summary["status"] == (saved := read_cache())["status"]
            return saved

        def read_cache():
            return validate_linear_cache(json.loads(cache_path.read_text()))

        before = fingerprints()
        data, fail_list = original, None
        ok = update()  # S8
        assert ok["status"] == "ok" and ok["failed"] == {} and ok["fetched_at"]
        assert ok["issues"].keys() == original.keys()
        assert Counter(calls) == Counter((tool, key) for key in native_children for tool in ("get_issue", "list_issues"))
        assert ok["issues"]["DEMO-1"]["children"] == ["DEMO-2", "DEMO-3"]
        assert ok["issues"]["DEMO-6"]["children"] == []  # 尚无本机 map 的原生子项
        assert ok["issues"]["DEMO-5"]["parent"] == "DEMO-4"
        assert ok["issues"]["DEMO-13"]["parent"] == "DEMO-3"
        assert ok["issues"]["DEMO-13"]["description"] is None
        assert fingerprints() == before

        data = {key: {**row, "title": f"新 {key}", "status": "In Progress", "statusType": "started"}
                for key, row in original.items()}
        fail_list = "DEMO-3"
        partial = update()  # S9
        assert partial["status"] == "partial" and partial["fetched_at"] == partial["attempted_at"]
        assert partial["failed"] == {"DEMO-3": "子项列表读取失败"}
        assert partial["issues"].keys() == original.keys()
        for key, row in partial["issues"].items():
            if key in {"DEMO-3", "DEMO-13"}:
                assert row == ok["issues"][key]
            else:
                assert (row["title"], row["status"]) == (f"新 {key}", "In Progress")

        cache_path.unlink()

        def unavailable(tool, args):
            raise RuntimeError("Linear 暂不可用")

        failed = update(unavailable)  # S10，无旧缓存
        assert failed["status"] == "failed" and failed["fetched_at"] is None and not failed["issues"]
        assert set(failed["failed"].values()) == {"Linear 暂不可用"}

        driver.write_json(cache_path, ok)
        entered, release = Event(), Event()

        def slow(tool, args):
            entered.set()
            release.wait(5)
            return linear(tool, args)

        try:
            timed_out = refresh_linear(temp, slow, deadline_s=0.2)  # S10，旧成功缓存
            assert entered.is_set() and not release.is_set()
            assert timed_out == read_cache()
            assert timed_out["status"] == "failed" and timed_out["reason"]
            assert timed_out["fetched_at"] == ok["fetched_at"] and timed_out["issues"] == ok["issues"]
            assert fingerprints() == before
        finally:
            release.set()


def self_test() -> None:
    for path in sorted(SAMPLES.glob("*.json")):
        if path.name.startswith("linear-cache-"):
            sample = validate_linear_cache(json.loads(path.read_text(encoding="utf-8")))
            assert path.stem == f"linear-cache-{sample['status']}"
            continue

        raw = json.loads(path.read_text(encoding="utf-8"))
        snapshot = validate_snapshot(raw)
        _expect_rejection(snapshot | {"schema": 2}, "$.schema")
        if path.name == "board-linear.json":
            raw["repos"][0]["epics"][0]["candidates"][0]["source"] = "undefined"
            _expect_rejection(raw, "$.repos[0].epics[0].candidates[0].source")
            continue
        if path.name == "board-linear-failed.json":
            assert snapshot["linear"]["status"] == "failed"
            continue

        _test_required_fields(snapshot, snapshot)

        running = _running_lanes(snapshot)
        assert running, f"{path.name} 必须含 running lane"
        inputs: list[ProbeLane] = [{"lane_id": lane["lane_id"], "overlay": {}} for lane in running]
        assert not LIVE_PROBES
        assert probe_lanes("fixture", inputs) == {lane["lane_id"]: "unknown" for lane in running}

    if m1 := os.environ.get("BOARD_M1_SNAPSHOT"):
        validate_snapshot(json.loads(Path(m1).read_text(encoding="utf-8")))

    _test_local_snapshot()
    _test_linear_refresh()
    print("board_snapshot self-test ok")


def main(argv: list[str]) -> int:
    if argv == ["self-test"]:
        self_test()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lanes-root", required=True)
    refresh = parser.add_mutually_exclusive_group()
    refresh.add_argument("--refresh-archives", action="store_true", help="从 Linear 更新本机 Epic Spec 的归档记录")
    refresh.add_argument("--refresh-linear", action="store_true", help="更新看板的 Linear 缓存")
    args = parser.parse_args(argv)
    if args.refresh_archives:
        print(json.dumps(refresh_archives(args.lanes_root), ensure_ascii=False))
        return 0
    if args.refresh_linear:
        result = refresh_linear(args.lanes_root, call=issue_status.linear_call)
        summary = {key: result[key] for key in ("status", "fetched_at", "attempted_at", "reason", "failed")}
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    _load_live_probes()
    print(json.dumps(read_snapshot(args.lanes_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

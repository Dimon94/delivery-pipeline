#!/usr/bin/env python3
"""从本机 Driver 与 lane registry 只读生成 schema 1 看板快照。"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from functools import cache
from hashlib import sha256
import json
from pathlib import Path
from runpy import run_path
import subprocess
import sys
from tempfile import TemporaryDirectory
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


class Ticket(TypedDict):
    id: str
    title: str
    deps: list[str]
    stage: Literal[Stage, "Unknown"]
    lane: Lane | None
    executing: bool
    linear: str | None


class MmfHistory(TypedDict, total=False):
    archived_at: str


class Mmf(MmfHistory):
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


class Epic(TypedDict):
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


class BoardSnapshot(TypedDict):
    schema: Literal[1]
    generated_at: str  # ISO 时间
    lanes_root: str
    repos: list[Repo]
    inbox: list[InboxItem]
    probes: list[ProbeResult]
    errors: list[BoardError]


SAMPLES = Path(__file__).resolve().with_name("board_samples")
SPEC_ARCHIVES = "spec-archives.json"
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
    elif origin is UnionType:  # schema 1 的联合类型均为 T | None。
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


_BOARD_STAGE: dict[str, Stage] = {"todo": "implement", "started": "implement",
                                  "review": "review", "acceptance": "merge_review", "done": "merged"}


def _text(value) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _issue_base(ref: str | None) -> str | None:
    match = issue_status.URL_RE.match(ref or "")
    return match[0][:match.start(1)] if match else None


def _linear(ref: str | None, base: str | None) -> str | None:
    if _issue_base(ref):
        return ref
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
    direct = [_lane(row) for _, row in sorted(lanes.items())
              if row.get("role") != "map" and row.get("work_item") not in ids]
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


def read_snapshot(lanes_root: str) -> BoardSnapshot:
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

    # 根层保留旧布局的 map；同一 map 已迁入目录时，目录现场优先。
    root_rows = driver.closeout.latest_rows(root)
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
    return validate_snapshot({"schema": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                              "lanes_root": lanes_root, "repos": repos, "inbox": inbox,
                              "probes": _apply_live_probes(maps), "errors": errors})


def refresh_archives(lanes_root: str, call=issue_status.linear_call) -> dict[str, str]:
    root = Path(lanes_root).expanduser().absolute()
    board = read_snapshot(str(root))
    keys = {issue_status.issue_key(mmf["links"]["linear"])
            for repo in board["repos"] for epic in repo["epics"] for mmf in epic["mmfs"]}
    archived = {}
    for key in sorted(k for k in keys if k):
        issue = call("get_issue", {"id": key, "fields": ["id", "archivedAt"]})
        if issue.get("id") != key or "archivedAt" not in issue:
            raise ValueError(f"{key} 归档回读不符")
        if at := _text(issue["archivedAt"]):
            archived[key] = at
    driver.write_json(root / SPEC_ARCHIVES, archived)
    return archived


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


def self_test() -> None:
    for path in sorted(SAMPLES.glob("*.json")):
        snapshot = validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
        _test_required_fields(snapshot, snapshot)
        _expect_rejection(snapshot | {"schema": 2}, "$.schema")

        running = _running_lanes(snapshot)
        assert running, f"{path.name} 必须含 running lane"
        inputs: list[ProbeLane] = [{"lane_id": lane["lane_id"], "overlay": {}} for lane in running]
        assert not LIVE_PROBES
        assert probe_lanes("fixture", inputs) == {lane["lane_id"]: "unknown" for lane in running}

    _test_local_snapshot()
    print("board_snapshot self-test ok")


def main(argv: list[str]) -> int:
    if argv == ["self-test"]:
        self_test()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lanes-root", required=True)
    parser.add_argument("--refresh-archives", action="store_true", help="从 Linear 更新本机 Epic Spec 的归档记录")
    args = parser.parse_args(argv)
    if args.refresh_archives:
        print(json.dumps(refresh_archives(args.lanes_root), ensure_ascii=False))
        return 0
    _load_live_probes()
    print(json.dumps(read_snapshot(args.lanes_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

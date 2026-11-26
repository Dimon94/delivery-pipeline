#!/usr/bin/env python3
"""看板快照 schema 1、现场探针接口与只读样本入口。"""
from __future__ import annotations

import argparse
from functools import cache
import json
from pathlib import Path
import subprocess
import sys
from types import UnionType
from typing import Callable, Literal, TypedDict, cast, get_args, get_origin, get_type_hints, is_typeddict


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


class Mmf(TypedDict):
    map: str
    title: str
    stage: Literal[Stage, "Unknown"]
    halt: Halt | None
    links: MmfLinks
    updated_at: str | None
    direct_lanes: list[Lane]
    executing: bool
    tickets: list[Ticket]


class InboxItem(Mmf):
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
SAMPLE = SAMPLES / "board.json"
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
                raise ValueError(f"{child_path}: 缺少必填字段")
            _validate(value[field], child_type, child_path)
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


def read_snapshot(lanes_root: str) -> BoardSnapshot:
    """样本桩以传入的目录作输出坐标，不读取该目录。"""
    snapshot = json.loads(SAMPLE.read_text(encoding="utf-8"))
    snapshot["lanes_root"] = lanes_root
    return validate_snapshot(snapshot)


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

    root = "/fixture/任意目录"
    output = subprocess.check_output([sys.executable, __file__, "--lanes-root", root], text=True)
    snapshot = validate_snapshot(json.loads(output))
    expected = json.loads(SAMPLE.read_text(encoding="utf-8")) | {"lanes_root": root}
    assert snapshot == expected
    assert all(lane["live"] == "unknown" for lane in _running_lanes(snapshot))
    print("board_snapshot self-test ok")


def main(argv: list[str]) -> int:
    if argv == ["self-test"]:
        self_test()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lanes-root", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(read_snapshot(args.lanes_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

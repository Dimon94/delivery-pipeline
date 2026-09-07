#!/usr/bin/env python3
"""核对实施分派的证据结构；tracker 内容与确认有效性由 coordinator 实时回读。"""
import json
import sys


def require_text(value, field):
    if not isinstance(value, str) or value.strip().lower() in ("", "unknown", "none", "null"):
        raise ValueError("实施 gate 缺失证据: " + field)


def check(data):
    if not isinstance(data, dict):
        raise ValueError("实施 gate 输入必须是 JSON object")
    evidence = data.get("gate_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("实施前须完成 to-spec → to-tickets；缺少 gate_evidence")
    require_text(data.get("work_item"), "work_item")
    require_text(evidence.get("readback"), "readback 来源与时间")
    for stage in ("spec", "ticket"):
        item = evidence.get(stage)
        if not isinstance(item, dict):
            raise ValueError("实施 gate 缺失: " + stage)
        for field in ("url", "body", "owner_run", "confirmation"):
            require_text(item.get(field), stage + "." + field)
    spec, ticket = evidence["spec"], evidence["ticket"]
    require_text(ticket.get("sizing"), "ticket-sizing 逐票判定产物")
    if ticket.get("parent") != spec["url"] or ticket["url"] != data["work_item"]:
        raise ValueError("实施 ticket / Spec Parent 回链不匹配")
    dependencies = ticket.get("dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("缺少拆票 dependency edges 回读；无依赖须为 []")
    for dependency in dependencies:
        require_text(dependency, "dependency")
    if data.get("map") is not None:
        require_text(data["map"], "map")
        if spec.get("source_map") != data["map"]:
            raise ValueError("Spec source map 回链不匹配")
        require_text(evidence.get("discovery"), "discovery resolution 与确认")
    return evidence


if __name__ == "__main__":
    try:
        check(json.load(sys.stdin))
        print("implementation gate: pass")
    except (ValueError, TypeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

#!/usr/bin/env python3
"""从协调者刚读回的 Issue 和运行证据计算 Epic frontier。"""
import json
import sys
from graphlib import CycleError, TopologicalSorter
from urllib.parse import urlsplit


GATES = {"development", "release"}
STATES = GATES | {"candidate", "active", "blocked", "accepted"}


def text(value, field):
    if not isinstance(value, str) or not value.strip() or value.strip().lower() == "unknown":
        raise ValueError(f"{field} 缺少有效值")
    return value


def issue_url(value, field):
    url = urlsplit(text(value, field))
    if url.scheme not in {"http", "https"} or not url.hostname or not url.path.strip("/"):
        raise ValueError(f"{field} 需要 Issue URL")
    return value


def read_items(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("需要 Epic 读回对象")
    epic = issue_url(snapshot.get("epic"), "epic")
    rows = snapshot.get("items")
    if not isinstance(rows, list) or not rows:
        raise ValueError("items 需要至少一个 MMF")
    items = {}
    coordinates = {epic}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("MMF 需要对象")
        key = text(row.get("id"), "id")
        if key.startswith("external:") or key in items:
            raise ValueError(f"MMF 标识非法或重复：{key}")
        state = text(row.get("state"), f"{key}.state")
        if state not in STATES:
            raise ValueError(f"{key}.state 非法：{state}")
        for field in ("map", "spec"):
            if row.get(field) is None:
                continue
            url = issue_url(row[field], f"{key}.{field}")
            if url in coordinates:
                raise ValueError(f"重复坐标：{url}")
            coordinates.add(url)
        if state in {"release", "accepted"}:
            issue_url(row.get("spec"), f"{key}.spec")
        if state == "accepted":
            text(row.get("acceptance"), f"{key}.acceptance")
        items[key] = row
    return items


def pending_dependencies(key, item, items):
    dependencies = item.get("dependencies")
    if dependencies is None and item["state"] in {"candidate", "blocked", "active"}:
        return []
    if not isinstance(dependencies, list):
        raise ValueError(f"{key}.dependencies 需要数组")
    pending = []
    for edge in dependencies:
        if not isinstance(edge, dict):
            raise ValueError(f"{key} 的依赖需要对象")
        source = text(edge.get("source"), f"{key}.dependencies.source")
        gate = text(edge.get("gate"), f"{key}.dependencies.gate")
        requires = text(edge.get("requires"), f"{key}.dependencies.requires")
        external = source.startswith("external:") and len(source) > len("external:")
        if gate not in GATES or requires not in {"evidence", "accepted"}:
            raise ValueError(f"{key} 的依赖阶段或解除条件非法：{source}")
        if source == key or (source not in items and not (external and requires == "evidence")):
            raise ValueError(f"{key} 的依赖指向自身或未知 MMF：{source}")
        if requires == "accepted":
            satisfied = items[source]["state"] == "accepted"
        else:
            evidence = edge.get("evidence")
            satisfied = evidence is not None and bool(text(evidence, f"{key}:{source}.evidence"))
        if not satisfied:
            pending.append({"source": source, "gate": gate, "requires": requires})
    return pending


def acceptance_cycle(pending):
    graph = TopologicalSorter()
    for key, edges in pending.items():
        graph.add(("release", key), ("development", key))
        for edge in edges:
            if edge["requires"] == "accepted":
                graph.add((edge["gate"], key), ("release", edge["source"]))
    try:
        graph.prepare()
    except CycleError as error:
        return [{"gate": gate, "id": key} for gate, key in error.args[1]]
    return []


def frontier(snapshot):
    items = read_items(snapshot)
    focus = snapshot.get("mmf")
    if focus is not None and text(focus, "mmf") not in items:
        raise ValueError(f"未知 MMF：{focus}")
    pending = {key: pending_dependencies(key, row, items) for key, row in items.items()}
    result = {
        "development": [], "release": [], "active": [], "waiting": {},
        "accepted": [key for key, row in items.items() if row["state"] == "accepted"],
        "cycle": acceptance_cycle(pending),
    }
    for key, row in items.items():
        state = row["state"]
        if state == "accepted" or (focus is not None and key != focus):
            continue
        target = {"id": key, **{field: row[field] for field in ("map", "spec") if row.get(field)}}
        if state == "active":
            result["active"].append(target)
        else:
            blockers = [edge for edge in pending[key]
                        if state != "development" or edge["gate"] == "development"]
            if state in GATES and not blockers:
                result[state].append(target)
            else:
                waiting = {"state": state}
                if blockers:
                    waiting["dependencies"] = blockers
                result["waiting"][key] = waiting
    result["done"] = len(result["accepted"]) == len(items)
    return result


def main():
    try:
        result = frontier(json.load(sys.stdin))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

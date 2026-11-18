#!/usr/bin/env python3
"""使用共享 Registry 串行化同一宿主上 Epic 的首次写入与接管。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from epic_frontier import issue_url, text
from lane_registry import lock, persist, rows


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def transition(path, action, epic, owner, previous=None, evidence=None):
    with lock(path) as path:
        live = [row for row in rows(path).values() if row.get("state") == "running"]
        if len(live) > 1 or any(row.get("work_item") != epic for row in live):
            raise ValueError("Epic registry 身份不一致")
        current = live[0] if live else None
        mine = current and current.get("coordinator") == owner
        if action == "verify":
            if not mine:
                raise ValueError("当前会话未持有 Epic 写入权")
            return current
        if action == "release":
            if not mine:
                raise ValueError("仅当前持有者可释放 Epic 写入权")
            released = {**current, "state": "closed"}
            persist(path, [released])
            return released
        if mine:
            return current
        if current and action == "claim":
            raise ValueError("Epic 已有 coordinator：" + current["coordinator"])
        if action == "handoff":
            text(evidence, "前任退出与运行现场证据")
            if not current or current.get("coordinator") != previous:
                raise ValueError("Epic 前任身份已变化，重新读回后再接管")
        row = {
            "lane_id": "epic-" + key(owner),
            "role": "map",
            "work_item": epic,
            "coordinator": owner,
            "state": "running",
        }
        if current:
            row["handoff_evidence"] = evidence
            persist(path, [{**current, "state": "closed"}, row])
        else:
            persist(path, [row])
        return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("claim", "verify", "release", "handoff"))
    action = parser.parse_args().action
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("需要 Epic 认领请求")
        epic = issue_url(request.get("epic"), "epic").rstrip("/")
        owner = text(request.get("owner"), "owner")
        path = Path.home() / ".config/delivery-pipeline/epic-runs" / f"epic-{key(epic)}.md"
        row = transition(path, action, epic, owner, request.get("previous"), request.get("evidence"))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps({"registry": str(path), **row}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

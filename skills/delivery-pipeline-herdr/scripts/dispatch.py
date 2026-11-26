#!/usr/bin/env python3
"""Herdr lane 一次派发：解析计划 → 写 registry → 落 pane → 启动 agent → 投递 packet →
确认 working → 挂 watcher → 回写 running。成功只打印一行 JSON 坐标；失败写 setup_blocked。

用法：
  dispatch.py --evidence <capability.json> --task <task type>
              --output-mode <mode> --lane <lane_id> --work-item <url> --title <pane label>
              --worktree <abs> --branch <branch> --base <sha> --packet <abs> --registry <abs .md>
              --map-registry <abs map registry .md | none>
              --tab-prefix <tab 前缀> [--ticket-mode NAME] [--map-mode NAME] [--off-chain-reason TEXT]

派发前（任何 herdr 调用前）拒绝：lane 名超过 Herdr agent 名上限、map registry 未通过
recovery_record.py check、packet owner 已移出交付链路且未给 --off-chain-reason。
registry 记录 contract_rev（派发时 skill 仓 HEAD）与 map（map registry 的 lane_id）。
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_CONFIG = HERE.parents[1] / "delivery-pipeline-setup" / "scripts" / "model_config.py"
RECOVERY_RECORD = HERE.parents[1] / "delivery-pipeline" / "scripts" / "recovery_record.py"
HERDR_NAME_MAX = 32
MAX_WORKSPACE_COLS = 20
MAX_TAB_PREFIX_COLS = 18
MAX_PANE_COLS = 24
CJK_RE = re.compile(r"[\u3400-\u9FFF]")
FULLWIDTH_RE = re.compile(r"[\u2E80-\u9FFF\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFFEF]")
ANY_ISSUE_KEY_RE = re.compile(r"(?:^|\s)(?:[A-Z][A-Z0-9]*-\d+|#\d+)(?:\s|$)")
LINEAR_KEY_RE = re.compile(r"^(?:https?://linear\.app/[^/]+/issue/)?([A-Z][A-Z0-9]*-\d+)(?:/|$|\?|#)", re.I)
GITHUB_ISSUE_RE = re.compile(r"^https?://github\.com/[^/]+/[^/]+/issues/(\d+)(?:/|$|\?|#)", re.I)
# 已移出交付链路、只作独立 skill 保留的 owner（5ecd9ce）；链路内派发须显式写理由。
OFF_CHAIN_OWNERS = {"ticket-sizing"}
OWNER_RE = re.compile(r"^Owner[：:]\s*([^；;\s]+)", re.M)
WATCHER = Path(os.environ.get("DP_LANE_WATCH", HERE / "lane-watch.sh"))
TAB_CAPACITY = 4
RUNTIME = {"pi": "herdr-pi-pane", "codex": "herdr-codex-pane", "claude": "herdr-claude-pane", "antigravity": "herdr-agy-pane"}


class DispatchError(Exception):
    pass


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_model_config():
    return load_module("model_config", MODEL_CONFIG)


def agent_name(lane: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", lane.lower()).strip("-") or "lane"


def display_width(text: str) -> int:
    return sum(2 if FULLWIDTH_RE.match(ch) else 1 for ch in text)


def extract_issue_key(work_item: str) -> str | None:
    value = (work_item or "").strip()
    m = LINEAR_KEY_RE.match(value)
    if m:
        return m.group(1).upper()
    m = GITHUB_ISSUE_RE.match(value)
    if m:
        return f"#{m.group(1)}"
    return None


def format_visual_label(work_item: str, label: str, max_cols: int, kind: str) -> str:
    cleaned = re.sub(r"\s+", " ", (label or "").strip())
    if len(CJK_RE.findall(cleaned)) < 2:
        raise DispatchError(f"{kind} label {cleaned!r} lacks a 中文简写 (>= 2 汉字); "
                            f"use '<Issue> <中文简写>[ <英文>]' such as 'JB-548 扩表Job'")
    key = extract_issue_key(work_item)
    formatted = f"{key} {cleaned}" if (key and not ANY_ISSUE_KEY_RE.search(cleaned)) else cleaned
    width = display_width(formatted)
    if width > max_cols:
        raise DispatchError(
            f"{kind} label {formatted!r} display width {width} exceeds limit {max_cols} "
            f"(CJK=2, ASCII=1); shorten to compact '<Issue> <中文简写>[ <英文>]'"
        )
    return formatted


def contract_rev() -> str:
    result = subprocess.run(["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "Unknown"


def preflight(args) -> str | None:
    """herdr 调用前的确定性拒绝；返回 map lane_id（--map-registry none 时为 None）。"""
    name = agent_name(args.lane)
    if len(name) > HERDR_NAME_MAX:
        raise DispatchError(f"lane name {name!r} is {len(name)} chars; Herdr agent names allow "
                            f"{HERDR_NAME_MAX}: shorten to {name[:HERDR_NAME_MAX].rstrip('-')!r} or similar")
    args.title = format_visual_label(args.work_item, args.title, MAX_PANE_COLS, "pane")
    args.tab_prefix = format_visual_label(args.work_item, args.tab_prefix, MAX_TAB_PREFIX_COLS, "tab-prefix")
    if getattr(args, "workspace_label", None):
        args.workspace_label = format_visual_label(
            args.work_item, args.workspace_label, MAX_WORKSPACE_COLS, "workspace",
        )
    owner = OWNER_RE.search(Path(args.packet).read_text(encoding="utf-8"))
    if owner and owner.group(1) in OFF_CHAIN_OWNERS and not args.off_chain_reason:
        raise DispatchError(f"packet owner {owner.group(1)} is off the delivery chain; "
                            "pass --off-chain-reason with the user decision or gate that requires it")
    if args.map_registry == "none":
        return None
    map_path = Path(args.map_registry)
    if not map_path.is_absolute() or not map_path.exists():
        raise DispatchError(f"map-registry must be an existing absolute path or none: {map_path}")
    problems = load_module("recovery_record", RECOVERY_RECORD).check(map_path)
    if problems:
        raise DispatchError("map registry fails recovery_record.py check: " + " ; ".join(problems))
    lane_id = re.search(r"^lane_id: (.+)$", map_path.read_text(encoding="utf-8"), re.M)
    return lane_id.group(1).strip() if lane_id else "Unknown"


def herdr(*args: str) -> dict:
    result = subprocess.run(["herdr", *args], text=True, capture_output=True)
    if result.returncode != 0:
        raise DispatchError(f"herdr {' '.join(args[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
    try:
        reply = json.loads(result.stdout) if result.stdout.strip() else {}
        if args[:2] == ("agent", "start") and (not isinstance(reply, dict) or not isinstance(reply.get("result"), dict)):
            raise DispatchError("inspect original start: native receipt Unknown")
        return reply
    except json.JSONDecodeError:
        if args[:2] == ("agent", "start"):
            raise DispatchError("inspect original start: native receipt Unknown")
        return {}


def find_pane(value: object) -> dict | None:
    """在任意 herdr 响应里找第一个带 pane_id 的对象。"""
    if isinstance(value, dict):
        if "pane_id" in value:
            return value
        for child in value.values():
            found = find_pane(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = find_pane(child)
            if found:
                return found
    return None


def coordinator() -> dict:
    env = {k: os.environ.get(k, "") for k in ("HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID")}
    if env["HERDR_ENV"] != "1" or not all(env.values()):
        raise DispatchError("dispatch unavailable: not inside a Herdr pane")
    pane = find_pane(herdr("pane", "current", "--current")) or {}
    actual = (pane.get("workspace_id"), pane.get("tab_id"), pane.get("pane_id"))
    expected = (env["HERDR_WORKSPACE_ID"], env["HERDR_TAB_ID"], env["HERDR_PANE_ID"])
    if actual != expected:
        raise DispatchError(f"coordinator pane readback mismatch: {actual} != {expected}")
    return {"workspace_id": actual[0], "tab_id": actual[1], "pane_id": actual[2]}


def place(coord: dict, worktree: str, prefix: str) -> dict:
    """容量管理的 worker tab：同前缀 tab 未满则在其中 split，否则新开 tab。"""
    workspace = coord["workspace_id"]
    tabs = herdr("tab", "list", "--workspace", workspace).get("result", {}).get("tabs", [])
    label_re = re.compile(rf"^{re.escape(prefix)}(-\d+)?$")
    workers = [t for t in tabs if t.get("tab_id") != coord["tab_id"] and label_re.match(str(t.get("label", "")))]
    target = next((t for t in workers if int(t.get("pane_count", 0)) < TAB_CAPACITY), None)
    if target:
        panes = [p for p in herdr("pane", "list", "--workspace", workspace).get("result", {}).get("panes", [])
                 if p.get("tab_id") == target["tab_id"]]
        if not panes:
            raise DispatchError(f"worker tab {target['tab_id']} has no panes")
        # 四角：1→右，2→左下，3→右下
        anchor = panes[0] if len(panes) < 3 else panes[1]
        direction = "right" if len(panes) == 1 else "down"
        created = herdr("pane", "split", "--pane", anchor["pane_id"], "--direction", direction,
                        "--cwd", worktree, "--no-focus")
    else:
        label = prefix if not workers else f"{prefix}-{len(workers) + 1}"
        created = herdr("tab", "create", "--workspace", workspace, "--cwd", worktree, "--label", label, "--no-focus")
    pane = find_pane(created)
    if not pane:
        raise DispatchError("placement response carries no pane_id")
    readback = find_pane(herdr("pane", "get", pane["pane_id"])) or {}
    if readback.get("workspace_id") != workspace or readback.get("pane_id") == coord["pane_id"] \
            or readback.get("tab_id") == coord["tab_id"]:
        raise DispatchError(f"placement readback mismatch: {readback}")
    return {"workspace_id": workspace, "tab_id": readback.get("tab_id"), "pane_id": readback["pane_id"]}


def write_registry(path: Path, row: dict) -> None:
    core = HERE.parents[1] / "delivery-pipeline" / "scripts"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    import lane_registry
    lane_registry.write(path, row)


def wait_working(name: str) -> bool:
    return subprocess.run(["herdr", "agent", "wait", name, "--until", "working", "--timeout", "15000"],
                          capture_output=True).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    for flag in ("evidence", "task", "output-mode", "lane", "work-item", "title",
                 "worktree", "branch", "base", "packet", "registry", "map-registry"):
        parser.add_argument(f"--{flag}", required="--recover-review" not in sys.argv)
    parser.add_argument("--config", help="可选配置路径，仅正式 review 接受替代路径")
    parser.add_argument("--off-chain-reason")
    parser.add_argument("--ticket-mode")
    parser.add_argument("--map-mode")
    parser.add_argument("--tab-prefix", required="--recover-review" not in sys.argv)
    parser.add_argument("--workspace-label", help="可选：同步重命名 Herdr workspace（左侧 space，≤20 列）")
    parser.add_argument("--review-scope")
    parser.add_argument("--required-axes", nargs="+", choices=["standards", "spec"])
    parser.add_argument("--request-id")
    parser.add_argument("--native-capabilities", help="已停用：外部自述不能授权原生派发；由 Adapter 现场采集")
    parser.add_argument("--implementation-registry", nargs="+")
    parser.add_argument("--preflight-only", action="store_true", help="whole-change 真实入口只读预检；不写 packet/Registry/pane")
    parser.add_argument("--recover-review", action="store_true", help="只读原 plan/intent/receipt，不读取配置或创建 lane")
    parser.add_argument("--review-ledger", help="本 scope 原 Review Budget 账本；恢复/后轮共用")
    parser.add_argument('--round', type=int, default=1)
    parser.add_argument('--review-head', help='本轮已验证的候选 commit')
    parser.add_argument('--previous-review-registry', help='上一轮原 Registry；后轮必需')
    parser.add_argument('--interface-changed', action='store_true')
    parser.add_argument('--dependencies-changed', action='store_true')
    args = parser.parse_args()
    if args.recover_review:
        from review_recovery import recover
        try:
            print(json.dumps(recover(args.registry, args.lane, args.request_id, args.review_ledger, args.previous_review_registry), ensure_ascii=False))
            return 0
        except (ValueError, KeyError, OSError, TypeError) as error:
            print(json.dumps({"state":"blocked", "error":str(error)}, ensure_ascii=False))
            return 1

    registry = Path(args.registry)
    row: dict = {}
    row_owned = False
    try:
        for label, value in (("worktree", args.worktree), ("packet", args.packet)):
            if not Path(value).is_absolute() or not Path(value).exists():
                raise DispatchError(f"{label} must be an existing absolute path: {value}")
        sys.path.insert(0,str(HERE.parents[1]/"delivery-pipeline/scripts"))
        import lane_registry
        existing = lane_registry.rows(registry)
        round_context = None
        if args.task == 'review' and (args.review_head or args.round != 1 or args.review_ledger):
            from review_gate import prepare_round, read_ledger
            if not args.review_head or not args.review_ledger:
                raise DispatchError('round planning requires review-head and original review-ledger')
            rounds = read_ledger(args.review_ledger)
            # 完整结果复用优先于能力/配置检查，不创建 lane、不写预算。
            prior_rows = lane_registry.rows(Path(args.previous_review_registry)) if args.previous_review_registry else existing
            if rounds:
                from review_recovery import verify_previous_round
                verify_previous_round(prior_rows, rounds)
            map_rows = lane_registry.rows(Path(args.map_registry))
            maps = [r for r in map_rows.values() if r.get('role') == 'map']
            if len(maps) != 1:
                raise DispatchError('unique Map fixed point required')
            contributions = dict(map_rows)
            for source in args.implementation_registry or []:
                contributions.update(lane_registry.rows(Path(source)))
            identities = lane_registry.collect_implementation_identities(contributions, maps[0]['base_commit'])
            round_context = prepare_round(rounds, round_no=args.round, base=args.base,
                head=args.review_head, request_id=args.request_id, implementations=identities,
                interface_changed=args.interface_changed, dependencies_changed=args.dependencies_changed)
            if round_context['action'] == 'reuse':
                print(json.dumps(round_context, ensure_ascii=False))
                return 0
            if args.required_axes != round_context['required_axes']:
                raise DispatchError('required axes must equal original Review Budget decision')
        if args.task == "review" and (args.lane in existing or any(
                r.get("review_plan", {}).get("request_id") == args.request_id for r in existing.values())):
            raise DispatchError("review lane already frozen: recover original plan/receipt; do not redispatch")
        if any(row.get("state") in {"running","awaiting_human","created"} for row in existing.values()):
            raise DispatchError(f"registry already has an active writer: {registry}")
        map_lane = preflight(args)
        mc = load_model_config()
        config = mc.cli_config_path()
        if args.config:
            requested = Path(args.config).expanduser().resolve()
            if args.task != "review" and requested != config.resolve():
                raise DispatchError("work dispatch requires the setup model-roles.json")
            config = requested
        evidence = json.loads(Path(args.evidence).expanduser().read_text())
        review = None
        if args.task == "review":
            if (args.review_scope != "whole-change" or args.output_mode != "verdict"
                    or args.map_registry == "none" or not args.required_axes or not args.request_id
                    or args.ticket_mode or args.map_mode):
                raise DispatchError("review requires Map Integration whole-change verdict, axes and request_id")
            packet_path = Path(args.packet)
            packet_text = packet_path.read_text()
            owner = re.search(r"^Owner[：:]\s*code-review[；;]\s*([^；;\n]+)[；;]\s*(.+)$", packet_text, re.M)
            if not owner or not Path(owner[1].strip()).is_absolute():
                raise DispatchError("review requires resolved code-review owner name/path/invocation label")
            owner_path = Path(owner[1].strip()).resolve()
            if not re.search(r"^name: code-review\s*$", owner_path.read_text(), re.M):
                raise DispatchError("resolved code-review owner mismatch")
            map_rows = lane_registry.rows(Path(args.map_registry))
            fixed_point = map_rows[map_lane].get("base_commit")
            if not fixed_point:
                raise DispatchError("Map Integration fixed point required")
            contribution_rows = dict(map_rows)
            for path in args.implementation_registry or []:
                contribution_rows.update(lane_registry.rows(Path(path)))
            implementations = lane_registry.collect_implementation_identities(contribution_rows, fixed_point)
            if round_context is not None:
                implementations = round_context['implementations']
            document = mc.load_document(config)
            participating = dict.fromkeys(["standards", *args.required_axes])
            pools = {axis: [mc.triple(cell), *cell["candidates"]]
                     for axis in participating
                     if (cell := document["review"]["whole-change"][axis]).get("candidates")}
            native = {}
            if pools:
                if args.native_capabilities:
                    raise DispatchError("review_capability_evidence_required: external native claims cannot authorize dispatch; omit --native-capabilities")
                from native_review_preflight import preflight_review_candidates
                collected = preflight_review_candidates(pools, args.request_id)
                native = collected["capabilities"]
                # 工件先返回内存；不在 Registry/packet 写入失败的 preflight。
                if any(x["status"] == "unknown" for pool in native.values() for x in pool):
                    raise DispatchError("review_capability_evidence_required: " + json.dumps(collected, ensure_ascii=False))
            try:
                review = mc.resolve_review_plan(document,
                    required_axes=args.required_axes, implementations=implementations,
                    evidence=evidence, native_capabilities=native, request_id=args.request_id, round_context=round_context)
            except ValueError as error:
                if pools:
                    raise DispatchError(str(error) + " native_preflight=" + json.dumps(collected, ensure_ascii=False)) from error
                raise
            if pools:
                review["native_preflight"] = collected
            calls = lane_registry.build_owner_calls(review)
            payload = {"review_plan": review, "owner_calls": calls}
            if args.preflight_only:
                print(json.dumps({"state":"preflight_ready", **payload}, ensure_ascii=False))
                return 0
            marker = "<!-- DP_REVIEW_PLAN -->"
            if marker in packet_text:
                stored = json.loads(packet_text.split(marker, 1)[1].split("```json", 1)[1].split("```", 1)[0])
                lane_registry.verify_review_packet(review, stored)
            else:
                packet_path.write_text(packet_text + "\n" + marker + "\n```json\n" +
                    json.dumps(payload, ensure_ascii=False) + "\n```\n" +
                    "resolved code-review owner：逐轴按 owner_calls 的 requested 调用 required axes；"
                    "不得重新读取配置选模型。每轴保留独立 findings/verdict 和原生 readback，"
                    "无 readback 写 Unknown；pane 启动身份不得复制为双轴 executed。"
                    "沿用原 Review Evidence Bundle、Review Budget 和 review_gate。"
                    "同轮恢复先读原 Registry plan/intent/receipt 与已有轴结果文件，只 fan-in；"
                    "已完成轴禁止为补并行而重跑。取消尝试不计完成轮次，保留原 finding/草稿/结果。"
                    "响应丢失或启动后失败只对账原请求，不进 work replacement，不换候选。"
                    "原账本终态只读返回，不重新提交 gate。"
                    f"fan-in 必须运行 python3 {HERE / 'review_execution.py'} --ledger <原轮次账本>，"
                    "stdin 传 round、axes 完整结果、原 review_packet 与逐轴 native_readbacks；"
                    "REVIEW_BLOCKED 保留 findings、阻断本轮放行，禁止自动重跑或换候选。\n")
            actual = json.loads(packet_path.read_text().split(marker, 1)[1].split("```json", 1)[1].split("```", 1)[0])
            lane_registry.verify_review_packet(review, actual)
            plan = mc.review_start_plan(review, evidence)
        else:
            if args.preflight_only:
                raise DispatchError("preflight-only requires whole-change review")
            plan = mc.resolve_plan(mc.load_document(config), args.task,
                                   ticket_mode=args.ticket_mode, map_mode=args.map_mode,
                                   evidence=evidence, output_mode=args.output_mode)
        frozen = mc.freeze_overlay(plan)
        if plan["agent"] not in RUNTIME:
            raise DispatchError(f"Herdr transport does not support agent: {plan['agent']}")
        coord = coordinator()
        row = {
            "lane_id": args.lane, "work_item": args.work_item, "role": args.task,
            "output_mode": args.output_mode, "runtime": RUNTIME[plan["agent"]], "state": "created",
            **frozen, "worktree": args.worktree, "branch": args.branch,
            "base_commit": args.base, "map": map_lane, "contract_rev": contract_rev(),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if args.off_chain_reason:
            row["off_chain_reason"] = args.off_chain_reason.replace("\n", " ")
        if review is not None:
            row['review_plan'] = review
            lane_registry.reserve_review(registry, row)
        else:
            write_registry(registry, row)
        row_owned = True
        if review is not None:
            lane_registry.freeze_review_plan(registry, args.lane, review, args.request_id)
            persisted = lane_registry.load_review_plan(registry, args.lane, args.request_id)
            lane_registry.verify_review_packet(persisted, actual)
        # 同批并发 dispatch 时串行化落位，避免同时 split 同一 tab 或重复开 X。
        lock_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"dp-dispatch-{coord['workspace_id'].replace(':', '_')}.lock"
        with open(lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.workspace_label:
                herdr("workspace", "rename", coord["workspace_id"], args.workspace_label)
            pane = place(coord, args.worktree, args.tab_prefix)
        name = agent_name(args.lane)
        row["herdr"] = {**pane, "agent_name": name, "coordinator_pane_id": coord["pane_id"]}
        write_registry(registry, row)
        argv = mc.startup_request(plan, worker_name=name, pane_id=pane["pane_id"])
        if review is not None:
            row["herdr"].update(startup_state="launching", request_id=args.request_id, argv=argv)
            write_registry(registry, row)
        reply = herdr(*argv[1:])
        if review is not None:
            row["herdr"].update(startup_state="completed", receipt={"request_id":args.request_id, "native":reply})
            write_registry(registry, row)
        herdr("pane", "rename", pane["pane_id"], args.title)
        prompt = f"完整读取 {args.packet} 并严格按其中全部指令执行。"
        herdr("agent", "prompt", name, prompt)
        if not wait_working(name):
            if review is not None:
                raise DispatchError("inspect original review: working Unknown; preserve pane/packet, do not re-prompt")
            herdr("agent", "prompt", name, prompt)
            if not wait_working(name):
                subprocess.run(["herdr", "pane", "close", pane["pane_id"]], capture_output=True)
                raise DispatchError("agent did not reach working after one re-prompt")
        log = open(f"/tmp/lane-watch-{name}.log", "ab")
        watch_env = dict(os.environ)
        if args.map_registry != "none" and (Path(args.map_registry).parent / "driver.json").exists():
            watch_env["LANE_WATCH_MAP_DIR"] = str(Path(args.map_registry).parent)  # ADR-0026：终态先交 Driver
        subprocess.Popen([str(WATCHER), pane["pane_id"], coord["pane_id"], args.lane, args.title],
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True, env=watch_env)
        row["state"] = "running"
        row["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_registry(registry, row)
    except (DispatchError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        if row_owned:
            row["state"] = "setup_blocked"
            row["blocker"] = str(error).replace("\n", " ")
            try:
                write_registry(registry, row)
            except (DispatchError, OSError):
                pass
        print(json.dumps({"lane_id": args.lane, "state": "setup_blocked", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"lane_id": args.lane, "state": "running", **row["herdr"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

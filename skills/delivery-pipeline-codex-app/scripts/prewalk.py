#!/usr/bin/env python3
"""App 分派边界：读取 JSON，输出可持久化 overlay 与工具参数；不发送请求。"""

import json
import runpy
import stat
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/models.json"
EXECUTION_TARGET_MARKER = "app.execution_target:"
EXECUTION_TARGET_KEYS = {"model", "effort", "source", "scope"}
SKILLS_ROOT = Path(__file__).resolve().parents[2]
CORE_SCRIPTS = SKILLS_ROOT / "delivery-pipeline/scripts"
MODEL_CONFIG = runpy.run_path(
    str(SKILLS_ROOT / "delivery-pipeline-setup/scripts/model_config.py")
)
CHECKPOINT = runpy.run_path(str(CORE_SCRIPTS / "checkpoint.py"))
check_implementation = runpy.run_path(str(CORE_SCRIPTS / "implementation_gate.py"))[
    "check"
]


def pair(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"model", "effort"}
        or any(
            not isinstance(v, str) or not v.strip() or v.strip().lower() == "unknown"
            for v in value.values()
        )
    ):
        raise ValueError("模型配置必须包含有效 model/effort")
    return dict(value)


def entry(value):
    """version 4 work/review 项：剥除 agent 后返回 model/effort 对。"""
    if not isinstance(value, dict) or "agent" not in value:
        raise ValueError("任务类型配置必须包含 agent")
    return pair({k: value.get(k) for k in ("model", "effort")})


def models(data):
    path = Path(data.get("config_path", CONFIG_PATH)).expanduser()
    if not path.is_absolute():
        raise ValueError("config_path 必须是绝对路径")
    path = path.resolve(strict=True)
    config = json.loads(path.read_text())
    errors = MODEL_CONFIG["validate_document"](config, "app")
    if errors:
        raise ValueError("非法 App 模型配置: " + "; ".join(errors))
    return {"config_path": str(path), "config": config}


def select(value, override, source, scope):
    target = {**pair(value), "source": source, "scope": scope}
    if override is not None:
        if (
            not isinstance(override, dict)
            or not {"source", "scope"} <= set(override)
            or not set(override) <= {"model", "effort", "source", "scope"}
            or not set(override) & {"model", "effort"}
            or override["scope"] != scope
            or not isinstance(override["source"], str)
            or not override["source"].strip()
            or override["source"].strip().lower() == "unknown"
        ):
            raise ValueError("非法模型覆盖 source/scope/model/effort")
        target.update(override)
        pair({k: target[k] for k in ("model", "effort")})
    return target


def model(data):
    loaded = models(data)
    work = data["work"]
    value = entry(loaded["config"]["work"][work])
    target = select(
        value, data.get("model_override"), loaded["config_path"] + "#work." + work, work
    )
    return {
        "config_path": loaded["config_path"],
        "target": target,
        "request": {"model": target["model"], "thinking": target["effort"]},
    }


def git(root, *args):
    return CHECKPOINT["_run_git"](Path(root), *args)


def snapshot(root, required_ignored=()):
    return CHECKPOINT["snapshot_worktree"](root, required_ignored=required_ignored)


def checkpoint(data):
    required_ignored = data.get("required_ignored", [])
    if not isinstance(required_ignored, list) or any(
        not isinstance(path, str) for path in required_ignored
    ):
        raise ValueError("required_ignored 必须是路径列表")
    root = data["worktree"]
    payload = dict(data["payload"])
    phase_plan = payload.get("phase_plan")
    if not isinstance(phase_plan, dict) or not isinstance(
        phase_plan.get("execution"), dict
    ):
        raise ValueError("checkpoint 缺少 phase_plan.execution")
    target = validate_execution_target(
        payload.pop(
            "execution_target",
            {
                "model": phase_plan["execution"].get("model"),
                "effort": phase_plan["execution"].get("effort"),
                "source": payload.get("mode_source"),
                "scope": "execution",
            },
        )
    )
    if {key: target[key] for key in ("model", "effort")} != phase_plan["execution"]:
        raise ValueError("execution_target 与 phase_plan.execution 不一致")
    evidence = payload.get("evidence")
    if (
        not isinstance(evidence, list)
        or any(not isinstance(item, str) for item in evidence)
        or any(item.startswith(EXECUTION_TARGET_MARKER) for item in evidence)
    ):
        raise ValueError("evidence 缺失或已包含 execution_target marker")
    payload["evidence"] = [*evidence, execution_target_marker(target)]
    document = CHECKPOINT["build_checkpoint"](payload, snapshot(root, required_ignored))
    CHECKPOINT["write_checkpoint"](data["checkpoint_path"], document, worktree=root)
    return CHECKPOINT["read_checkpoint"](
        data["checkpoint_path"],
        worktree=root,
        expected_lane=document["lane_id"],
        expected_base=document["base_commit"],
    )


def resolve(data):
    lane = data.get("existing_lane")
    if lane is not None:
        return {"action": "recover", "overlay": lane, "request": None}
    if data.get("output_mode") != "commit" or data.get("task") not in (
        "design",
        "frontend",
        "backend",
    ):
        return {"action": "not-applicable", "request": None}
    check_implementation(data)
    loaded = models(data)
    config = loaded["config"]
    mode, source = config["default_mode"], "default"
    for key in ("ticket_mode", "map_mode"):
        if data.get(key) is not None:
            mode, source = data[key], key.removesuffix("_mode")
            break
    if mode not in config["modes"]:
        raise ValueError("非法 development_mode")
    selected = config["modes"][mode]
    direct = selected["kind"] == "direct"
    overrides = data.get("model_overrides", {})
    if not isinstance(overrides, dict) or not set(overrides) <= {
        "starting",
        "execution",
        "direct",
    }:
        raise ValueError("非法阶段 model_overrides")
    phase_plan = selected["agents"]["codex-app"]
    targets = {
        phase: select(
            value,
            overrides.get(phase),
            loaded["config_path"] + "#modes." + mode + "." + phase,
            phase,
        )
        for phase, value in phase_plan.items()
    }
    plan = {
        phase: {k: value[k] for k in ("model", "effort")}
        for phase, value in targets.items()
    }
    target = targets["direct" if direct else "starting"]
    model, effort = target["model"], target["effort"]
    return {
        "action": "create",
        "overlay": {
            "development_mode": mode,
            "mode_source": source,
            "config_path": loaded["config_path"],
            "execution_kind": selected["kind"],
            "phase_plan": plan,
            "phase_targets": targets,
            "execution_target": targets["execution"],
            "execution_phase": "executing" if direct else "starting",
            "checkpoint": None,
            "checkpoint_format": "canonical-v1",
            "checkpoint_sha256": None,
            "requested_model": model,
            "requested_effort": effort,
            "model": "Unknown",
            "effort": "Unknown",
            "model_evidence": "Unknown",
        },
        "request": {"model": model, "thinking": effort},
    }


def review(data):
    """校验 coordinator 从 resolved owner 取得的两轴结论。"""
    scope, owner = data.get("review_scope"), data.get("owner")
    if scope not in ("implementation", "whole-change"):
        raise ValueError("缺失或非法 review_scope")
    if (
        not isinstance(owner, dict)
        or set(owner) != {"name", "skill_path", "invocation_label"}
        or any(
            not isinstance(value, str) or not value.strip() for value in owner.values()
        )
        or not Path(owner["skill_path"]).is_absolute()
    ):
        raise ValueError("缺失 resolved code-review owner triple")
    axes = data.get("reviews")
    if not isinstance(axes, dict) or set(axes) != {"standards", "spec"}:
        raise ValueError("缺少独立两轴结论")
    identities = set()
    for axis in axes.values():
        for key in ("reviewer_id", "source", "verdict_text"):
            if (
                not isinstance(axis.get(key), str)
                or not axis[key].strip()
                or axis[key] == "Unknown"
            ):
                raise ValueError("缺失 reviewer 宿主证据: " + key)
        identities.add(axis["reviewer_id"])
        if (
            axis.get("status") != "completed"
            or axis.get("verdict") != "pass"
            or type(axis.get("blocking_findings")) is not int
            or axis["blocking_findings"] != 0
            or axis.get("review_scope") != scope
        ):
            raise ValueError("独立审查未通过；中断或自评不能放行")
        if any(axis.get(key) != data[key] for key in ("base_commit", "head_commit")):
            raise ValueError("Review 代码版本已过期")
    if len(identities) != 2 or data["worker_id"] in identities:
        raise ValueError("执行者与两轴 reviewer 必须独立")
    current = snapshot(data["worktree"])
    if current["dirty"] or current["head"] != data["head_commit"]:
        raise ValueError("待集成代码已变化")
    git(
        data["worktree"],
        "merge-base",
        "--is-ancestor",
        data["base_commit"],
        data["head_commit"],
    )
    return {
        "action": "review-passed",
        "review_scope": scope,
        "owner": owner,
        "head_commit": data["head_commit"],
    }


def coordinator(data):
    recommendation = model({**data, "work": "coordinator"})["target"]
    if not all(
        isinstance(data.get(k), str) and data[k].strip() and data[k] != "Unknown"
        for k in ("model", "effort", "source")
    ):
        return {
            "action": "Unknown",
            "model": "Unknown",
            "effort": "Unknown",
            "source": "Unknown",
            "recommendation": recommendation,
        }
    return {
        "action": "verified",
        "model": data["model"],
        "effort": data["effort"],
        "source": data["source"],
        "recommendation": recommendation,
    }


def validate_execution_target(value):
    if not isinstance(value, dict) or set(value) != EXECUTION_TARGET_KEYS:
        raise ValueError("execution_target 必须完整包含 model/effort/source/scope")
    for key, item in value.items():
        if (
            not isinstance(item, str)
            or not item.strip()
            or item.strip().lower() == "unknown"
        ):
            raise ValueError("execution_target 缺失有效 " + key)
    if value["scope"] != "execution":
        raise ValueError("execution_target.scope 必须是 execution")
    return {key: value[key] for key in ("model", "effort", "source", "scope")}


def execution_target_marker(target):
    return EXECUTION_TARGET_MARKER + json.dumps(
        validate_execution_target(target),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def checkpoint_execution_target(checkpoint):
    evidence = checkpoint.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("checkpoint 缺少 execution_target evidence")
    markers = [
        item[len(EXECUTION_TARGET_MARKER) :]
        for item in evidence
        if isinstance(item, str) and item.startswith(EXECUTION_TARGET_MARKER)
    ]
    if len(markers) != 1:
        raise ValueError("checkpoint 缺少唯一 execution_target 记录")
    try:
        target = json.loads(markers[0])
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("checkpoint execution_target 记录不可解析") from error
    target = validate_execution_target(target)
    if {key: target[key] for key in ("model", "effort")} != checkpoint["phase_plan"][
        "execution"
    ]:
        raise ValueError("checkpoint execution_target 与 phase_plan.execution 不一致")
    return target


def execution_target(data, lane, default_source=None):
    frozen = lane.get("execution_target")
    if frozen is not None:
        baseline = validate_execution_target(frozen)
        if lane.get("phase_plan") and pair(lane["phase_plan"]["execution"]) != {
            k: baseline[k] for k in ("model", "effort")
        }:
            raise ValueError("lane 冻结 phase_plan 与 execution_target 不一致")
    else:
        plan = lane.get("phase_plan") or data["checkpoint"].get("phase_plan")
        value = (
            pair(plan["execution"])
            if plan is not None
            else models(data)["config"]["legacy_execution"][lane["development_mode"]]
        )
        baseline = {
            **value,
            "source": default_source or lane.get("mode_source"),
            "scope": "execution",
        }
    return validate_execution_target(
        select(
            {k: baseline[k] for k in ("model", "effort")},
            data.get("execution_override"),
            baseline["source"],
            "execution",
        )
    )


def prepare(data):
    lane = data["lane"]
    if lane.get("execution_phase") in ("switching", "executing"):
        return {"action": "readback", "overlay": lane, "request": None}
    if (
        lane.get("execution_phase") != "starting"
        or lane.get("execution_kind", "staged") != "staged"
    ):
        raise ValueError("当前 lane 不允许 Prewalk 接续")
    if lane.get("state") != "running":
        raise ValueError("当前 lane 非 running")
    observation, checkpoint = data["observation"], data["checkpoint"]
    if not lane.get("lane_id"):
        raise ValueError("检查点坐标不匹配: lane_id")
    for key in ("thread_id", "host_id"):
        if lane[key] != observation.get(key):
            raise ValueError("宿主观测坐标不匹配: " + key)
    if not observation.get("source"):
        raise ValueError("缺失起步轮宿主证据")
    if observation.get("status") == "active":
        return {
            "action": "wait-for-stop",
            "overlay": lane,
            "request": None,
            "target": {"threadId": lane["thread_id"], "hostId": lane["host_id"]},
        }
    if observation.get("status") != "idle":
        raise ValueError("缺失起步轮停止的宿主证据")
    check_implementation(data)
    path = Path(data["checkpoint_path"])
    root = Path(lane["worktree"]).resolve()
    legacy = data.get("legacy_checkpoint", False)
    if type(legacy) is not bool:
        raise ValueError("legacy_checkpoint 必须是显式布尔值")
    if legacy:
        if (
            lane.get("development_mode") not in ("astra-luna", "astra-sol")
            or lane.get("checkpoint_format") != "legacy-app-v0"
            or not isinstance(lane.get("checkpoint"), str)
            or Path(lane["checkpoint"]).resolve(strict=False)
            != path.resolve(strict=False)
        ):
            raise ValueError(
                "legacy 恢复缺少 registry 持久来源或 checkpoint path 不匹配"
            )
        if "checkpoint_version" in checkpoint:
            raise ValueError("canonical checkpoint 不允许走 legacy 恢复")
        if (
            not path.is_absolute()
            or not path.is_file()
            or json.loads(path.read_text()) != checkpoint
        ):
            raise ValueError("legacy 检查点持久 readback 不匹配")
        if path.resolve().is_relative_to(root):
            raise ValueError("检查点必须位于 repo 外")
        for key in ("lane_id", "thread_id", "host_id"):
            if not lane.get(key) or lane[key] != checkpoint.get(key):
                raise ValueError("检查点坐标不匹配: " + key)
        if (
            not lane.get("base_commit")
            or checkpoint.get("base_commit") != lane["base_commit"]
        ):
            raise ValueError("检查点 base 不匹配")
        git(root, "merge-base", "--is-ancestor", lane["base_commit"], "HEAD")
        canonical = snapshot(root)
        dirty = {}
        for name, item in canonical["dirty"].items():
            if item["deleted"]:
                dirty[name] = {"deleted": True}
            else:
                kind = stat.S_IFLNK if item["kind"] == "symlink" else stat.S_IFREG
                dirty[name] = {
                    "mode": kind | item["mode"],
                    "sha256": item["content_sha256"],
                }
        current = {
            key: canonical[key]
            for key in ("worktree", "head", "branch", "common_dir", "index_sha256")
        }
        current["dirty"] = dirty
        current["ignored"] = {"delivery_input": canonical["ignored"]["delivery_input"]}
        if checkpoint.get("snapshot", {}).get("ignored") != {"delivery_input": "none"}:
            raise ValueError("legacy ignored 交付输入未确认无关")
        if current != checkpoint.get("snapshot"):
            raise ValueError("检查点已过期")
        first_edit = checkpoint.get("first_edit")
        if (
            not isinstance(first_edit, list)
            or not first_edit
            or any(
                not isinstance(name, str) or name not in current["dirty"]
                for name in first_edit
            )
        ):
            raise ValueError("缺少可核对的首处实现路径")
        decision = checkpoint.get("decision")
        if (
            not isinstance(decision, dict)
            or set(decision) != {"critical_design_unknown", "reason"}
            or type(decision["critical_design_unknown"]) is not bool
            or not isinstance(decision["reason"], str)
            or not decision["reason"].strip()
            or CHECKPOINT["_is_unknown"](decision["reason"])
        ):
            raise ValueError("legacy decision 缺失、Unknown 或形状不支持")
        if decision["critical_design_unknown"]:
            raise ValueError("legacy 关键设计 Unknown")
        for key in ("todo", "checks", "evidence"):
            if not checkpoint.get(key):
                raise ValueError("检查点缺失: " + key)
        checkpoint_format, checkpoint_hash = "legacy-app-v0", "Unknown"
    else:
        if lane.get("checkpoint_format") != "canonical-v1":
            raise ValueError("canonical lane 缺少 checkpoint format")
        if (
            "phase_plan" not in lane
            and lane.get("development_mode") in ("astra-luna", "astra-sol")
            and (
                not isinstance(lane.get("checkpoint"), str)
                or Path(lane["checkpoint"]).resolve(strict=False)
                != path.resolve(strict=False)
            )
        ):
            raise ValueError("旧 astra lane 缺少 registry 持久恢复证据")
        persisted = CHECKPOINT["read_checkpoint"](
            path,
            worktree=root,
            expected_lane=lane["lane_id"],
            expected_base=lane.get("base_commit"),
        )
        if persisted != checkpoint:
            raise ValueError("检查点持久 readback 不匹配")
        expected = {
            "runtime": "codex-thread",
            "session_id": lane.get("thread_id"),
            "coordinator_thread_id": lane.get("coordinator_thread_id"),
            "coordinator_host_id": lane.get("coordinator_host_id"),
            "execution_worktree": str(root),
            "phase": "starting",
            "development_mode": "staged",
        }
        if any(checkpoint.get(key) != value for key, value in expected.items()):
            raise ValueError("canonical 检查点 App 坐标或阶段不匹配")
        evaluation = CHECKPOINT["evaluate_signal"](
            checkpoint,
            f"WORKER_STOPPED {lane['lane_id']} {path}",
            {
                "runtime": "codex-thread",
                "session_id": lane.get("thread_id"),
                "coordinator_thread_id": lane.get("coordinator_thread_id"),
                "coordinator_host_id": lane.get("coordinator_host_id"),
                "status": "stopped",
                "writer_active": False,
                "stop_evidence": True,
                "ready_seen": True,
            },
        )
        if evaluation["action"] != "ready-for-coordinator":
            raise ValueError(
                "canonical checkpoint 阻塞: "
                + evaluation.get("reason", evaluation["action"])
            )
        checkpoint_format = "canonical-v1"
        checkpoint_hash = checkpoint[CHECKPOINT["FINGERPRINT_FIELD"]]
    persisted_target = None if legacy else checkpoint_execution_target(checkpoint)
    target = execution_target(
        data,
        lane,
        default_source=None if persisted_target is None else persisted_target["source"],
    )
    model, effort = target["model"], target["effort"]
    if not legacy and target != persisted_target:
        raise ValueError("canonical 检查点与完整 resolved execution target 不匹配")
    if not legacy and lane.get("phase_plan"):
        for phase in ("starting", "direct"):
            if lane["phase_plan"][phase] != checkpoint["phase_plan"][phase]:
                raise ValueError("checkpoint 与 lane 冻结 phase_plan 不一致")
    overlay = {
        **lane,
        "execution_phase": "switching",
        "checkpoint": str(path),
        "checkpoint_format": checkpoint_format,
        "checkpoint_sha256": checkpoint_hash,
        "execution_target": target,
        "previous_model_evidence": {
            k: lane.get(k, "Unknown")
            for k in (
                "requested_model",
                "requested_effort",
                "model",
                "effort",
                "model_evidence",
            )
        },
        "requested_model": model,
        "requested_effort": effort,
        "model": "Unknown",
        "effort": "Unknown",
        "model_evidence": "Unknown",
    }
    if not legacy:
        overlay["phase_plan"] = checkpoint["phase_plan"]
        if "phase_targets" in lane:
            overlay["phase_targets"] = {**lane["phase_targets"], "execution": target}
    return {
        "action": "persist-before-send",
        "overlay": overlay,
        "request": {
            "threadId": lane["thread_id"],
            "hostId": lane["host_id"],
            "model": model,
            "thinking": effort,
            "prompt": "你是本任务 Execution Worktree 内的实现 worker；直接继续实现，不承担协调器监控。"
            "起步轮限制已结束。沿本任务历史及原 packet/owner/权限接续；读取检查点 "
            + str(path)
            + "，完成剩余实现、测试与原 owner 的交付步骤。"
            "执行者约束：不得取消或中断正式 reviewer，不得催促其直接通过；"
            "不得用自评、测试通过或已修复声明替代独立 verdict，不得自行豁免验收。"
            "审查超时、中断或缺结论时保留现场，可保存候选 commit，"
            "但必须按 blocked 回传‘实现已保存、审查待完成’，不得报告 completed。"
            "由 coordinator 管理审查、核验原始结果并决定放行；"
            "执行者不得自行集成、关闭票或更改审查范围来规避 finding。"
            "正式 Review 由 coordinator 按 resolved owner 和 review_scope 管理；"
            "你只保存候选 commit 与修复说明，不得启动、取消、改写或自评替代两轴 verdict。",
        },
    }


def subagent(data):
    """父会话先读宿主活跃列表；这个入口不创建或锁定子代理。"""
    work, count = data["work"], data["active_count"]
    if work not in (
        "assistance",
        "second-opinion",
        "review",
        "ticket-sizing",
        "testing",
        "integration",
    ):
        raise ValueError("非法内部工作类型")
    if (
        type(count) is not int
        or count < 0
        or not data.get("source")
        or type(data.get("read_only")) is not bool
    ):
        raise ValueError("缺少有效的宿主并发/父权限观测")
    slots = 2 if work == "review" else 1
    if work in ("testing", "integration") and count != 0:
        raise ValueError(work + " 需要独占父会话的子代理容量")
    if work == "integration" and data["read_only"]:
        raise ValueError("integration 需要父任务写权限")
    result = {
        "request": None,
        "read_only": data["read_only"] or work not in ("assistance", "integration"),
        "required_slots": slots,
        "limit": 3,
    }
    if count + slots > 3:
        return {**result, "action": "wait"}
    if work == "review":
        loaded = models(data)
        scope = data["review_scope"]
        axes = loaded["config"]["review"][scope]
        overrides = data.get("review_overrides", {})
        if not isinstance(overrides, dict) or not set(overrides) <= set(axes):
            raise ValueError("非法 review_overrides")
        targets = {
            axis: select(
                entry(value),
                overrides.get(axis),
                loaded["config_path"] + "#review." + scope + "." + axis,
                scope + "." + axis,
            )
            for axis, value in axes.items()
        }
        return {
            **result,
            "action": "invoke-owner",
            "review_scope": scope,
            "review_models": targets,
            "config_path": loaded["config_path"],
        }
    selected = model(data)
    target = selected["target"]
    return {
        **result,
        "action": "spawn",
        "target": target,
        "config_path": selected["config_path"],
        "request": {
            "model": target["model"],
            "reasoning_effort": target["effort"],
            "fork_turns": "none",
        },
    }


def main():
    try:
        data = json.load(sys.stdin)
        command = sys.argv[1]
        if command == "models":
            result = models(data)
        elif command == "model":
            result = model(data)
        elif command == "snapshot":
            result = snapshot(data["worktree"], data.get("required_ignored", []))
        elif command == "coordinator":
            result = coordinator(data)
        elif command == "checkpoint":
            result = checkpoint(data)
        elif command == "review":
            result = review(data)
        elif command == "resolve":
            result = resolve(data)
        elif command == "subagent":
            result = subagent(data)
        elif command == "prepare":
            result = prepare(data)
        else:
            raise ValueError("未知命令")
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, IndexError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

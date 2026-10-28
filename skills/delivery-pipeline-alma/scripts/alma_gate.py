#!/usr/bin/env python3
"""Alma 分派边界（ADR-0015）：读取 stdin JSON，输出可持久化 overlay 与 Task 参数；不发起 Task。

命令：models | model | coordinator | resolve | subagent | review | snapshot | isolation | self-test
"""

import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/models.json"
SKILLS_ROOT = Path(__file__).resolve().parents[2]
CORE_SCRIPTS = SKILLS_ROOT / "delivery-pipeline/scripts"
MODEL_CONFIG = runpy.run_path(
    str(SKILLS_ROOT / "delivery-pipeline-setup/scripts/model_config.py")
)
CHECKPOINT = runpy.run_path(str(CORE_SCRIPTS / "checkpoint.py"))
check_implementation = runpy.run_path(str(CORE_SCRIPTS / "implementation_gate.py"))[
    "check"
]
INTERNAL_WORK = (
    "assistance",
    "second-opinion",
    "review",
    "ticket-sizing",
    "testing",
    "integration",
)


def known(value):
    return isinstance(value, str) and value.strip() and value.strip() != "Unknown"


def pair(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"model", "effort"}
        or not all(known(v) for v in value.values())
    ):
        raise ValueError("模型配置必须包含有效 model/effort")
    return dict(value)


def entry(value):
    if not isinstance(value, dict) or value.get("agent") != "alma":
        raise ValueError("Alma 配置项的 agent 必须为 alma")
    return pair({k: value.get(k) for k in ("model", "effort")})


def task_request(target):
    """Task 只接受 model；effort 只记录请求值，不进入请求（ADR-0015）。"""
    return {"model": target["model"]}


def models(data):
    path = Path(data.get("config_path", CONFIG_PATH)).expanduser()
    if not path.is_absolute():
        raise ValueError("config_path 必须是绝对路径")
    path = path.resolve(strict=True)
    config = json.loads(path.read_text())
    errors = MODEL_CONFIG["validate_document"](config, "alma")
    if errors:
        raise ValueError("非法 Alma 模型配置: " + "; ".join(errors))
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
            or not known(override["source"])
        ):
            raise ValueError("非法模型覆盖 source/scope/model/effort")
        target.update(override)
        pair({k: target[k] for k in ("model", "effort")})
    return target


def model(data):
    loaded = models(data)
    work = data["work"]
    target = select(
        entry(loaded["config"]["work"][work]),
        data.get("model_override"),
        loaded["config_path"] + "#work." + work,
        work,
    )
    return {
        "config_path": loaded["config_path"],
        "target": target,
        "request": task_request(target),
        "requested_effort": target["effort"],
    }


def coordinator(data):
    """coordinator 模型由宿主在调用前决定；这里只记录观测与推荐值。"""
    recommendation = model({**data, "work": "coordinator"})["target"]
    if not all(known(data.get(k)) for k in ("model", "source")):
        return {
            "action": "Unknown",
            "model": "Unknown",
            "effort": "Unknown",
            "source": "Unknown",
            "recommendation": recommendation,
        }
    return {
        "action": "observed",
        "model": data["model"],
        "effort": "Unknown",
        "source": data["source"],
        "recommendation": recommendation,
    }


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
    if selected["kind"] != "direct":
        raise ValueError("Alma 只支持 direct mode（ADR-0015）")
    override = (data.get("model_overrides") or {}).get("direct")
    target = select(
        selected["agents"]["alma"]["direct"],
        override,
        loaded["config_path"] + "#modes." + mode + ".direct",
        "direct",
    )
    return {
        "action": "create",
        "overlay": {
            "development_mode": mode,
            "mode_source": source,
            "config_path": loaded["config_path"],
            "execution_kind": "direct",
            "direct_target": target,
            "requested_model": target["model"],
            "requested_effort": target["effort"],
            "model": "Unknown",
            "effort": "Unknown",
            "model_evidence": "Unknown",
        },
        "request": task_request(target),
    }


def subagent(data):
    """内部 gate 子代理参数。Alma Task 并发上限 Unknown，因此只做写权限与独占约束。"""
    work, count = data["work"], data["active_count"]
    if work not in INTERNAL_WORK:
        raise ValueError("非法内部工作类型")
    if type(count) is not int or count < 0 or type(data.get("read_only")) is not bool:
        raise ValueError("缺少有效的 active_count/read_only 观测")
    if work in ("testing", "integration") and count != 0:
        return {"action": "wait", "reason": work + " 需要没有其他活跃子代理"}
    if work == "integration" and data["read_only"]:
        raise ValueError("integration 需要父任务写权限")
    read_only = data["read_only"] or work not in ("assistance", "integration")
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
            "action": "invoke-owner",
            "read_only": True,
            "review_scope": scope,
            "review_models": targets,
            "requests": {axis: task_request(t) for axis, t in targets.items()},
            "config_path": loaded["config_path"],
        }
    selected = model(data)
    return {
        "action": "spawn",
        "read_only": read_only,
        "target": selected["target"],
        "config_path": selected["config_path"],
        "request": {**selected["request"], "resume": None},
    }


def snapshot(root):
    return CHECKPOINT["snapshot_worktree"](root)


def review(data):
    """校验 coordinator 直接读回的两轴结论；不验证宿主来源真实性。"""
    scope, owner = data.get("review_scope"), data.get("owner")
    if scope not in ("implementation", "whole-change"):
        raise ValueError("缺失或非法 review_scope")
    if (
        not isinstance(owner, dict)
        or set(owner) != {"name", "skill_path", "invocation_label"}
        or not all(known(v) for v in owner.values())
        or not Path(owner["skill_path"]).is_absolute()
    ):
        raise ValueError("缺失 resolved code-review owner triple")
    axes = data.get("reviews")
    if not isinstance(axes, dict) or set(axes) != {"standards", "spec"}:
        raise ValueError("缺少独立两轴结论")
    identities = set()
    for axis in axes.values():
        for key in ("reviewer_id", "source", "verdict_text"):
            if not known(axis.get(key)):
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
    CHECKPOINT["_run_git"](
        Path(data["worktree"]),
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


def isolation(data):
    """Task 无 cwd 参数：fan-in 前核对派发前登记的受保护 worktree 未被 worker 改动。"""
    guarded = data.get("guarded")
    if not isinstance(guarded, list) or not guarded:
        raise ValueError("guarded 必须是非空列表")
    violations = []
    for item in guarded:
        if not isinstance(item, dict) or not {"worktree", "head", "dirty"} <= set(item):
            raise ValueError("guarded 项必须包含 worktree/head/dirty")
        current = snapshot(item["worktree"])
        if current["head"] != item["head"] or current["dirty"] != item["dirty"]:
            violations.append(
                {
                    "worktree": item["worktree"],
                    "expected": {"head": item["head"], "dirty": item["dirty"]},
                    "actual": {"head": current["head"], "dirty": current["dirty"]},
                }
            )
    if violations:
        return {"action": "blocked", "violations": violations}
    return {"action": "isolated"}


def self_test():
    failures = []
    loaded = models({})
    if loaded["config"]["version"] != 5:
        failures.append("bundled Alma config is not version 5")
    target = model({"work": "planning"})
    if set(target["request"]) != {"model"}:
        failures.append("Task request must carry model only")
    try:
        subagent({"work": "integration", "active_count": 0, "read_only": True})
        failures.append("read-only integration was accepted")
    except ValueError:
        pass
    if subagent({"work": "testing", "active_count": 1, "read_only": True})["action"] != "wait":
        failures.append("testing with active subagents did not wait")
    if coordinator({"model": "x"})["action"] != "Unknown":
        failures.append("coordinator without source was treated as observed")
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory)
        env = CHECKPOINT["_git_env"]()

        def run(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, env=env, capture_output=True)

        run("init", "-q")
        run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base")
        base = snapshot(repo)
        guarded = [{"worktree": str(repo), "head": base["head"], "dirty": base["dirty"]}]
        if isolation({"guarded": guarded})["action"] != "isolated":
            failures.append("clean guarded worktree was flagged")
        (repo / "leak.txt").write_text("worker wrote here\n")
        if isolation({"guarded": guarded})["action"] != "blocked":
            failures.append("dirty guarded worktree was not blocked")
    return failures


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "self-test":
        failures = self_test()
        print(json.dumps({"valid": not failures, "errors": failures}, ensure_ascii=False))
        raise SystemExit(1 if failures else 0)
    handlers = {
        "models": models,
        "model": model,
        "coordinator": coordinator,
        "resolve": resolve,
        "subagent": subagent,
        "review": review,
        "snapshot": lambda d: snapshot(d["worktree"]),
        "isolation": isolation,
    }
    try:
        if command not in handlers:
            raise ValueError("未知命令")
        result = handlers[command](json.load(sys.stdin))
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, IndexError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""App 分派边界：读取 JSON，输出可持久化 overlay 与工具参数；不发送请求、不写 registry。

命令：models / model / coordinator / resolve / review / subagent。App implementation 只跑
direct（Prewalk 已退役，见 ADR-0018 修订）。
"""

import json
import runpy
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/models.json"
SKILLS_ROOT = Path(__file__).resolve().parents[2]
MODEL_CONFIG = runpy.run_path(
    str(SKILLS_ROOT / "delivery-pipeline-setup/scripts/model_config.py")
)
check_implementation = runpy.run_path(
    str(SKILLS_ROOT / "delivery-pipeline/scripts/implementation_gate.py")
)["check"]


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise ValueError("git " + " ".join(args) + " 失败: " + result.stderr.strip())
    return result.stdout.strip()


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
    """version 5 work/review 项：剥除 agent 后返回 model/effort 对。"""
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
    root = data["worktree"]
    if git(root, "status", "--porcelain") or git(root, "rev-parse", "HEAD") != data["head_commit"]:
        raise ValueError("待集成代码已变化")
    git(root, "merge-base", "--is-ancestor", data["base_commit"], data["head_commit"])
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



def subagent(data):
    """父会话先读宿主活跃列表；这个入口不创建或锁定子代理。"""
    work, count = data["work"], data["active_count"]
    if work not in (
        "assistance",
        "second-opinion",
        "review",
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



def resolve(data):
    """新 implementation 冻结 direct 计划；existing_lane 原样恢复。"""
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
    override = (data.get("model_overrides") or {}).get("direct")
    if set(data.get("model_overrides") or {}) - {"direct"}:
        raise ValueError("非法阶段 model_overrides；App 只跑 direct")
    target = select(
        config["modes"][mode]["agents"]["codex-app"]["direct"],
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
            "target": target,
            "requested_model": target["model"],
            "requested_effort": target["effort"],
            "model": "Unknown",
            "effort": "Unknown",
            "model_evidence": "Unknown",
        },
        "request": {"model": target["model"], "thinking": target["effort"]},
    }



COMMANDS = {
    "models": lambda d: models(d),
    "model": lambda d: model(d),
    "coordinator": lambda d: coordinator(d),
    "resolve": lambda d: resolve(d),
    "review": lambda d: review(d),
    "subagent": lambda d: subagent(d),
}


def main():
    try:
        data = json.load(sys.stdin)
        command = sys.argv[1]
        if command not in COMMANDS:
            raise ValueError("未知命令")
        print(json.dumps(COMMANDS[command](data), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, IndexError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

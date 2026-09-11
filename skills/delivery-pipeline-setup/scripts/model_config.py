#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "delivery-pipeline" / "scripts"
sys.path.insert(0, str(CORE_SCRIPTS))
# 以下 import 由上方 sys.path.insert 在运行时解析，静态分析不可见。
# pi-lens-ignore: reportMissingImports
import checkpoint

# pi-lens-ignore: reportMissingImports
import codex_cli_adapter

# pi-lens-ignore: reportMissingImports
from pi_adapter import build_start_command, build_tui_switch

TASK_TYPES = {
    "coordinator",
    "research",
    "prototype",
    "planning",
    "design",
    "frontend",
    "backend",
    "testing",
    "integration",
    "assistance",
    "second-opinion",
    "ticket-sizing",
}
CLI_REQUIRED_WORK = {"planning", "design", "frontend", "backend", "testing"}
APP_REQUIRED_WORK = {
    "coordinator",
    "research",
    "prototype",
    "planning",
    "testing",
    "integration",
    "assistance",
    "second-opinion",
    "ticket-sizing",
}
CLI_AGENTS = {"pi", "codex", "claude"}
LEGACY_ROLES = {"planning", "design", "frontend", "backend", "testing", "review"}
IMPLEMENTATION_TASKS = {"design", "frontend", "backend"}
KINDS = {"staged", "direct"}
STAGES = ("starting", "execution", "direct")
REVIEW_SCOPES = ("implementation", "whole-change")
REVIEW_AXES = ("standards", "spec")
LEGACY_EXECUTION_KEYS = {"astra-luna", "astra-sol"}


def _pair_errors(prefix: str, value: object) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"model", "effort"}:
        return [f"{prefix} must define exactly model and effort"]
    errors = []
    for field, candidate in value.items():
        if (
            not isinstance(candidate, str)
            or not candidate.strip()
            or candidate.strip().lower() == "unknown"
        ):
            errors.append(f"{prefix}.{field} must be a known non-empty string")
    return errors


def _entry_errors(prefix: str, value: object, agents: set[str]) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"agent", "model", "effort"}:
        return [f"{prefix} must define exactly agent, model and effort"]
    errors = _pair_errors(prefix, {k: value[k] for k in ("model", "effort")})
    if value.get("agent") not in agents:
        errors.append(f"{prefix}.agent must be one of {sorted(agents)}")
    return errors


def validate_document(document: object, transport: str = "cli") -> list[str]:
    """只检查 version 4 结构，不探测或修改用户配置。transport 为 cli 或 app。"""
    if transport not in ("cli", "app"):
        return ["transport must be cli or app"]
    agents = CLI_AGENTS if transport == "cli" else {"codex-app"}
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level value must be an object"]
    top_level = {"version", "default_mode", "work", "modes", "review"}
    allowed = top_level | ({"legacy_execution"} if transport == "app" else set())
    if not set(document) <= allowed or not top_level <= set(document):
        errors.append(
            f"top-level keys must be exactly {sorted(top_level)}"
            + (" plus optional legacy_execution" if transport == "app" else "")
        )
    if document.get("version") != 4:
        errors.append(
            "version must equal 4; older configs need model_config.py migrate"
        )
    work = document.get("work")
    if not isinstance(work, dict):
        errors.append("work must be an object")
    else:
        if not set(work) <= TASK_TYPES:
            errors.append(f"work keys must be known task types: {sorted(TASK_TYPES)}")
        required = CLI_REQUIRED_WORK if transport == "cli" else APP_REQUIRED_WORK
        if not required <= set(work):
            errors.append(
                f"{transport} config must define task types {sorted(required)}"
            )
        for task in sorted(set(work) & TASK_TYPES):
            errors.extend(_entry_errors(f"work.{task}", work[task], agents))
    modes = document.get("modes")
    if not isinstance(modes, dict) or not modes:
        errors.append("modes must be a non-empty object")
    else:
        for name, mode in sorted(modes.items()):
            prefix = f"modes.{name}"
            if not isinstance(name, str) or not name.strip():
                errors.append("mode names must be non-empty strings")
            if not isinstance(mode, dict) or set(mode) != {"kind", "agents"}:
                errors.append(f"{prefix} must define exactly kind and agents")
                continue
            if mode["kind"] not in KINDS:
                errors.append(f"{prefix}.kind must equal staged or direct")
            plans = mode["agents"]
            if not isinstance(plans, dict) or not plans:
                errors.append(f"{prefix}.agents must be a non-empty object")
                continue
            if transport == "app" and set(plans) != {"codex-app"}:
                errors.append(f"{prefix}.agents keys must be exactly ['codex-app']")
            elif not set(plans) <= agents:
                errors.append(
                    f"{prefix}.agents keys must be known agents {sorted(agents)}"
                )
            for agent, plan in plans.items():
                if not isinstance(plan, dict) or set(plan) != set(STAGES):
                    errors.append(
                        f"{prefix}.agents.{agent} must define starting, execution, direct"
                    )
                    continue
                for stage in STAGES:
                    errors.extend(
                        _pair_errors(
                            f"{prefix}.agents.{agent}.{stage}", plan.get(stage)
                        )
                    )
    default_mode = document.get("default_mode")
    if (
        not isinstance(default_mode, str)
        or not isinstance(modes, dict)
        or default_mode not in modes
    ):
        errors.append("default_mode must name an existing mode")
    elif transport == "cli" and isinstance(work, dict):
        covered = (
            modes[default_mode].get("agents", {})
            if isinstance(modes[default_mode], dict)
            else {}
        )
        for task in sorted(IMPLEMENTATION_TASKS & set(work)):
            entry = work[task]
            if (
                isinstance(entry, dict)
                and entry.get("agent") in CLI_AGENTS
                and entry["agent"] not in covered
            ):
                errors.append(
                    f"default_mode must cover the agent of work.{task}: {entry['agent']}"
                )
    review = document.get("review")
    if not isinstance(review, dict) or set(review) != set(REVIEW_SCOPES):
        errors.append(f"review must define exactly {list(REVIEW_SCOPES)}")
    else:
        for scope in REVIEW_SCOPES:
            axes = review[scope]
            if not isinstance(axes, dict) or set(axes) != set(REVIEW_AXES):
                errors.append(f"review.{scope} must define exactly {list(REVIEW_AXES)}")
                continue
            for axis in REVIEW_AXES:
                errors.extend(
                    _entry_errors(f"review.{scope}.{axis}", axes[axis], agents)
                )
    if "legacy_execution" in document:
        legacy = document["legacy_execution"]
        if not isinstance(legacy, dict) or set(legacy) != LEGACY_EXECUTION_KEYS:
            errors.append(
                f"legacy_execution keys must be exactly {sorted(LEGACY_EXECUTION_KEYS)}"
            )
        else:
            for key, value in legacy.items():
                errors.extend(_pair_errors(f"legacy_execution.{key}", value))
    return errors


def validate_path(path: Path) -> list[str]:
    try:
        return validate_document(json.loads(path.expanduser().read_text()))
    except FileNotFoundError:
        return [f"config file not found: {path.expanduser()}"]
    except json.JSONDecodeError as error:
        return [f"invalid JSON: {error}"]


def load_document(path: Path) -> dict:
    document = json.loads(path.expanduser().read_text())
    errors = validate_document(document)
    if errors:
        raise ValueError("; ".join(errors))
    return document


def _validate_legacy_cli(document: object) -> list[str]:
    """旧 version 2/3 CLI 配置的结构检查，仅作 migrate 输入。"""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level value must be an object"]
    version = document.get("version")
    if version not in (2, 3):
        return ["legacy CLI config version must equal 2 or 3"]
    roles = document.get("roles")
    if not isinstance(roles, dict) or set(roles) != LEGACY_ROLES:
        return [f"legacy roles keys must be exactly {sorted(LEGACY_ROLES)}"]
    for role in sorted(LEGACY_ROLES):
        errors.extend(_entry_errors(f"roles.{role}", roles[role], CLI_AGENTS))
    if version == 3:
        execution = document.get("execution")
        if not isinstance(execution, dict) or set(execution) != CLI_AGENTS:
            return errors + [f"execution must define exactly {sorted(CLI_AGENTS)}"]
        for agent, plan in sorted(execution.items()):
            prefix = f"execution.{agent}"
            if not isinstance(plan, dict) or set(plan) != {"default_mode", *STAGES}:
                errors.append(
                    f"{prefix} must define default_mode, starting, execution, direct"
                )
                continue
            if plan.get("default_mode") not in KINDS:
                errors.append(f"{prefix}.default_mode must equal staged or direct")
            for stage in STAGES:
                errors.extend(_pair_errors(f"{prefix}.{stage}", plan.get(stage)))
    return errors


def _validate_legacy_app(document: object) -> list[str]:
    """旧 version 1 App 配置的结构检查，仅作 migrate 输入。"""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level value must be an object"]
    if document.get("version") != 1:
        return ["legacy App config version must equal 1"]
    work = document.get("work")
    if not isinstance(work, dict) or set(work) != APP_REQUIRED_WORK:
        errors.append(
            f"legacy App work keys must be exactly {sorted(APP_REQUIRED_WORK)}"
        )
    else:
        for task, value in work.items():
            errors.extend(_pair_errors(f"work.{task}", value))
    modes = document.get("modes")
    if not isinstance(modes, dict) or not modes:
        errors.append("legacy App modes must be a non-empty object")
    else:
        for name, mode in modes.items():
            prefix = f"modes.{name}"
            if (
                not isinstance(mode, dict)
                or set(mode) != {"kind", "phase_plan"}
                or mode.get("kind") not in KINDS
            ):
                errors.append(f"{prefix} must define kind staged|direct and phase_plan")
                continue
            plan = mode["phase_plan"]
            if not isinstance(plan, dict) or set(plan) != set(STAGES):
                errors.append(
                    f"{prefix}.phase_plan must define starting, execution, direct"
                )
                continue
            for stage in STAGES:
                errors.extend(
                    _pair_errors(f"{prefix}.phase_plan.{stage}", plan.get(stage))
                )
    if document.get("default_mode") not in (modes or {}):
        errors.append("legacy App default_mode must name an existing mode")
    review = document.get("review")
    if not isinstance(review, dict) or set(review) != set(REVIEW_SCOPES):
        errors.append(f"legacy App review must define exactly {list(REVIEW_SCOPES)}")
    else:
        for scope in REVIEW_SCOPES:
            axes = review[scope]
            if not isinstance(axes, dict) or set(axes) != set(REVIEW_AXES):
                errors.append(
                    f"legacy App review.{scope} must define exactly {list(REVIEW_AXES)}"
                )
                continue
            for axis in REVIEW_AXES:
                errors.extend(_pair_errors(f"review.{scope}.{axis}", axes[axis]))
    legacy = document.get("legacy_execution")
    if not isinstance(legacy, dict) or set(legacy) != LEGACY_EXECUTION_KEYS:
        errors.append(
            f"legacy App legacy_execution keys must be exactly {sorted(LEGACY_EXECUTION_KEYS)}"
        )
    else:
        for key, value in legacy.items():
            errors.extend(_pair_errors(f"legacy_execution.{key}", value))
    return errors


def migrate_document(document: dict) -> tuple[dict, str]:
    """机械迁移旧配置到 version 4；返回 (新配置, transport)。不改已有 lane。"""
    if isinstance(document, dict) and document.get("version") == 4:
        raise ValueError("config is already version 4")
    if isinstance(document, dict) and document.get("version") in (2, 3):
        errors = _validate_legacy_cli(document)
        if errors:
            raise ValueError("; ".join(errors))
        roles = document["roles"]
        work = {task: dict(roles[task]) for task in sorted(LEGACY_ROLES - {"review"})}
        review_triple = dict(roles["review"])
        review = {
            scope: {axis: dict(review_triple) for axis in REVIEW_AXES}
            for scope in REVIEW_SCOPES
        }
        if document["version"] == 2:
            agents_plans: dict[str, dict] = {}
            for task in sorted(IMPLEMENTATION_TASKS):
                entry = roles[task]
                pair = {"model": entry["model"], "effort": entry["effort"]}
                existing = agents_plans.get(entry["agent"])
                if existing is not None and existing != pair:
                    raise ValueError(
                        f"roles on agent {entry['agent']} disagree on model/effort; "
                        "cannot build a shared direct mode, rerun delivery-pipeline-setup"
                    )
                agents_plans[entry["agent"]] = pair
            modes = {
                "migrated-direct": {
                    "kind": "direct",
                    "agents": {
                        agent: {stage: dict(pair) for stage in STAGES}
                        for agent, pair in agents_plans.items()
                    },
                }
            }
            default_mode = "migrated-direct"
        else:
            execution = document["execution"]
            modes = {
                "migrated-direct": {
                    "kind": "direct",
                    "agents": {
                        agent: {stage: dict(plan["direct"]) for stage in STAGES}
                        for agent, plan in execution.items()
                    },
                }
            }
            staged = {
                agent: plan
                for agent, plan in execution.items()
                if plan["default_mode"] == "staged"
            }
            if staged:
                modes["migrated-staged"] = {
                    "kind": "staged",
                    "agents": {
                        agent: {stage: dict(plan[stage]) for stage in STAGES}
                        for agent, plan in staged.items()
                    },
                }
            if staged and len(staged) < len(execution):
                raise ValueError(
                    "legacy default_mode differs across agents; rerun "
                    "delivery-pipeline-setup and choose one default mode explicitly"
                )
            default_mode = "migrated-staged" if staged else "migrated-direct"
        migrated = {
            "version": 4,
            "default_mode": default_mode,
            "work": work,
            "modes": modes,
            "review": review,
        }
        errors = validate_document(migrated, "cli")
        if errors:
            raise ValueError("migration produced invalid config: " + "; ".join(errors))
        return migrated, "cli"
    if isinstance(document, dict) and document.get("version") == 1:
        errors = _validate_legacy_app(document)
        if errors:
            raise ValueError("; ".join(errors))
        migrated = {
            "version": 4,
            "default_mode": document["default_mode"],
            "work": {
                task: {"agent": "codex-app", **value}
                for task, value in document["work"].items()
            },
            "modes": {
                name: {
                    "kind": mode["kind"],
                    "agents": {"codex-app": mode["phase_plan"]},
                }
                for name, mode in document["modes"].items()
            },
            "review": {
                scope: {
                    axis: {"agent": "codex-app", **value}
                    for axis, value in axes.items()
                }
                for scope, axes in document["review"].items()
            },
            "legacy_execution": document["legacy_execution"],
        }
        errors = validate_document(migrated, "app")
        if errors:
            raise ValueError("migration produced invalid config: " + "; ".join(errors))
        return migrated, "app"
    raise ValueError(
        "unrecognized config version; migrate supports CLI v2/v3 and App v1"
    )


def migrate_path(path: Path) -> dict:
    """迁移并原子写回同一路径，写后立即 readback 验证。"""
    path = path.expanduser()
    migrated, transport = migrate_document(json.loads(path.read_text()))
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temp:
            json.dump(migrated, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        os.unlink(temp_name)
        raise
    errors = validate_document(json.loads(path.read_text()), transport)
    if errors:
        raise ValueError("migration readback failed: " + "; ".join(errors))
    return {
        "migrated": str(path),
        "transport": transport,
        "default_mode": migrated["default_mode"],
    }


def capability_errors(
    agent: str, model: str, effort: str, evidence: object
) -> list[str]:
    """校验 setup/dispatch 传入的归一化实时探测证据。"""
    if not isinstance(evidence, dict):
        return ["capability evidence must be an object"]
    candidate = evidence.get(agent)
    if not isinstance(candidate, dict):
        return [f"missing capability evidence for {agent}"]
    errors: list[str] = []
    if candidate.get("binary") is not True:
        errors.append(f"{agent} binary is unavailable")
    models = candidate.get("models")
    if not isinstance(models, dict):
        return [f"{agent} capability evidence must map each model to supported efforts"]
    supported_efforts = models.get(model)
    if supported_efforts is None:
        errors.append(f"{agent} model is absent from capability evidence: {model}")
    elif not isinstance(supported_efforts, list) or effort not in supported_efforts:
        errors.append(f"{agent} effort is absent from capability evidence: {effort}")
    return errors


def plan_capability_errors(plan: dict, evidence: object) -> list[str]:
    if plan.get("mode") == "staged":
        errors: list[str] = []
        for stage in STAGES:
            pair = plan.get(stage, {})
            errors.extend(
                capability_errors(
                    plan["agent"], pair.get("model"), pair.get("effort"), evidence
                )
            )
        return errors
    return capability_errors(plan["agent"], plan["model"], plan["effort"], evidence)


def resolve_plan(
    document: dict,
    task: str,
    *,
    ticket_mode: str | None = None,
    map_mode: str | None = None,
    evidence: object = None,
    output_mode: str | None = None,
) -> dict:
    """解析并冻结一条 lane 的 mode 与模型选择，不修改配置。"""
    errors = validate_document(document)
    if errors:
        raise ValueError("; ".join(errors))
    if task not in TASK_TYPES:
        raise ValueError(f"unknown task type: {task}")
    if task not in document["work"]:
        raise ValueError(f"task type not defined in config: {task}")
    entry = document["work"][task]
    plan = {"version": 4, "task": task, **entry}
    if task not in IMPLEMENTATION_TASKS or output_mode != "commit":
        if evidence is None:
            capability = "unknown"
        else:
            errors = capability_errors(
                entry["agent"], entry["model"], entry["effort"], evidence
            )
            if errors:
                raise ValueError("; ".join(errors))
            capability = "verified"
        return {
            **plan,
            "mode": "none",
            "mode_name": None,
            "phase": "direct",
            "source": "work",
            "capability": capability,
        }

    requested = ticket_mode if ticket_mode is not None else map_mode
    source = (
        "ticket"
        if ticket_mode is not None
        else "map"
        if map_mode is not None
        else "user-config"
    )
    if requested is None:
        requested = document["default_mode"]
    mode = document["modes"].get(requested)
    if mode is None:
        raise ValueError(
            f"{source} execution mode is not a configured mode name: {requested}"
        )
    agent_plan = mode["agents"].get(entry["agent"])
    if agent_plan is None:
        raise ValueError(f"mode {requested} has no agents plan for {entry['agent']}")
    kind = mode["kind"]
    if kind == "staged":
        resolved = {
            **plan,
            "model": agent_plan["starting"]["model"],
            "effort": agent_plan["starting"]["effort"],
            "mode": "staged",
            "mode_name": requested,
            "phase": "starting",
            "source": source,
            **{stage: dict(agent_plan[stage]) for stage in STAGES},
        }
    else:
        resolved = {
            **plan,
            "mode": "direct",
            "mode_name": requested,
            "phase": "direct",
            "source": source,
            **agent_plan["direct"],
        }
    if evidence is None:
        return {**resolved, "capability": "unknown"}
    errors = plan_capability_errors(resolved, evidence)
    if errors:
        raise ValueError("; ".join(errors))
    return {**resolved, "capability": "verified"}


def freeze_overlay(plan: dict) -> dict:
    """返回 coordinator 写入 packet 与 registry 的唯一计划 overlay。"""
    if plan.get("mode") == "staged":
        for stage in STAGES:
            pair = plan.get(stage)
            if (
                not isinstance(pair, dict)
                or set(pair) != {"model", "effort"}
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or value.strip().lower() == "unknown"
                    for value in pair.values()
                )
            ):
                raise ValueError(f"staged plan missing {stage} model/effort")
        starting = plan["starting"]
        execution = plan["execution"]
        direct = plan["direct"]
    else:
        starting = execution = None
        direct = plan
    return {
        "execution_mode": plan["mode"],
        "execution_mode_name": plan.get("mode_name"),
        "execution_source": plan["source"],
        "agent": plan["agent"],
        "model": plan.get("model"),
        "effort": plan.get("effort"),
        "starting_model": starting["model"] if starting else None,
        "starting_effort": starting["effort"] if starting else None,
        "execution_model": execution["model"] if execution else None,
        "execution_effort": execution["effort"] if execution else None,
        "direct_model": direct["model"],
        "direct_effort": direct["effort"],
        "execution_phase": plan["phase"],
    }


def verify_overlay(plan: dict, overlay: object) -> dict:
    expected = freeze_overlay(plan)
    if overlay != expected:
        raise ValueError("packet/registry execution plan readback mismatch")
    return expected


def continuation_request(payload: dict) -> dict:
    """调用既有 native adapter；只生成计划，不替代 registry、lease 或发送。"""
    if isinstance(payload, dict) and payload.get("runtime") in {
        "herdr-pi-pane",
        "herdr-codex-pane",
    }:
        if set(payload) != {
            "runtime",
            "checkpoint_path",
            "request",
            "observation",
            "evidence",
        }:
            raise ValueError("continuation payload 字段不匹配")
        path = payload["checkpoint_path"]
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError("checkpoint_path 必须是绝对路径")
        document = codex_cli_adapter._load_checkpoint(path)
        if document["runtime"] != payload["runtime"]:
            raise ValueError("checkpoint runtime 不匹配")
        observation = payload["observation"]
        ready = checkpoint.evaluate_signal(
            document,
            f"WORKER_STOPPED {document['lane_id']} {document['checkpoint_path']}",
            observation,
        )
        if (
            not ready["can_continue"]
            or observation.get("coordinator_active") is not False
            or observation.get("session_resumable") is not True
        ):
            raise ValueError("原 session 停止或接续证据不足")
        request = payload["request"]
        if not isinstance(request, dict) or set(request) != {
            "request_id",
            "intent_sha256",
            "target_request",
        }:
            raise ValueError("canonical continuation request 字段不匹配")
        intent = checkpoint.build_continuation_intent(
            document, target_request=request["target_request"]
        )
        if (
            request["intent_sha256"] != intent[checkpoint.INTENT_FINGERPRINT_FIELD]
            or request["request_id"] != "request-" + request["intent_sha256"]
        ):
            raise ValueError("continuation intent 与 checkpoint 不匹配")
        agent = "pi" if payload["runtime"] == "herdr-pi-pane" else "codex"
        target = request["target_request"]
        errors = capability_errors(
            agent, target["model"], target["effort"], payload["evidence"]
        )
        if errors:
            raise ValueError("; ".join(errors))
        if agent == "codex":
            return codex_cli_adapter.resume_from_checkpoint(document, request)
        return {
            **build_tui_switch(request),
            "session_id": document["session_id"],
            "worktree": document["execution_worktree"],
            "checkpoint_sha256": document[checkpoint.FINGERPRINT_FIELD],
        }

    if not isinstance(payload, dict) or payload.get("runtime") != "herdr-claude-pane":
        raise ValueError("Claude continuation caller 只接受 herdr-claude-pane")
    adapter_path = (
        Path(__file__).resolve().parents[2]
        / "delivery-pipeline"
        / "scripts"
        / "claude_adapter.py"
    )
    spec = importlib.util.spec_from_file_location(
        "delivery_pipeline_claude_adapter", adapter_path
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"Claude adapter 不可加载: {adapter_path}")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    try:
        return adapter.resume_plan(payload)
    except (adapter.ClaudeAdapterError, OSError, TypeError) as error:
        raise ValueError(f"Claude continuation adapter rejected: {error}") from error


def startup_request(plan: dict, *, worker_name: str, pane_id: str) -> list[str]:
    """构造 Herdr 原生请求；所有 startup 都要求当前 capability evidence。"""
    if plan.get("mode") not in {"none", "direct", "staged"}:
        raise ValueError("execution plan is not runnable")
    if plan.get("capability") != "verified":
        raise ValueError("capability evidence is required before startup")
    if plan.get("mode") == "staged":
        freeze_overlay(plan)
        if (plan.get("model"), plan.get("effort")) != (
            plan["starting"]["model"],
            plan["starting"]["effort"],
        ):
            raise ValueError("staged startup 与冻结 starting 不匹配")
        if plan.get("agent") == "pi":
            return build_start_command(
                worker_name=worker_name,
                pane_id=pane_id,
                model=plan["model"],
                effort=plan["effort"],
            )
    agent, model, effort = plan.get("agent"), plan.get("model"), plan.get("effort")
    if agent not in CLI_AGENTS or not all(
        isinstance(value, str) and value.strip()
        for value in (worker_name, pane_id, model, effort)
    ):
        raise ValueError(
            "startup request requires agent, model, effort, worker_name and pane_id"
        )
    prefix = [
        "herdr",
        "agent",
        "start",
        worker_name,
        "--kind",
        agent,
        "--pane",
        pane_id,
        "--",
    ]
    if agent == "pi":
        return prefix + ["--approve", "--model", model, "--thinking", effort]
    if agent == "codex":
        return prefix + [
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-s",
            "danger-full-access",
            "-a",
            "never",
        ]
    return prefix + [
        "--model",
        model,
        "--effort",
        effort,
        "--dangerously-skip-permissions",
    ]


def valid_fixture() -> dict:
    pair = {"model": "provider/model", "effort": "high"}
    work = {task: {"agent": "pi", **pair} for task in sorted(CLI_REQUIRED_WORK)}
    return {
        "version": 4,
        "default_mode": "standard",
        "work": work,
        "modes": {
            "standard": {
                "kind": "staged",
                "agents": {
                    agent: {
                        stage: {"model": "provider/model", "effort": effort}
                        for stage, effort in (
                            ("starting", "high"),
                            ("execution", "medium"),
                            ("direct", "low"),
                        )
                    }
                    for agent in sorted(CLI_AGENTS)
                },
            }
        },
        "review": {
            scope: {axis: {"agent": "pi", **pair} for axis in REVIEW_AXES}
            for scope in REVIEW_SCOPES
        },
    }


def valid_app_fixture() -> dict:
    pair = {"agent": "codex-app", "model": "provider/model", "effort": "high"}
    return {
        "version": 4,
        "default_mode": "standard",
        "work": {task: dict(pair) for task in sorted(APP_REQUIRED_WORK)},
        "modes": {
            "standard": {
                "kind": "staged",
                "agents": {
                    "codex-app": {
                        stage: {"model": "provider/model", "effort": "effort"}
                        for stage, effort in (
                            ("starting", "high"),
                            ("execution", "medium"),
                            ("direct", "low"),
                        )
                    }
                },
            }
        },
        "review": {
            scope: {axis: dict(pair) for axis in REVIEW_AXES} for scope in REVIEW_SCOPES
        },
        "legacy_execution": {
            key: {"model": "provider/model", "effort": "high"}
            for key in sorted(LEGACY_EXECUTION_KEYS)
        },
    }


def self_test() -> list[str]:
    failures: list[str] = []
    fixture = valid_fixture()
    if validate_document(fixture):
        failures.append("valid v4 CLI fixture was rejected")
    if validate_document(valid_app_fixture(), "app"):
        failures.append("valid v4 App fixture was rejected")
    if not validate_document(valid_app_fixture()):
        failures.append("App fixture was accepted as CLI config")

    evidence = {
        agent: {"binary": True, "models": {"provider/model": ["low", "high", "medium"]}}
        for agent in sorted(CLI_AGENTS)
    }
    if (
        resolve_plan(fixture, "backend", output_mode="commit")["source"]
        != "user-config"
    ):
        failures.append("user execution mode was not selected")
    if resolve_plan(fixture, "backend")["mode"] != "none":
        failures.append("missing output mode enabled implementation phases")
    if (
        resolve_plan(fixture, "backend", map_mode="standard", output_mode="commit")[
            "mode"
        ]
        != "staged"
    ):
        failures.append("map execution mode was not selected")
    selected = resolve_plan(
        fixture,
        "backend",
        ticket_mode="standard",
        map_mode="standard",
        output_mode="commit",
    )
    if (
        selected["mode"] != "staged"
        or selected["source"] != "ticket"
        or selected["mode_name"] != "standard"
    ):
        failures.append("ticket execution mode did not override map mode")
    verified = resolve_plan(
        fixture,
        "backend",
        ticket_mode="standard",
        evidence=evidence,
        output_mode="commit",
    )
    if verified["capability"] != "verified":
        failures.append("live capability evidence was not recorded")
    if resolve_plan(fixture, "design", output_mode="artifact")["mode"] != "none":
        failures.append("design artifact lane was assigned implementation phases")
    try:
        resolve_plan(fixture, "backend", ticket_mode="staged", output_mode="commit")
    except ValueError:
        pass
    else:
        failures.append("legacy staged/direct literal was accepted as a mode name")
    case = json.loads(json.dumps(fixture))
    case["work"]["backend"]["agent"] = "codex"
    case["modes"]["standard"]["agents"] = {
        "pi": case["modes"]["standard"]["agents"]["pi"]
    }
    try:
        resolve_plan(case, "backend", output_mode="commit")
    except ValueError:
        pass
    else:
        failures.append("mode missing the lane agent plan was accepted")

    overlay = freeze_overlay(verified)
    if verify_overlay(verified, json.loads(json.dumps(overlay))) != overlay:
        failures.append("frozen packet/registry overlay failed readback")
    with tempfile.TemporaryDirectory() as directory:
        config_path = Path(directory) / "model-roles.json"
        packet_path = Path(directory) / "packet-overlay.json"
        registry_path = Path(directory) / "registry-overlay.json"
        config_path.write_text(json.dumps(fixture), encoding="utf-8")
        persisted = resolve_plan(
            load_document(config_path),
            "backend",
            ticket_mode="standard",
            evidence=evidence,
            output_mode="commit",
        )
        persisted_overlay = freeze_overlay(persisted)
        for path in (packet_path, registry_path):
            path.write_text(
                json.dumps(persisted_overlay, sort_keys=True), encoding="utf-8"
            )
            verify_overlay(persisted, json.loads(path.read_text(encoding="utf-8")))
    for agent in sorted(CLI_AGENTS):
        case = json.loads(json.dumps(fixture))
        case["work"]["backend"] = {
            "agent": agent,
            "model": "provider/model",
            "effort": "high",
        }
        resolved = resolve_plan(
            case,
            "backend",
            ticket_mode="standard",
            evidence=evidence,
            output_mode="commit",
        )
        command = startup_request(resolved, worker_name="worker", pane_id="pane")
        if command[5] != agent:
            failures.append(f"config-to-start mapping selected the wrong {agent} kind")
    bad_evidence = json.loads(json.dumps(evidence))
    bad_evidence["pi"]["binary"] = False
    try:
        resolve_plan(
            fixture,
            "backend",
            ticket_mode="standard",
            evidence=bad_evidence,
            output_mode="commit",
        )
    except ValueError:
        pass
    else:
        failures.append("unavailable binary was accepted")
    mismatched_evidence = json.loads(json.dumps(evidence))
    mismatched_evidence["pi"]["models"]["provider/model"] = []
    try:
        resolve_plan(
            fixture,
            "backend",
            ticket_mode="standard",
            evidence=mismatched_evidence,
            output_mode="commit",
        )
    except ValueError:
        pass
    else:
        failures.append("model/effort mismatch was accepted")
    if resolve_plan(fixture, "planning")["mode"] != "none":
        failures.append(
            "non-implementation task type was assigned implementation phases"
        )
    plain = resolve_plan(fixture, "backend")
    if plain["mode"] != "none":
        failures.append("missing output mode changed direct behavior")
    try:
        startup_request(plain, worker_name="worker", pane_id="pane")
    except ValueError:
        pass
    else:
        failures.append("startup accepted missing capability evidence")
    staged = resolve_plan(fixture, "backend", evidence=evidence, output_mode="commit")
    frozen = freeze_overlay(staged)
    verify_overlay(staged, json.loads(json.dumps(frozen)))
    if frozen["execution_mode_name"] != "standard":
        failures.append("frozen overlay lost the mode name")
    for stage in STAGES:
        for field in ("model", "effort"):
            key = f"{stage}_{field}"
            if (
                frozen[key]
                != fixture["modes"]["standard"]["agents"]["pi"][stage][field]
            ):
                failures.append(f"staged overlay lost {key}")
            for changed in (None, "mismatch", "missing"):
                edited = {**frozen, key: changed}
                if changed == "missing":
                    del edited[key]
                try:
                    verify_overlay(staged, edited)
                except ValueError:
                    pass
                else:
                    failures.append(f"staged overlay accepted invalid {key}")
    staged_pi = resolve_plan(
        fixture, "backend", evidence=evidence, output_mode="commit"
    )
    try:
        command = startup_request(staged_pi, worker_name="worker", pane_id="pane")
    except ValueError:
        failures.append("Pi staged mode did not use its native adapter")
    else:
        if command[5] != "pi" or "--thinking" not in command:
            failures.append(
                "Pi staged startup omitted its native model/thinking arguments"
            )
    case = json.loads(json.dumps(fixture))
    case["work"]["backend"]["agent"] = "codex"
    try:
        plan = resolve_plan(case, "backend", evidence=evidence, output_mode="commit")
        startup_request(plan, worker_name="worker", pane_id="pane")
    except ValueError:
        failures.append("codex staged mode did not enter native startup caller")
    claude_case = json.loads(json.dumps(fixture))
    claude_case["work"]["backend"]["agent"] = "claude"
    claude_staged = resolve_plan(
        claude_case, "backend", evidence=evidence, output_mode="commit"
    )
    claude_command = startup_request(
        claude_staged, worker_name="worker", pane_id="pane"
    )
    if (
        claude_command[5] != "claude"
        or "--model" not in claude_command
        or "--effort" not in claude_command
    ):
        failures.append("Claude staged plan did not enter the existing startup caller")
    try:
        continuation_request({"runtime": "herdr-codex-pane"})
    except ValueError:
        pass
    else:
        failures.append("non-Claude continuation was accepted by Claude caller")
    for agent in sorted(CLI_AGENTS):
        plan = {
            "mode": "direct",
            "agent": agent,
            "model": "provider/model",
            "effort": "high",
            "capability": "verified",
        }
        command = startup_request(plan, worker_name="worker", pane_id="pane")
        if command[4] != "--kind" or command[5] != agent:
            failures.append(f"{agent} startup mapping omitted its kind")
        if agent == "pi" and "--thinking" not in command:
            failures.append("pi startup mapping omitted thinking")
        if agent == "codex" and 'model_reasoning_effort="high"' not in command:
            failures.append("codex startup mapping omitted reasoning effort")
        if agent == "claude" and "--effort" not in command:
            failures.append("claude startup mapping omitted effort")
    # 复用 checkpoint fixture；生产入口必须绑定持久现场，且不发送任何请求。
    # pi-lens-ignore: reportMissingImports
    import checkpoint_check as fixture_module

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "execution"
        root.mkdir()
        fixture_module.git(root, "init", "-b", "check")
        fixture_module.git(
            root,
            "-c",
            "user.name=check",
            "-c",
            "user.email=check@example.invalid",
            "commit",
            "--allow-empty",
            "--no-verify",
            "-m",
            "base",
        )
        (root / "worker.py").write_text("first edit\n")
        path = Path(folder) / "checkpoint.json"
        base = fixture_module.document_for(checkpoint.snapshot_worktree(root), path)
        for agent in ("pi", "codex"):
            path = Path(folder) / f"{agent}-checkpoint.json"
            document = fixture_module.with_update(
                base,
                checkpoint_path=str(path),
                runtime=f"herdr-{agent}-pane",
                session_id="018f47a0-1b2c-7d3e-8f40-123456789abc",
            )
            checkpoint.write_checkpoint(path, document, worktree=root)
            intent = checkpoint.build_continuation_intent(
                document, target_request={"model": "provider/model", "effort": "high"}
            )
            payload = {
                "runtime": document["runtime"],
                "checkpoint_path": str(path),
                "request": {
                    "request_id": "request-"
                    + intent[checkpoint.INTENT_FINGERPRINT_FIELD],
                    "intent_sha256": intent[checkpoint.INTENT_FINGERPRINT_FIELD],
                    "target_request": intent["target_request"],
                },
                "observation": fixture_module.observation(
                    document,
                    status="stopped",
                    writer_active=False,
                    coordinator_active=False,
                    ready_seen=True,
                    stop_evidence=True,
                    session_resumable=True,
                ),
                "evidence": evidence,
            }
            result = continuation_request(payload)
            assert result["session_id"] == document["session_id"]
            assert result["checkpoint_sha256"] == document["checkpoint_sha256"]
            if agent == "pi":
                assert result["commands"][0]["text"] == "/model provider/model"
            else:
                assert result["native_args"][:2] == ["resume", document["session_id"]]
            for field, value in (
                ("evidence", {}),
                ("runtime", "herdr-claude-pane"),
                ("observation", {**payload["observation"], "writer_active": True}),
                ("request", {**payload["request"], "intent_sha256": "b" * 64}),
            ):
                try:
                    continuation_request({**payload, field: value})
                except ValueError:
                    pass
                else:
                    failures.append(f"{agent} continuation accepted invalid {field}")

    cases: dict[str, dict] = {}
    case = valid_fixture()
    case["version"] = 3
    cases["old-version"] = case
    case = valid_fixture()
    del case["work"]["testing"]
    cases["missing-required-task"] = case
    case = valid_fixture()
    case["work"]["bogus"] = case["work"]["planning"].copy()
    cases["unknown-task"] = case
    case = valid_fixture()
    case["work"]["backend"]["extra"] = True
    cases["extra-field"] = case
    case = valid_fixture()
    case["work"]["testing"]["agent"] = "bogus"
    cases["bogus-agent"] = case
    case = valid_fixture()
    case["work"]["testing"]["agent"] = "codex-app"
    cases["app-agent-in-cli"] = case
    case = valid_fixture()
    case["work"]["design"]["model"] = ""
    cases["blank-model"] = case
    case = valid_fixture()
    case["extra"] = True
    cases["extra-top-level"] = case
    case = valid_fixture()
    case["legacy_execution"] = {}
    cases["legacy-in-cli"] = case
    case = valid_fixture()
    case["default_mode"] = "missing"
    cases["unknown-default-mode"] = case
    case = valid_fixture()
    del case["review"]["implementation"]["spec"]
    cases["missing-review-axis"] = case
    case = valid_fixture()
    case["modes"]["standard"]["agents"]["pi"]["starting"] = {"model": "provider/model"}
    cases["missing-stage-field"] = case
    case = valid_fixture()
    case["modes"]["standard"]["kind"] = "bogus"
    cases["bogus-kind"] = case
    case = valid_app_fixture()
    case["work"]["planning"]["agent"] = "pi"
    cases["cli-agent-in-app"] = case

    for name, document in cases.items():
        transport = "app" if name == "cli-agent-in-app" else "cli"
        if not validate_document(document, transport):
            failures.append(f"invalid fixture accepted: {name}")

    # 迁移：CLI v2/v3 与 App v1 → v4，结果必须通过对应 transport 验证。
    legacy_v2 = {
        "version": 2,
        "roles": {
            role: {"agent": "pi", "model": "provider/model", "effort": "high"}
            for role in sorted(LEGACY_ROLES)
        },
    }
    migrated, transport = migrate_document(json.loads(json.dumps(legacy_v2)))
    if (
        transport != "cli"
        or validate_document(migrated)
        or migrated["default_mode"] != "migrated-direct"
    ):
        failures.append("v2 migration did not produce a valid direct-mode v4 config")
    if migrated["review"]["whole-change"]["spec"]["model"] != "provider/model":
        failures.append("v2 migration lost the review role triple")
    legacy_v3 = json.loads(json.dumps(legacy_v2))
    legacy_v3["version"] = 3
    legacy_v3["execution"] = {
        agent: {
            "default_mode": "staged",
            **{
                stage: {"model": "provider/model", "effort": "high"} for stage in STAGES
            },
        }
        for agent in sorted(CLI_AGENTS)
    }
    migrated, _ = migrate_document(json.loads(json.dumps(legacy_v3)))
    if (
        migrated["default_mode"] != "migrated-staged"
        or migrated["modes"]["migrated-staged"]["kind"] != "staged"
        or set(migrated["modes"]["migrated-staged"]["agents"]) != CLI_AGENTS
    ):
        failures.append("v3 migration did not produce the staged mode preset")
    mixed = json.loads(json.dumps(legacy_v3))
    mixed["execution"]["codex"]["default_mode"] = "direct"
    try:
        migrate_document(mixed)
    except ValueError:
        pass
    else:
        failures.append("mixed legacy default_mode was silently migrated")
    conflict_v2 = json.loads(json.dumps(legacy_v2))
    conflict_v2["roles"]["frontend"] = {
        "agent": "pi",
        "model": "other/model",
        "effort": "low",
    }
    try:
        migrate_document(conflict_v2)
    except ValueError:
        pass
    else:
        failures.append("conflicting same-agent role triples were silently migrated")
    legacy_app = {
        "version": 1,
        "default_mode": "astra-sol",
        "work": {
            task: {"model": "provider/model", "effort": "high"}
            for task in sorted(APP_REQUIRED_WORK)
        },
        "modes": {
            "astra-sol": {
                "kind": "staged",
                "phase_plan": {
                    stage: {"model": "provider/model", "effort": "high"}
                    for stage in STAGES
                },
            }
        },
        "review": {
            scope: {
                axis: {"model": "provider/model", "effort": "high"}
                for axis in REVIEW_AXES
            }
            for scope in REVIEW_SCOPES
        },
        "legacy_execution": {
            key: {"model": "provider/model", "effort": "high"}
            for key in sorted(LEGACY_EXECUTION_KEYS)
        },
    }
    migrated, transport = migrate_document(legacy_app)
    if transport != "app" or validate_document(migrated, "app"):
        failures.append("App v1 migration did not produce a valid v4 config")
    if (
        migrated["modes"]["astra-sol"]["agents"]["codex-app"]["execution"]["model"]
        != "provider/model"
    ):
        failures.append("App v1 migration lost a phase plan")
    if migrated["work"]["coordinator"]["agent"] != "codex-app":
        failures.append("App v1 migration did not bind the codex-app agent")
    try:
        migrate_document(valid_fixture())
    except ValueError:
        pass
    else:
        failures.append("v4 config was accepted for migration")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "model-roles.json"
        path.write_text(json.dumps(legacy_v3), encoding="utf-8")
        result = migrate_path(path)
        readback = json.loads(path.read_text(encoding="utf-8"))
        if result["default_mode"] != "migrated-staged" or validate_document(readback):
            failures.append("migrate_path readback did not round-trip")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate delivery-pipeline model task config"
    )
    parser.add_argument(
        "command",
        choices=(
            "validate",
            "self-test",
            "resolve",
            "freeze",
            "start",
            "resume",
            "migrate",
        ),
    )
    parser.add_argument(
        "path", nargs="?", default="~/.config/delivery-pipeline/model-roles.json"
    )
    parser.add_argument("task", nargs="?")
    parser.add_argument("--ticket-mode")
    parser.add_argument("--map-mode")
    parser.add_argument("--output-mode")
    parser.add_argument("--evidence", help="归一化实时能力 evidence JSON")
    parser.add_argument("--worker-name", default="worker")
    parser.add_argument("--pane-id", default="pane")
    parser.add_argument("--request", help="persisted native continuation payload JSON")
    args = parser.parse_args()

    if args.command == "self-test":
        errors = self_test()
        print(
            json.dumps(
                {"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2
            )
        )
        return 0 if not errors else 1
    if args.command == "validate":
        errors = validate_path(Path(args.path))
        print(
            json.dumps(
                {"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2
            )
        )
        return 0 if not errors else 1
    if args.command == "migrate":
        try:
            result = migrate_path(Path(args.path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(
                json.dumps(
                    {"valid": False, "errors": [str(error)]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "resume":
        if not args.request:
            parser.error("resume 需要 --request PAYLOAD_JSON")
        try:
            payload = json.loads(Path(args.request).expanduser().read_text())
            result = continuation_request(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(
                json.dumps(
                    {"valid": False, "errors": [str(error)]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if not args.task:
        parser.error(f"{args.command} 需要 TASK")
    try:
        evidence = (
            json.loads(Path(args.evidence).expanduser().read_text())
            if args.evidence
            else None
        )
        plan = resolve_plan(
            load_document(Path(args.path)),
            args.task,
            ticket_mode=args.ticket_mode,
            map_mode=args.map_mode,
            evidence=evidence,
            output_mode=args.output_mode,
        )
        if args.command == "start":
            result = startup_request(
                plan, worker_name=args.worker_name, pane_id=args.pane_id
            )
        elif args.command == "freeze":
            result = freeze_overlay(plan)
        else:
            result = plan
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"valid": False, "errors": [str(error)]}, ensure_ascii=False, indent=2
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

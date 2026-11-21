#!/usr/bin/env python3
from collections import Counter
import copy
import argparse
import fcntl
import hashlib
from contextlib import contextmanager
from typing import TypedDict, Literal, Callable, Mapping
import json
import os
import sys
import tempfile
from pathlib import Path

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
        return [f"{prefix} must define exactly agent, model, effort"]
    errors = _pair_errors(prefix, {k: value[k] for k in ("model", "effort")})
    if value.get("agent") not in agents:
        errors.append(f"{prefix}.agent must be one of {sorted(agents)}")
    return errors


class ModelTriple(TypedDict):
    agent: Literal["pi", "codex", "claude"]
    model: str
    effort: str


def triple(value: dict) -> ModelTriple:
    return {k: value[k] for k in ("agent", "model", "effort")}


def _cell_errors(prefix, value, agents, listing=None):
    if listing is None:
        return _entry_errors(prefix, value, agents)
    if not isinstance(value, dict) or set(value) != {"agent", "model", "effort", listing}:
        return [f"{prefix} must define exactly agent, model, effort, {listing}"]
    errors = _entry_errors(prefix, triple(value), agents)
    items = value[listing]
    if not isinstance(items, list):
        return errors + [f"{prefix}.{listing} must be a list"]
    for i, item in enumerate(items):
        errors.extend(_entry_errors(f"{prefix}.{listing}.{i}", item, agents))
    return errors


def _family_errors(families: object) -> list[str]:
    import re
    if not isinstance(families, dict):
        return ["model_families must be an object"]
    errors = []
    for agent, models in families.items():
        if agent not in CLI_AGENTS or not isinstance(models, dict):
            errors.append("family declarations require an exact CLI agent and native model map")
            continue
        for model, value in models.items():
            if (not isinstance(model, str) or not model.strip()
                    or not isinstance(value, dict) or set(value) != {"family", "source"}
                    or value.get("source") != "user_declared"
                    or not isinstance(value.get("family"), str)
                    or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value["family"], re.ASCII)):
                errors.append("family must be a normalized ASCII slug with user_declared source")
    return errors


def family_declaration(document: dict, agent: str, native_model: str) -> dict | None:
    """精确用户覆盖；effort 不参与身份，未声明时由 model_vendor 查对照表。"""
    return copy.deepcopy(document.get("model_families", {}).get(agent, {}).get(native_model))


VENDOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ('gpt-', 'openai'), ('o1', 'openai'), ('o3', 'openai'), ('o4', 'openai'),
    ('claude-', 'anthropic'), ('gemini-', 'google'), ('kimi-', 'moonshot'),
    ('grok-', 'xai'), ('deepseek-', 'deepseek'),
)
ReviewOutcome = Literal['different', 'no_different_family', 'unrecognized', 'none_runnable']


def model_vendor(document: dict, agent: str, model: str) -> str | None:
    """手动覆盖优先；剥离路由和上下文后缀后查内置厂商表。"""
    declaration = family_declaration(document, agent, model)
    if declaration:
        return declaration['family']
    name = model.rsplit('/', 1)[-1].split('@', 1)[0].lower()
    return next((vendor for prefix, vendor in VENDOR_PREFIXES if name.startswith(prefix)), None)


def choose_review_candidate(pool: list[dict], runnable: list[bool],
                            pool_vendors: list[str | None],
                            implementation_vendors: list[str | None]) -> tuple[int | None, ReviewOutcome]:
    """运行时与预览共用的顺序选择；没有完整厂商证据时按顺序回退。"""
    available = [i for i in range(len(pool)) if runnable[i]]
    if not available:
        return None, 'none_runnable'
    for i in available:
        if (pool_vendors[i] and implementation_vendors and all(implementation_vendors)
                and pool_vendors[i] not in implementation_vendors):
            return i, 'different'
    unknown = not implementation_vendors or any(v is None for v in [*pool_vendors, *implementation_vendors])
    return available[0], 'unrecognized' if unknown else 'no_different_family'


def preview_review_choice(document: dict, evidence: dict) -> dict:
    """按当前草稿的设计/前端/后端主模型预计；不探测、不修改输入。"""
    errors = validate_document(document)
    if errors:
        raise ValueError('; '.join(errors))
    if (not isinstance(evidence, dict) or not evidence.get('request_id')
            or not evidence.get('observed_at') or not isinstance(evidence.get('sources'), dict)
            or not isinstance(evidence.get('capabilities'), dict)):
        raise ValueError('preview-review requires complete current probe evidence')
    implementations = [triple(document['work'][task]) for task in ('design', 'frontend', 'backend')]
    axes = {axis: [triple(cell), *cell['candidates']]
            for axis, cell in document['review']['whole-change'].items() if cell['candidates']}
    for identity in [*implementations, *(item for pool in axes.values() for item in pool)]:
        agent = identity['agent']
        source = evidence['sources'].get(agent, {})
        capability = evidence['capabilities'].get(agent)
        if (source.get('status') != 'ok' or not isinstance(capability, dict)
                or not isinstance(capability.get('binary'), bool)
                or not isinstance(capability.get('models'), dict)):
            raise ValueError('preview-review requires complete probe source for ' + agent)
    vendors = [model_vendor(document, x['agent'], x['model']) for x in implementations]
    result = {}
    for axis, pool in axes.items():
        pool_vendors = [model_vendor(document, x['agent'], x['model']) for x in pool]
        runnable = [not capability_errors(**x, evidence=evidence['capabilities']) for x in pool]
        index, outcome = choose_review_candidate(pool, runnable, pool_vendors, vendors)
        unknown = [x for x, vendor in zip([*implementations, *pool], [*vendors, *pool_vendors]) if vendor is None]
        result[axis] = {'selected': pool[index] if index is not None else None,
                        'selected_index': index, 'outcome': outcome,
                        'unrecognized': [x for i, x in enumerate(unknown) if x not in unknown[:i]]}
    return result


DEFAULT_LIMITS = {"parallel": 4, "max_turns": 100}


def read_limits(config: dict) -> dict:
    if config.get("version") in (6, 7):
        return DEFAULT_LIMITS.copy()
    if config.get("version") != 8:
        raise ValueError("dispatch requires CLI config v6, v7 or v8")
    limits = config.get("dispatch")
    if not isinstance(limits, dict) or set(limits) != set(DEFAULT_LIMITS):
        raise ValueError("dispatch must define exactly parallel and max_turns")
    for key, value in limits.items():
        if type(value) is not int or value < 1:
            raise ValueError(f"dispatch.{key} must be a positive integer")
    return limits.copy()


def apply_limits(config: dict, limits: dict) -> dict:
    migrated, transport = migrate_document(config)
    if transport != "cli":
        raise ValueError("dispatch requires CLI config")
    migrated["dispatch"] = limits
    migrated["dispatch"] = read_limits(migrated)
    return migrated


def validate_document(document: object, transport: str = "cli") -> list[str]:
    """只检查 CLI v6/v7 / App v5 结构，不探测或修改用户配置。transport 为 cli 或 app。"""
    if transport not in ("cli", "app"):
        return ["transport must be cli or app"]
    agents = CLI_AGENTS if transport == "cli" else {"codex-app"}
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level value must be an object"]
    top_level = {"version", "work", "modes", "review"}
    if transport == "cli" and document.get("version") == 8:
        top_level.add("dispatch")
        try:
            read_limits(document)
        except ValueError as error:
            errors.append(str(error))
    if transport == "cli" and document.get("version") in (7, 8):
        top_level.add("model_families")
    if transport == "app":
        top_level = top_level | {"default_mode"}
    if set(document) != top_level:
        errors.append(f"top-level keys must be exactly {sorted(top_level)}")
    if transport == "cli" and "default_mode" in document:
        errors.append("default_mode is App-only; CLI 默认计划来自 work 项")
    if document.get("version") not in ((6, 7, 8) if transport == "cli" else (5,)):
        errors.append(
            "unsupported version; older configs need model_config.py migrate"
        )
    if transport == "cli" and document.get("version") in (7, 8):
        errors.extend(_family_errors(document.get("model_families")))
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
            errors.extend(_cell_errors(f"work.{task}", work[task], agents, "fallbacks" if transport == "cli" and task in CLI_REQUIRED_WORK else None))
    modes = document.get("modes")
    if not isinstance(modes, dict):
        errors.append("modes must be an object")
    elif transport == "app" and not modes:
        errors.append("app modes must be a non-empty object")
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
            elif mode["kind"] != "direct":
                errors.append(f"{prefix}.kind must equal direct; CLI 与 App 只跑 direct")
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
    if transport == "app":
        default_mode = document.get("default_mode")
        if (
            not isinstance(default_mode, str)
            or not isinstance(modes, dict)
            or default_mode not in modes
        ):
            errors.append("default_mode must name an existing mode")
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
                    _cell_errors(f"review.{scope}.{axis}", axes[axis], agents, "candidates" if transport == "cli" else None)
                )
    return errors


def validate_path(path: Path) -> list[str]:
    try:
        return validate_document(json.loads(path.expanduser().read_text()))
    except FileNotFoundError:
        return [f"config file not found: {path.expanduser()}"]
    except json.JSONDecodeError as error:
        return [f"invalid JSON: {error}"]


def show(path: Path) -> dict:
    """离线快照：只读原字节，不采集能力，不初始化或迁移。"""
    path = path.expanduser().absolute()
    result = {"api_version": 1, "path": str(path), "file_state": "ready",
              "base_hash": None, "config": None,
              "validation": {"valid": False, "errors": []}, "cells": {}}
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        result["file_state"] = "missing"
        return result
    except OSError:
        result["file_state"] = "unreadable"
        return result
    result["base_hash"] = hashlib.sha256(raw).hexdigest()
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError):
        result["file_state"] = "invalid_json"
        return result
    result["config"] = document
    errors = validate_document(document)
    result["validation"] = {"valid": not errors, "errors": errors}
    if isinstance(document, dict) and document.get("version") not in (6, 7, 8):
        result["file_state"] = "unsupported_version"
    elif errors:
        result["file_state"] = "invalid_schema"
    else:
        result["cells"] = {
            **{f"work.{task}": {"status": "unknown"} for task in sorted(CLI_REQUIRED_WORK)},
            **{f"review.{scope}.{axis}": {"status": "unknown"}
               for scope in REVIEW_SCOPES for axis in REVIEW_AXES},
        }
    return result


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


def _migrate_v4_cli(document: dict) -> tuple[dict, str]:
    """CLI v4 → v5：work 项收回模型权威；starting≠execution 的 staged 计划无法直跑，报错。"""
    modes = document.get("modes")
    default_mode = document.get("default_mode")
    if not isinstance(modes, dict) or not isinstance(modes.get(default_mode), dict):
        raise ValueError(
            "v4 default_mode must name an existing mode; rerun delivery-pipeline-setup"
        )
    mode = modes[default_mode]
    kind = mode.get("kind")
    plans = mode.get("agents")
    plans = plans if isinstance(plans, dict) else {}
    work: dict[str, dict] = {}
    for task, raw in document.get("work", {}).items():
        entry = dict(raw) if isinstance(raw, dict) else raw
        if task in IMPLEMENTATION_TASKS and isinstance(entry, dict):
            plan = plans.get(entry.get("agent"))
            if not isinstance(plan, dict):
                raise ValueError(
                    f"v4 default_mode 缺少 work.{task} 的 agent 计划；rerun "
                    "delivery-pipeline-setup"
                )
            pair = {"model": entry.get("model"), "effort": entry.get("effort")}
            if kind == "staged":
                if plan.get("starting") != pair:
                    raise ValueError(
                        f"v4 work.{task} 与 default_mode starting 冲突；rerun "
                        "delivery-pipeline-setup"
                    )
                if plan.get("execution") != pair:
                    raise ValueError(
                        f"v4 work.{task} 的 staged execution 已移除（CLI 只跑 direct）；"
                        "rerun delivery-pipeline-setup"
                    )
            elif plan.get("direct") != pair:
                raise ValueError(
                    f"v4 work.{task} 与 default_mode direct 冲突；rerun "
                    "delivery-pipeline-setup"
                )
        work[task] = entry
    migrated = {
        "version": 5,
        "work": work,
        "modes": {
            name: {**mode, "kind": "direct"} for name, mode in modes.items()
        },
        "review": document.get("review"),
    }
    errors = validate_document(migrate_document(migrated)[0], "cli")
    if errors:
        raise ValueError("migration produced invalid config: " + "; ".join(errors))
    return migrated, "cli"


def migrate_document(document: dict) -> tuple[dict, str]:
    if not isinstance(document, dict):
        raise ValueError("unrecognized config")
    is_app = "default_mode" in document and any(
        isinstance(c, dict) and c.get("agent") == "codex-app"
        for c in document.get("work", {}).values())
    if document.get("version") in (6, 7, 8) or (document.get("version") == 5 and is_app):
        transport = "app" if is_app else "cli"
        errors = validate_document(document, transport)
        if errors: raise ValueError("; ".join(errors))
        migrated = copy.deepcopy(document)
        if transport == "cli" and migrated["version"] == 6:
            migrated.update(version=7, model_families={})
        if transport == "cli" and migrated["version"] == 7:
            migrated.update(version=8, dispatch=DEFAULT_LIMITS.copy())
        return migrated, transport
    if document.get("version") == 5:
        for c in [*document.get("work", {}).values(), *(c for axes in document.get("review", {}).values() for c in axes.values())]:
            errors = _entry_errors("legacy cell", c, CLI_AGENTS)
            if errors: raise ValueError("; ".join(errors))
        migrated, transport = copy.deepcopy(document), "cli"
    else:
        migrated, transport = _migrate_legacy_document(document)
    if transport == "cli":
        migrated["version"] = 6
        for task in CLI_REQUIRED_WORK:
            migrated["work"][task]["fallbacks"] = []
        for axes in migrated["review"].values():
            for c in axes.values(): c["candidates"] = []
    if transport == "cli":
        migrated.update(version=8, model_families={}, dispatch=DEFAULT_LIMITS.copy())
    errors = validate_document(migrated, transport)
    if errors: raise ValueError("; ".join(errors))
    return migrated, transport


def _migrate_legacy_document(document: dict) -> tuple[dict, str]:
    """旧转换阶段到 version 5；返回 (新配置, transport)。不改已有 lane。"""
    if not isinstance(document, dict):
        raise ValueError(
            "unrecognized config version; migrate supports CLI v2/v3/v4 and App v1/v4"
        )
    version = document.get("version")
    if version == 5:
        raise ValueError("config is already version 5")
    if version == 4:
        # v4 实例没有显式 transport 标记；按 App 独有特征识别，失败时按 CLI 处理。
        is_app = "legacy_execution" in document or (
            isinstance(document.get("work"), dict)
            and any(
                isinstance(entry, dict) and entry.get("agent") == "codex-app"
                for entry in document["work"].values()
            )
        )
        if is_app:
            migrated = {**document, "version": 5}
            errors = validate_document(migrated, "app")
            if errors:
                raise ValueError(
                    "migration produced invalid config: " + "; ".join(errors)
                )
            return migrated, "app"
        return _migrate_v4_cli(document)
    if version in (2, 3):
        errors = _validate_legacy_cli(document)
        if errors:
            raise ValueError("; ".join(errors))
        roles = document["roles"]
        review_triple = dict(roles["review"])
        review = {
            scope: {axis: dict(review_triple) for axis in REVIEW_AXES}
            for scope in REVIEW_SCOPES
        }
        work: dict[str, dict] = {}
        for task in sorted(LEGACY_ROLES - {"review"}):
            entry = dict(roles[task])
            if version == 3 and task in IMPLEMENTATION_TASKS:
                plan = document["execution"][entry["agent"]]
                pair = {"model": entry["model"], "effort": entry["effort"]}
                if plan["default_mode"] == "staged":
                    if plan["starting"] != pair:
                        raise ValueError(
                            f"legacy roles.{task} 与 staged starting 冲突；rerun "
                            "delivery-pipeline-setup"
                        )
                    if plan["execution"] != pair:
                        raise ValueError(
                            f"legacy roles.{task} 的 staged execution 已移除（CLI 只跑 direct）；"
                            "rerun delivery-pipeline-setup"
                        )
                elif plan["direct"] != pair:
                    raise ValueError(
                        f"legacy roles.{task} 与 direct 计划冲突；rerun "
                        "delivery-pipeline-setup"
                    )
            work[task] = entry
        migrated = {"version": 5, "work": work, "modes": {}, "review": review}
        errors = validate_document(migrate_document(migrated)[0], "cli")
        if errors:
            raise ValueError(
                "migration produced invalid config: " + "; ".join(errors)
            )
        return migrated, "cli"
    if version == 1:
        errors = _validate_legacy_app(document)
        if errors:
            raise ValueError("; ".join(errors))
        for name, mode in document["modes"].items():
            plan = mode["phase_plan"]
            if mode["kind"] == "staged" and plan["starting"] != plan["execution"]:
                raise ValueError(
                    f"App v1 modes.{name} 的 staged execution 已移除（Prewalk 退役，App 只跑 direct）；"
                    "rerun delivery-pipeline-setup"
                )
        migrated = {
            "version": 5,
            "default_mode": document["default_mode"],
            "work": {
                task: {"agent": "codex-app", **value}
                for task, value in document["work"].items()
            },
            "modes": {
                name: {
                    "kind": "direct",
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
        }
        errors = validate_document(migrated, "app")
        if errors:
            raise ValueError(
                "migration produced invalid config: " + "; ".join(errors)
            )
        return migrated, "app"
    raise ValueError(
        "unrecognized config version; migrate supports CLI v2/v3/v4 and App v1/v4"
    )


class Snapshot(TypedDict):
    raw: bytes | None
    base_hash: str | None
    config: object


class ProbeEvidence(TypedDict):
    request_id: str
    observed_at: str
    gateway: dict          # {"status": "ok" | "unreachable"}
    capabilities: dict
    sources: dict


class Applied(TypedDict):
    status: Literal["applied"]
    changed: bool
    base_hash: str
    config: dict


class Rejected(TypedDict):
    status: Literal["rejected"]
    error: dict


class Unverified(TypedDict):
    status: Literal["commit_unverified"]
    error: dict
    expected_hash: str | None


CommitResult = Applied | Rejected | Unverified


class ConfigRejected(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CommitUnverified(OSError):
    def __init__(self, result: Unverified):
        super().__init__(result["error"]["message"])
        self.result = result


def read_snapshot(path: Path) -> Snapshot:
    """hash 只来自实际原字节；坏 JSON 仍可绑定显式修复的基线。"""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"raw": None, "base_hash": None, "config": None}
    try:
        config = json.loads(raw)
    except (ValueError, UnicodeError):
        config = None
    return {"raw": raw, "base_hash": hashlib.sha256(raw).hexdigest(), "config": config}


@contextmanager
def config_lock(path: Path):
    # sidecar 永不删除；锁住被 replace 的 inode 会让合作进程失去互斥。
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def configuration_transaction(
    path: Path, prepare: Callable[[Snapshot], dict]
) -> CommitResult:
    """共享写入 Interface：prepare 在锁内核对基线/权限，返回完整合法候选。

    仅供 canonical configure/migrate/apply 调用；Host 不传 prepare。
    不重试、不回滚；replace 返回后所有读回失败均为待确认。
    """
    path = path.expanduser().resolve()
    committed = False
    expected_hash = None
    temp_name = None
    try:
        with config_lock(path):
            snapshot = read_snapshot(path)
            candidate = prepare(snapshot)
            if snapshot["raw"] is not None and snapshot["config"] == candidate:
                return {"status": "applied", "changed": False,
                        "base_hash": snapshot["base_hash"], "config": snapshot["config"]}
            payload = (json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode()
            expected_hash = hashlib.sha256(payload).hexdigest()
            handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
            with os.fdopen(handle, "wb") as temp:
                temp.write(payload)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, path)
            committed = True
            temp_name = None
            actual = read_snapshot(path)
            if actual["raw"] != payload:
                raise OSError("提交后精确读回不一致")
            return {"status": "applied", "changed": True,
                    "base_hash": actual["base_hash"], "config": actual["config"]}
    except (OSError, ValueError, TypeError) as error:
        if committed:
            return {"status": "commit_unverified", "expected_hash": expected_hash,
                    "error": {"code": "commit_unverified", "message": str(error)}}
        return {"status": "rejected", "error": {
            "code": error.code if isinstance(error, ConfigRejected) else "io_error",
            "message": str(error)}}
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def _config_entries(document: dict) -> dict:
    entries = {"work." + key: triple(value) for key, value in document["work"].items()}
    for scope, axes in document["review"].items():
        entries.update({f"review.{scope}.{axis}": triple(value) for axis, value in axes.items()})
    for name, mode in document["modes"].items():
        for agent, plan in mode["agents"].items():
            # CLI 只消费 direct；保留的 starting/execution 不恢复执行语义。
            entries[f"modes.{name}.{agent}.direct"] = {"agent": agent, **plan["direct"]}
    return entries


def validate_selection(candidate: dict, previous: object,
                       evidence: ProbeEvidence, request_id: str) -> None:
    errors = validate_document(candidate)
    if errors:
        raise ConfigRejected("invalid_candidate", "; ".join(errors))
    if evidence is not None and (not isinstance(evidence, dict) or not request_id
            or evidence.get("request_id") != request_id
            or not isinstance(evidence.get("observed_at"), str)
            or not evidence["observed_at"].strip()
            or not isinstance(evidence.get("sources"), dict)):
        raise ConfigRejected("capability_unavailable", "需要本次 request-id 的能力证据")
    previous_valid = not validate_document(previous)
    referenced = set()
    for c in [*candidate["work"].values(), *(c for axes in candidate["review"].values() for c in axes.values())]:
        for item in [c, *c.get("fallbacks", []), *c.get("candidates", [])]:
            referenced.add((item["agent"], item["model"]))
    previous_families = previous.get("model_families", {}) if previous_valid else {}
    for agent, models in candidate.get("model_families", {}).items():
        for model in models:
            if (agent, model) not in referenced and model not in previous_families.get(agent, {}):
                raise ConfigRejected("invalid_candidate", "新声明必须对应配置引用的精确工具和原生模型")
    old_entries = (_config_entries(previous) if previous_valid else {})
    def counts(document, task):
        c = document["work"][task]
        return Counter(tuple(item[k] for k in ("agent", "model", "effort")) for item in c["fallbacks"])
    additions = {}
    for task in CLI_REQUIRED_WORK:
        old = counts(previous, task) if previous_valid else Counter()
        for identity in counts(candidate, task) - old:
            additions[f"work.{task}.fallbacks.{identity}"] = dict(zip(("agent", "model", "effort"), identity))
    for scope in REVIEW_SCOPES:
        for axis in REVIEW_AXES:
            def candidates(document):
                return Counter(tuple(item[k] for k in ("agent", "model", "effort"))
                               for item in document["review"][scope][axis]["candidates"])
            old = candidates(previous) if previous_valid else Counter()
            for identity in candidates(candidate) - old:
                additions[f"review.{scope}.{axis}.candidates.{identity}"] = dict(zip(("agent", "model", "effort"), identity))
    for key, entry in {**_config_entries(candidate), **additions}.items():
        if old_entries.get(key) == entry:
            continue
        if evidence is None:
            raise ConfigRejected("capability_unavailable", "需要本次 request-id 的能力证据")
        source = evidence["sources"].get(entry["agent"], {})
        errors = capability_errors(entry["agent"], entry["model"], entry["effort"],
                                   evidence.get("capabilities"))
        if not isinstance(source, dict) or source.get("status") != "ok":
            errors.append("能力来源未成功")
        if errors:
            raise ConfigRejected("capability_unavailable", key + ": " + "; ".join(errors))


def configure(path: Path, candidate: dict, base_hash: str | None,
              evidence: ProbeEvidence, request_id: str) -> CommitResult:
    """setup 的完整编辑权限；桌面 apply 必须另检查只读区，再复用本事务。"""
    def prepare(snapshot: Snapshot) -> dict:
        if snapshot["base_hash"] != base_hash:
            raise ConfigRejected("base_conflict", "配置已变化，请读取最新配置后人工核对")
        validate_selection(candidate, snapshot["config"], evidence, request_id)
        return candidate
    return configuration_transaction(path, prepare)


DESKTOP_CELLS = [*("work." + n for n in ("planning", "design", "frontend", "backend", "testing")),
                 *(f"review.{scope}.{axis}" for scope in ("implementation", "whole-change")
                   for axis in ("standards", "spec"))]


def apply(path: Path, candidate: dict, base_hash: str,
          evidence: ProbeEvidence, request_id: str) -> CommitResult:
    def prepare(snapshot: Snapshot) -> dict:
        previous = snapshot["config"]
        if (snapshot["raw"] is None or validate_document(previous)):
            raise ConfigRejected("unsupported_config", "请让 AI setup 处理当前配置")
        if not base_hash or snapshot["base_hash"] != base_hash:
            raise ConfigRejected("base_conflict", "请显式读取最新设置并人工核对草稿")
        errors = validate_document(candidate)
        if errors:
            raise ConfigRejected("invalid_candidate", "; ".join(errors))
        # 仅替换九格的三元组；同一格的其他合法字段也属于只读区。
        permitted = copy.deepcopy(previous)
        for key in DESKTOP_CELLS:
            parts = key.split(".")
            old, new = permitted, candidate
            for part in parts:
                old, new = old[part], new[part]
            for field in ("agent", "model", "effort"):
                old[field] = new[field]
            if key.startswith("work."):
                old["fallbacks"] = copy.deepcopy(new["fallbacks"])
            else:
                old["candidates"] = copy.deepcopy(new["candidates"])
        if previous["version"] in (7, 8):
            permitted["model_families"] = copy.deepcopy(candidate["model_families"])
        if candidate["version"] == 8:
            permitted = apply_limits(permitted, candidate["dispatch"])
        if permitted != candidate:
            raise ConfigRejected("invalid_candidate", "桌面不能修改只读设置")
        validate_selection(candidate, previous, evidence, request_id)
        return candidate
    return configuration_transaction(path, prepare)


def migrate_path(path: Path) -> dict:
    """迁移范围与成功返回不变；读取、转换、替换、读回均在共享锁内。"""
    path = path.expanduser()
    transport = None
    migrated = None
    def prepare(snapshot: Snapshot) -> dict:
        nonlocal transport, migrated
        migrated, transport = migrate_document(snapshot["config"])
        return migrated
    result = configuration_transaction(path, prepare)
    if result["status"] == "commit_unverified":
        raise CommitUnverified(result)
    if result["status"] == "rejected":
        raise ConfigRejected(result["error"]["code"], result["error"]["message"])
    return {"migrated": str(path), "transport": transport,
            "default_mode": migrated.get("default_mode")}


CodexRoute = Literal["gateway", "direct"] | None


def codex_route(config: dict, env: Mapping[str, str]) -> CodexRoute:
    provider = config.get('model_provider', 'openai')
    endpoint = (env.get('OPENAI_BASE_URL') or config.get('openai_base_url', '')
                if provider == 'openai' else
                config.get('model_providers', {}).get(provider, {}).get('base_url', ''))
    if endpoint.rstrip('/') in ('http://127.0.0.1:3425/v1',
                                'http://127.0.0.1:3425/backend-api/codex'):
        return 'gateway'
    if provider == 'openai' and not endpoint:
        return 'direct'
    return None


ClaudeEndpoint = TypedDict('ClaudeEndpoint', {
    'route': Literal['official'] | None, 'base_url': str,
    'credential_kind': Literal['api_key', 'auth_token', 'oauth'] | None,
    'reason': str})


def claude_endpoint(settings: dict, env: Mapping[str, str],
                    oauth: dict | None, now: float) -> ClaudeEndpoint:
    settings_env = settings.get('env', {})
    base = env.get('ANTHROPIC_BASE_URL') or settings_env.get('ANTHROPIC_BASE_URL') or 'https://api.anthropic.com'
    result: ClaudeEndpoint = {'route': None, 'base_url': base,
                             'credential_kind': None, 'reason': ''}
    if base.startswith('http://127.0.0.1:3425'):
        result['reason'] = 'Claude Code 指向本机网关，暂不支持通过网关核对 Claude 模型'
        return result
    if settings.get('apiKeyHelper'):
        result['reason'] = 'Claude Code 使用 apiKeyHelper，暂不支持核对'
        return result
    for name, kind in (('ANTHROPIC_API_KEY', 'api_key'), ('ANTHROPIC_AUTH_TOKEN', 'auth_token')):
        if env.get(name) or settings_env.get(name):
            result.update(route='official', credential_kind=kind)
            return result
    if (oauth and oauth.get('accessToken') and isinstance(oauth.get('expiresAt'), (int, float))
            and oauth['expiresAt'] / 1000 >= now):
        result.update(route='official', credential_kind='oauth')
    else:
        result['reason'] = '请先打开 Claude Code 完成登录后重新核对'
    return result


EFFORT_ORDER = ('low', 'medium', 'high', 'xhigh', 'max')


class HarnessModel(TypedDict):
    native_id: str
    gateway_id: str
    efforts: list[str]


def claude_models(catalog: dict) -> list[HarnessModel]:
    try:
        if not isinstance(catalog['data'], list):
            raise ValueError
        models = []
        for model in catalog['data']:
            native = model['id']
            if not isinstance(native, str) or not native:
                raise ValueError
            effort = model.get('capabilities', {}).get('effort', {})
            efforts = [e for e in EFFORT_ORDER
                       if effort.get('supported') is True and effort.get(e, {}).get('supported') is True]
            if efforts:
                models.append({'native_id': native, 'gateway_id': native, 'efforts': efforts})
        return models
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError('无法读取 Claude 官方模型清单') from None


def probe(raw: dict, request_id: str) -> ProbeEvidence:
    """只归一化 metadata；逐工具独立，不把 gateway 声明当 harness 能力。"""
    from datetime import datetime, timezone
    if "harnesses" not in raw:
        raw = {**raw, "harnesses": collect_harnesses()}
    observed = datetime.now(timezone.utc).isoformat()
    gateway = raw.get('gateway', {})
    catalog = {m['id']: [v['effort'] for v in m.get('supported_reasoning_levels', [])
                         if isinstance(v.get('effort'), str)]
               for m in (gateway.get('data') or []) if isinstance(m.get('id'), str)}
    capabilities, sources = {}, {}
    for agent in sorted(CLI_AGENTS):
        harness = raw.get('harnesses', {}).get(agent, {})
        models = {}
        route = harness.get('route')
        if harness.get('binary') is True and route in ('gateway', 'direct', 'official'):
            for model in harness.get('models', []):
                native = model.get('native_id')
                if not isinstance(native, str) or not native:
                    continue
                if route in ('direct', 'official'):
                    allowed = model.get('efforts', [])
                elif gateway.get('status') == 'ok':
                    allowed = [e for e in model.get('efforts', [])
                               if e in catalog.get(model.get('gateway_id'), [])]
                else:
                    allowed = []
                if allowed:
                    models[native] = list(dict.fromkeys(allowed))
        capabilities[agent] = {'binary': harness.get('binary') is True, 'models': models}
        reason = ('Codex 当前指向的地址既不是本机网关也不是 OpenAI 官方，无法确认可用模型'
                  if agent == 'codex' and route is None and harness.get('binary') is True else
                  '未取得精确模型与有效档位的完整证据链')
        sources[agent] = {'route': route, 'status': 'ok' if models else 'unknown',
                          'observed_at': observed, 'reason': '' if models else harness.get('reason', reason), 'origin': harness.get('origin', '本机工具元数据'),
                          'next_step': '能力仅核验配置与元数据；认证、额度和实际执行为 Unknown。' if models else
                          '请让 AI 助手核对该工具的接入、精确模型清单和思考档位，再重新核对。'}
    # 网关状态属于证据层：区分“网关挂了”与“工具未接入”，UI 不得从 sources 反推。
    return {'request_id': request_id, 'observed_at': observed,
            'gateway': {'status': 'ok' if gateway.get('status') == 'ok' else 'unreachable'},
            'capabilities': capabilities, 'sources': sources}


def collect_harnesses() -> dict:
    """本机元数据与一次只读模型清单请求；不打印原始来源或凭据，不发推理。"""
    import shutil
    import subprocess
    home = Path.home()
    def command(agent, args):
        binary = shutil.which(agent)
        if not binary:
            candidates = {'codex': home/'.local/bin/codex', 'claude': home/'.bun/bin/claude',
                          'pi': home/'.local/bin/pi'}
            binary = str(candidates[agent]) if candidates[agent].exists() else None
            if agent == 'pi' and not binary:
                installed = list((home/'.nvm/versions/node').glob('*/bin/pi'))
                binary = str(installed[0]) if len(installed) == 1 else None
        if not binary:
            return None
        try:
            result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=15,
                env={**os.environ, 'PATH': str(Path(binary).parent) + os.pathsep + os.environ.get('PATH', '')})
            return result.stdout if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None
    result = {}
    output = command('codex', ['debug', 'models', '--bundled'])
    codex = {'binary': bool(shutil.which('codex') or (home/'.local/bin/codex').exists()),
             'route': None}
    result['codex'] = codex
    try:
        try:
            import tomllib
        except ModuleNotFoundError:
            from _vendor import tomli as tomllib
        config_path = home/'.codex/config.toml'
        config = tomllib.loads(config_path.read_text()) if config_path.exists() else {}
        codex['route'] = codex_route(config, os.environ)
    except (OSError, ValueError, ImportError):
        codex['reason'] = '无法读取 Codex 配置'
    route = codex['route']
    codex['origin'] = ('Codex 内置清单（直连 OpenAI）' if route == 'direct' else
                       'Codex 当前路由、精确 catalog 与 magpie 网关清单交集')
    if route in ('direct', 'gateway'):
        try:
            data = json.loads(output or '')
            entries = data if isinstance(data, list) else data['models']
            catalog_path = config.get('model_catalog_json')
            if route == 'gateway' and isinstance(catalog_path, str) and Path(catalog_path).expanduser().is_absolute():
                data = json.loads(Path(catalog_path).expanduser().read_text())
                entries = data if isinstance(data, list) else data['models']
            # 两种路由沿用 Codex 既有档位边界，均不提供 ultra/persistent 扩展档位。
            codex['models'] = [{'native_id': m['slug'], 'gateway_id': m['slug'],
                'efforts': [e['effort'] for e in m.get('supported_reasoning_levels', [])
                            if e['effort'] not in ('ultra', 'persistent')]} for m in entries]
        except (OSError, ValueError, KeyError, TypeError):
            codex['reason'] = '无法读取 Codex 内置模型清单'
    output = command('pi', ['--list-models', 'magpie'])
    try:
        config = json.loads((home/'.pi/agent/models.json').read_text())
        provider = config.get('providers', {}).get('magpie', {})
        models = []
        if provider.get('baseUrl', '').rstrip('/') == 'http://127.0.0.1:3425/v1':
            for m in provider.get('models', []):
                if not output or m['id'] not in output:
                    continue
                mapping = m.get('thinkingLevelMap', {})
                efforts = [e for e, value in mapping.items() if value == e and e not in ('off','ultra')]
                api = m.get('api', provider.get('api'))
                if api == 'anthropic-messages' and not m.get('compat', {}).get('forceAdaptiveThinking'):
                    efforts = [e for e in efforts if e not in ('xhigh','max')]
                models.append({'native_id': 'magpie/'+m['id'], 'gateway_id': m['id'], 'efforts': efforts})
        result['pi'] = {'binary': output is not None,'route': 'gateway' if models else None, 'models': models,
                        'origin': 'Pi 注册清单、模型映射与网关清单交集'}
    except (OSError, ValueError, KeyError):
        result['pi'] = {'binary': output is not None}
    import time
    import urllib.request
    claude = {'binary': command('claude', ['--version']) is not None,
              'route': None, 'origin': 'Anthropic 官方模型清单（Claude Code 当前账号与地址）'}
    result['claude'] = claude
    try:
        path = home/'.claude/settings.json'
        settings = json.loads(path.read_text()) if path.exists() else {}
        oauth = None
        endpoint = claude_endpoint(settings, os.environ, oauth, time.time())
        # 有显式凭据或不支持的路由时，不触碰钥匙串。
        if endpoint['reason'] == '请先打开 Claude Code 完成登录后重新核对':
            try:
                if sys.platform == 'darwin':
                    credentials = subprocess.run(
                        ['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                        capture_output=True, text=True, timeout=15)
                    record = json.loads(credentials.stdout) if credentials.returncode == 0 else {}
                else:
                    record = json.loads((home/'.claude/.credentials.json').read_text())
                oauth = record.get('claudeAiOauth')
            except (OSError, ValueError, subprocess.TimeoutExpired):
                oauth = None
            endpoint = claude_endpoint(settings, os.environ, oauth, time.time())
        claude.update(route=endpoint['route'], reason=endpoint['reason'])
        if endpoint['route'] == 'official':
            kind = endpoint['credential_kind']
            if kind == 'oauth':
                credential = oauth['accessToken']
            else:
                name = 'ANTHROPIC_API_KEY' if kind == 'api_key' else 'ANTHROPIC_AUTH_TOKEN'
                credential = os.environ.get(name) or settings.get('env', {}).get(name)
            headers = {'anthropic-version': '2023-06-01'}
            if kind == 'api_key':
                headers['x-api-key'] = credential
            else:
                headers.update(Authorization='Bearer ' + credential,
                               **{'anthropic-beta': 'oauth-2025-04-20'})
            request = urllib.request.Request(endpoint['base_url'].rstrip('/') + '/v1/models?limit=1000',
                                             headers=headers)
            with urllib.request.urlopen(request, timeout=15) as response:
                claude['models'] = claude_models(json.load(response))
    except urllib.error.HTTPError as error:
        claude.update(route=None, reason=(
            '请先打开 Claude Code 完成登录后重新核对' if error.code in (401, 403)
            else '无法读取 Claude 官方模型清单'))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        claude.update(route=None, reason='无法读取 Claude 官方模型清单')
    return result


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
    recovery = {}
    if document.get("version") in (6, 7, 8) and task in CLI_REQUIRED_WORK:
        explicit = task in IMPLEMENTATION_TASKS and output_mode == "commit" and (ticket_mode is not None or map_mode is not None)
        recovery = {"recovery_plan": {"plan_version": 1, "source": "explicit_mode" if explicit else "work",
                    "primary": triple(entry), "fallbacks": [] if explicit else [triple(x) for x in entry["fallbacks"]]},
                    "recovery_progress": {"current_index": None, "next_cursor": 0}}
    plan = {
        **recovery,
        "version": 5,
        "task": task,
        "agent": entry["agent"],
        "model": entry["model"],
        "effort": entry["effort"],
    }
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
    resolved = {**plan, "mode": "direct", "mode_name": None, "phase": "direct", "source": source}
    if requested is not None:
        # 票/map 显式点名：命名 mode 的 per-agent direct 计划整体覆盖。
        mode = document["modes"].get(requested)
        if mode is None:
            raise ValueError(
                f"{source} execution mode is not a configured mode name: {requested}"
            )
        agent_plan = mode["agents"].get(entry["agent"])
        if agent_plan is None:
            raise ValueError(
                f"mode {requested} has no agents plan for {entry['agent']}"
            )
        resolved = {**resolved, "mode_name": requested, **agent_plan["direct"]}
        if recovery:
            resolved["recovery_plan"]["primary"] = triple(resolved)
    if evidence is None:
        return {**resolved, "capability": "unknown"}
    errors = capability_errors(
        resolved["agent"], resolved["model"], resolved["effort"], evidence
    )
    if errors:
        raise ValueError("; ".join(errors))
    return {**resolved, "capability": "verified"}


def resolve_review_plan(document, *, required_axes, implementations, evidence,
                        native_capabilities, request_id, round_context=None):
    """whole-change 纯解析；先核验完整参与池，再按用户顺序选择。"""
    errors = validate_document(document)
    if errors:
        raise ValueError("; ".join(errors))
    axes = list(required_axes)
    if not request_id or not axes or len(set(axes)) != len(axes) or any(a not in REVIEW_AXES for a in axes):
        raise ValueError("review requires request_id and distinct required axes")
    if round_context is not None and (
            round_context.get('action') != 'plan' or round_context.get('required_axes') != axes
            or round_context.get('implementations') != implementations
            or round_context.get('request_id') != request_id):
        raise ValueError('review round context/axes/implementations mismatch')
    participating = list(dict.fromkeys(["standards", *axes]))
    family_evidence = []
    def family(identity):
        declaration = (family_declaration(document, identity.get("agent"), identity.get("model"))
                       if identity else None)
        vendor = model_vendor(document, identity.get("agent"), identity.get("model", "")) if identity else None
        item = {"identity": identity, "declaration": declaration, "source": "declared_at_review",
                "vendor_source": "user_declared" if declaration else "vendor_table" if vendor else "unknown"}
        if item not in family_evidence:
            family_evidence.append(item)
        return vendor

    observed = [(i.get("executed") if i.get("executed") is not None else i.get("requested"),
                 "executed" if i.get("executed") is not None else "requested") for i in implementations]
    bases = {basis for _, basis in observed}
    basis = next(iter(bases)) if len(bases) == 1 else "mixed" if bases else "unknown"
    implementation_families = [family(identity) for identity, _ in observed]
    implementation_evidence = [
        {"lane_id": item.get("lane_id"), "requested": item.get("requested"),
         "executed": item.get("executed"), "identity": identity, "basis": source,
         "declaration": (family_declaration(document, identity.get("agent"), identity.get("model"))
                         if identity else None), "source": "declared_at_review"}
        for item, (identity, source) in zip(implementations, observed)]
    def compare(identity):
        declared = family(identity)
        if declared is None or not implementation_families:
            return "unknown"
        if declared in implementation_families:
            return "same"
        return "different" if all(implementation_families) else "unknown"

    # 非空池必须绑定本轮 probe 与逐项 NativeCapability；缺项不能当 unavailable。
    checked = {}
    for axis in participating:
        cell = document["review"]["whole-change"][axis]
        if not cell.get("candidates"):
            continue
        prefix = "review_capability_evidence_required: " + axis
        if (not isinstance(evidence, dict) or evidence.get("request_id") != request_id
                or not evidence.get("observed_at") or not isinstance(evidence.get("sources"), dict)):
            raise ValueError(prefix + " current probe required")
        pool = [triple(cell), *cell["candidates"]]
        native = native_capabilities.get(axis) if isinstance(native_capabilities, dict) else None
        if not isinstance(native, list) or len(native) != len(pool):
            raise ValueError(prefix + " complete ordered native evidence required")
        attempts = []
        for index, (identity, capability) in enumerate(zip(pool, native)):
            source = evidence["sources"].get(identity["agent"], {})
            if (source.get("status") != "ok" or not isinstance(capability, dict)
                    or capability.get("identity") != identity or not capability.get("evidence_id")
                    or capability.get("status") not in ("runnable", "unavailable")):
                raise ValueError(prefix + " exact current evidence required")
            probe_map = evidence.get("capabilities")
            probe_agent = probe_map.get(identity["agent"]) if isinstance(probe_map, dict) else None
            if (not isinstance(probe_agent, dict) or not isinstance(probe_agent.get("binary"), bool)
                    or not isinstance(probe_agent.get("models"), dict)):
                raise ValueError(prefix + " complete probe source required")
            errors = capability_errors(**identity, evidence=evidence.get("capabilities"))
            if capability["status"] == "runnable" and errors:
                raise ValueError(prefix + "; " + "; ".join(errors))
            if capability["status"] == "unavailable" and not capability.get("reason"):
                raise ValueError(prefix + " unavailable requires positive reason")
            attempts.append({"index": index, "identity": identity, "status": capability["status"],
                "reason": capability.get("reason"), "comparison": compare(identity),
                "comparison_basis": basis, "native_evidence_id": capability["evidence_id"]})
        checked[axis] = attempts

    def select(axis):
        cell = document["review"]["whole-change"][axis]
        if cell.get("candidates"):
            attempts = checked[axis]
            runnable = [a for a in attempts if a["status"] == "runnable"]
            if not runnable:
                raise ValueError("review_no_runnable_candidate: " + json.dumps(attempts))
            pool = [a["identity"] for a in attempts]
            index, outcome = choose_review_candidate(pool,
                [a["status"] == "runnable" for a in attempts],
                [family(identity) for identity in pool], implementation_families)
            different = outcome == "different"
            selected = attempts[index]
            for attempt in attempts:
                if attempt["status"] == "runnable":
                    attempt["reason"] = ("selected" if attempt["index"] == selected["index"] else
                        "different_family_preferred" if attempt["comparison"] != "different" and different else "later_in_user_order")
            return {"selected": selected["identity"], "selected_index": selected["index"],
                "comparison": selected["comparison"], "comparison_basis": basis,
                "fallback": "none" if different else "no_different_family_candidate", "attempts": attempts,
                "probe_evidence_id": evidence.get("evidence_id", request_id),
                "native_evidence_ids": [a["native_evidence_id"] for a in attempts]}
        selected = triple(cell)
        errors = capability_errors(**selected, evidence=(evidence.get("capabilities", evidence)
                                    if isinstance(evidence, dict) else evidence))
        if errors:
            raise ValueError("; ".join(errors))
        return {"selected": selected, "selected_index": 0, "comparison": "unknown",
                "comparison_basis": "unknown", "fallback": "single_model",
                "attempts": [{"index": 0, "identity": selected, "status": "runnable",
                              "reason": "single_model", "comparison": "unknown"}],
                "probe_evidence_id": None, "native_evidence_ids": []}
    lane = select("standards")
    selections = {a: lane if a == "standards" else select(a) for a in axes}
    return json.loads(json.dumps({"scope": "whole-change", "required_axes": axes,
        "config_hash": hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False,
                                                  separators=(",", ":")).encode()).hexdigest(),
        "request_id": request_id, "implementations": implementations,
        "lane": lane, "axes": selections, "family_evidence": family_evidence,
        "implementation_evidence": implementation_evidence,
        **({"round_context": round_context} if round_context is not None else {})}))


def load_review_native_capabilities(path, request_id):
    """读取 Adapter 本轮只读证据；不探测、不生成成功结论。"""
    if not path:
        return {}
    value = json.loads(Path(path).expanduser().read_text())
    if (not isinstance(value, dict) or value.get('request_id') != request_id
            or not value.get('observed_at') or not isinstance(value.get('capabilities'), dict)):
        raise ValueError('review_capability_evidence_required: current native preflight required')
    return value['capabilities']


def review_start_plan(review_plan, evidence):
    """仅复核冻结 lane 目标；不读取配置或重选。"""
    selected = review_plan["lane"]["selected"]
    errors = capability_errors(**selected, evidence=(evidence.get("capabilities", evidence)
                                if isinstance(evidence, dict) else evidence))
    if errors:
        raise ValueError("; ".join(errors))
    return {**selected, "mode": "none", "mode_name": None, "phase": "direct",
            "source": "review.whole-change.standards", "capability": "verified",
            "review_plan": review_plan}


def freeze_overlay(plan: dict) -> dict:
    """返回 coordinator 写入 packet 与 registry 的唯一计划 overlay。"""
    recovery = {k: json.loads(json.dumps(plan[k])) for k in ("recovery_plan", "recovery_progress") if k in plan}
    overlay = {
        **recovery,
        **({"review_plan": plan["review_plan"]} if "review_plan" in plan else {}),
        "mode": plan.get("mode_name"),
        "agent": plan["agent"],
        "model": plan.get("model"),
        "effort": plan.get("effort"),
    }

    recover_overlay(overlay)
    return overlay


def verify_overlay(plan: dict, overlay: object) -> dict:
    expected = freeze_overlay(plan)
    if overlay != expected:
        raise ValueError("packet/registry execution plan readback mismatch")
    return expected


def recover_overlay(row: dict) -> dict:
    """只验证持久计划与位置；无计划旧 row 沿 ADR-0023，不解析配置。"""
    if "recovery_plan" not in row:
        if "recovery_progress" in row:
            raise ValueError("invalid_recovery_plan: progress without plan")
        return {"status": "legacy", **{k: row.get(k) for k in ("mode", "agent", "model", "effort")}}
    plan, progress = row["recovery_plan"], row.get("recovery_progress")
    if not isinstance(plan, dict) or set(plan) != {"plan_version", "source", "primary", "fallbacks"}:
        raise ValueError("invalid_recovery_plan: shape")
    if type(plan["plan_version"]) is not int or plan["plan_version"] != 1:
        raise ValueError("invalid_recovery_plan: version")
    if plan["source"] not in {"work", "explicit_mode"} or not isinstance(plan["fallbacks"], list):
        raise ValueError("invalid_recovery_plan: source/list")
    if plan["source"] == "explicit_mode" and plan["fallbacks"]:
        raise ValueError("invalid_recovery_plan: explicit mode fallbacks")
    if (plan["source"] == "explicit_mode") != (row.get("mode") not in (None, "none")):
        raise ValueError("invalid_recovery_plan: mode/source mismatch")
    entries = [plan["primary"], *plan["fallbacks"]]
    for entry in entries:
        if _entry_errors("recovery triple", entry, CLI_AGENTS):
            raise ValueError("invalid_recovery_plan: triple")
    if not isinstance(progress, dict) or set(progress) != {"current_index", "next_cursor"}:
        raise ValueError("invalid_recovery_plan: progress")
    current, cursor = progress["current_index"], progress["next_cursor"]
    valid_position = ((current is None and cursor == 0) or
                      (type(current) is int and 0 <= current < len(plan["fallbacks"]) and cursor == current + 1))
    if type(cursor) is not int or not valid_position:
        raise ValueError("invalid_recovery_plan: position")
    selected = plan["primary"] if current is None else plan["fallbacks"][current]
    if {k: row.get(k) for k in ("agent", "model", "effort")} != selected:
        raise ValueError("invalid_recovery_plan: current triple mismatch")
    return json.loads(json.dumps({"status": "frozen", "recovery_plan": plan, "recovery_progress": progress,
                                 **{k: row.get(k) for k in ("mode", "agent", "model", "effort")}}))


def recover_registry(path: Path, lane_id: str | None = None) -> dict:
    # 沿用共享 Registry 的块解析；计划字段采用 JSON flow value。
    import importlib.util
    parser_path = Path(__file__).resolve().parents[2] / "delivery-pipeline/scripts/lane_graph.py"
    spec = importlib.util.spec_from_file_location("lane_graph", parser_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = list({row["lane_id"]: row for row in module.parse_registry_file(path)}.values())
    rows = [row for row in rows if lane_id is None or row["lane_id"] == lane_id]
    if len(rows) != 1:
        raise ValueError("registry recovery requires exactly one matching lane")
    row = rows[0]
    for key in ("recovery_plan", "recovery_progress"):
        if key in row and isinstance(row[key], str):
            row[key] = json.loads(row[key])
    return recover_overlay(row)


def startup_request(plan: dict, *, worker_name: str, pane_id: str) -> list[str]:
    """构造 Herdr 原生请求；所有 startup 都要求当前 capability evidence。"""
    if plan.get("mode") not in {"none", "direct"}:
        raise ValueError("execution plan is not runnable")
    if plan.get("capability") != "verified":
        raise ValueError("capability evidence is required before startup")
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
    work = {task: {"agent": "pi", **pair, "fallbacks": []} for task in sorted(CLI_REQUIRED_WORK)}
    return {
        "version": 6,
        "work": work,
        "modes": {
            "standard": {
                "kind": "direct",
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
            scope: {axis: {"agent": "pi", **pair, "candidates": []} for axis in REVIEW_AXES}
            for scope in REVIEW_SCOPES
        },
    }


def valid_app_fixture() -> dict:
    pair = {"agent": "codex-app", "model": "provider/model", "effort": "high"}
    return {
        "version": 5,
        "default_mode": "standard",
        "work": {task: dict(pair) for task in sorted(APP_REQUIRED_WORK)},
        "modes": {
            "standard": {
                "kind": "direct",
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
    }


def self_test() -> list[str]:
    failures: list[str] = []
    fixture = valid_fixture()
    if validate_document(fixture):
        failures.append("valid v5 CLI fixture was rejected")
    if validate_document(valid_app_fixture(), "app"):
        failures.append("valid v5 App fixture was rejected")
    if not validate_document(valid_app_fixture()):
        failures.append("App fixture was accepted as CLI config")
    case = valid_fixture()
    case["default_mode"] = "standard"
    if not validate_document(case):
        failures.append("CLI config with default_mode was accepted")
    case = valid_app_fixture()
    case["modes"]["standard"]["kind"] = "staged"
    if not validate_document(case, "app"):
        failures.append("staged App mode was accepted after Prewalk retirement")
    case = valid_app_fixture()
    case["modes"] = {}
    if not validate_document(case, "app"):
        failures.append("App config with empty modes was accepted")

    evidence = {
        agent: {"binary": True, "models": {"provider/model": ["low", "high", "medium"]}}
        for agent in sorted(CLI_AGENTS)
    }
    default_direct = resolve_plan(fixture, "frontend", output_mode="commit")
    if (
        default_direct["mode"] != "direct"
        or default_direct["mode_name"] is not None
        or (default_direct["model"], default_direct["effort"])
        != ("provider/model", "high")
    ):
        failures.append("work entry without execution did not run direct")
    case = json.loads(json.dumps(fixture))
    case["work"]["frontend"]["model"] = "other/model"
    if resolve_plan(case, "frontend", output_mode="commit")["model"] != "other/model":
        failures.append("same-agent task types did not keep independent starting")
    if resolve_plan(fixture, "backend")["mode"] != "none":
        failures.append("missing output mode enabled implementation phases")
    if (
        resolve_plan(fixture, "backend", map_mode="standard", output_mode="commit")[
            "mode_name"
        ]
        != "standard"
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
        selected["mode"] != "direct"
        or selected["effort"] != "low"
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
        resolve_plan(case, "backend", ticket_mode="standard", output_mode="commit")
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
            "effort": "high", "fallbacks": [],
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
    case = valid_app_fixture()
    case["legacy_execution"] = {}
    cases["legacy-in-app"] = case
    case = valid_fixture()
    case["default_mode"] = "missing"
    cases["default-mode-in-cli"] = case
    case = valid_app_fixture()
    case["default_mode"] = "missing"
    cases["unknown-default-mode-app"] = case
    case = valid_fixture()
    del case["review"]["implementation"]["spec"]
    cases["missing-review-axis"] = case
    case = valid_fixture()
    case["modes"]["standard"]["agents"]["pi"]["starting"] = {"model": "provider/model"}
    cases["missing-stage-field"] = case
    case = valid_fixture()
    case["modes"]["standard"]["kind"] = "bogus"
    cases["bogus-kind"] = case
    case = valid_fixture()
    case["modes"]["standard"]["kind"] = "staged"
    cases["staged-in-cli"] = case
    case = valid_fixture()
    case["work"]["backend"]["execution"] = {"model": "provider/model", "effort": "medium"}
    cases["work-execution-in-cli"] = case
    case = valid_app_fixture()
    case["work"]["planning"]["agent"] = "pi"
    cases["cli-agent-in-app"] = case

    for name, document in cases.items():
        transport = (
            "app"
            if name in ("cli-agent-in-app", "unknown-default-mode-app")
            else "cli"
        )
        if not validate_document(document, transport):
            failures.append(f"invalid fixture accepted: {name}")

    # 迁移：CLI v2/v3/v4 与 App v1/v4 → v5，结果必须通过对应 transport 验证。
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
        or migrated["version"] != 8
        or "default_mode" in migrated
        or migrated["modes"] != {}
    ):
        failures.append("v2 migration did not produce a valid v5 config")
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
        migrated["version"] != 8
        or "default_mode" in migrated
        or validate_document(migrated)
        or "execution" in migrated["work"]["backend"]
    ):
        failures.append("v3 migration did not produce a valid v5 config")
    split_v3 = json.loads(json.dumps(legacy_v3))
    split_v3["execution"]["pi"]["execution"] = {"model": "provider/model", "effort": "low"}
    try:
        migrate_document(split_v3)
    except ValueError:
        pass
    else:
        failures.append("legacy staged execution was migrated instead of rejected")
    mixed = json.loads(json.dumps(legacy_v3))
    mixed["execution"]["codex"]["default_mode"] = "direct"
    migrated, _ = migrate_document(mixed)
    if validate_document(migrated):
        failures.append("mixed legacy default_mode did not migrate per entry")
    conflict_v3 = json.loads(json.dumps(legacy_v3))
    conflict_v3["execution"]["pi"]["starting"] = {
        "model": "other/model",
        "effort": "low",
    }
    try:
        migrate_document(conflict_v3)
    except ValueError:
        pass
    else:
        failures.append("legacy role/starting conflict was silently migrated")
    divergent_v2 = json.loads(json.dumps(legacy_v2))
    divergent_v2["roles"]["frontend"] = {
        "agent": "pi",
        "model": "other/model",
        "effort": "low",
    }
    migrated, _ = migrate_document(divergent_v2)
    if migrated["work"]["frontend"]["model"] != "other/model":
        failures.append("v5 migration did not keep per-task starting models")
    legacy_v4 = valid_fixture()
    legacy_v4["version"] = 4
    for c in legacy_v4["work"].values(): c.pop("fallbacks", None)
    for axes in legacy_v4["review"].values():
        for c in axes.values(): c.pop("candidates", None)
    legacy_v4["default_mode"] = "standard"
    legacy_v4["modes"]["standard"]["kind"] = "staged"
    for agent_plan in legacy_v4["modes"]["standard"]["agents"].values():
        agent_plan["starting"] = {"model": "provider/model", "effort": "high"}
        agent_plan["execution"] = {"model": "provider/model", "effort": "high"}
    migrated, transport = migrate_document(json.loads(json.dumps(legacy_v4)))
    if (
        transport != "cli"
        or migrated["version"] != 8
        or "default_mode" in migrated
        or validate_document(migrated)
        or "execution" in migrated["work"]["backend"]
        or migrated["modes"]["standard"]["kind"] != "direct"
    ):
        failures.append("v4 CLI migration did not produce a direct-only v5 config")
    for field, value in (
        ("model", "other/model"),
        ("execution", {"model": "provider/model", "effort": "medium"}),
    ):
        conflict_v4 = json.loads(json.dumps(legacy_v4))
        if field == "model":
            conflict_v4["work"]["backend"]["model"] = value
        else:
            for agent_plan in conflict_v4["modes"]["standard"]["agents"].values():
                agent_plan["execution"] = value
        try:
            migrate_document(conflict_v4)
        except ValueError:
            pass
        else:
            failures.append(f"v4 staged {field} conflict was silently migrated")
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
        failures.append("App v1 migration did not produce a valid v5 config")
    if (
        migrated["modes"]["astra-sol"]["agents"]["codex-app"]["execution"]["model"]
        != "provider/model"
    ):
        failures.append("App v1 migration lost a phase plan")
    if migrated["work"]["coordinator"]["agent"] != "codex-app":
        failures.append("App v1 migration did not bind the codex-app agent")
    legacy_app_v4 = valid_app_fixture()
    legacy_app_v4["version"] = 4
    migrated, transport = migrate_document(legacy_app_v4)
    if transport != "app" or migrated["version"] != 5:
        failures.append("App v4 migration did not bump the version")
    v7 = {**valid_fixture(), "version": 7, "model_families": {}}
    v8 = migrate_document(v7)[0]
    if v8["dispatch"] != DEFAULT_LIMITS or migrate_document(v8)[0] != v8:
        failures.append("v7 repeated migration changed configuration")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "model-roles.json"
        path.write_text(json.dumps(legacy_v3), encoding="utf-8")
        result = migrate_path(path)
        readback = json.loads(path.read_text(encoding="utf-8"))
        if result["default_mode"] is not None or validate_document(readback):
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
            "show",
            "preview-review",
            "self-test",
            "resolve",
            "freeze",
            "recover",
            "start",
            "migrate",
            "configure",
            "apply",
            "probe",
        ),
    )
    parser.add_argument(
        "path", nargs="?", default="~/.config/delivery-pipeline/model-roles.json"
    )
    parser.add_argument("task", nargs="?")
    parser.add_argument("--candidate", help="待预览配置 JSON 文件")
    parser.add_argument("--base-hash")
    parser.add_argument("--request-id")
    parser.add_argument("--ticket-mode")
    parser.add_argument("--map-mode")
    parser.add_argument("--output-mode")
    parser.add_argument("--evidence", help="归一化实时能力 evidence JSON")
    parser.add_argument("--native-capabilities", help="本轮 Adapter 原生只读 preflight 证据 JSON")
    parser.add_argument("--worker-name", default="worker")
    parser.add_argument("--pane-id", default="pane")
    parser.add_argument("--review-scope")
    parser.add_argument("--required-axes", nargs="+", choices=list(REVIEW_AXES))
    parser.add_argument("--implementation-registry")
    parser.add_argument("--fixed-point")
    args = parser.parse_args()

    if args.command == "preview-review":
        if not args.candidate or not args.evidence:
            parser.error("preview-review 需要 --candidate 与 --evidence")
        try:
            document = json.loads(Path(args.candidate).expanduser().read_text())
            evidence = json.loads(Path(args.evidence).expanduser().read_text())
            print(json.dumps(preview_review_choice(document, evidence), ensure_ascii=False))
            return 0
        except (OSError, ValueError) as error:
            print(json.dumps({"valid": False, "errors": [str(error)]}, ensure_ascii=False))
            return 1
    if args.command == "recover":
        try:
            print(json.dumps(recover_registry(Path(args.path).expanduser(), args.task), ensure_ascii=False))
            return 0
        except (OSError, ValueError) as error:
            print(json.dumps({"valid": False, "errors": [str(error)]}))
            return 1
    if args.command == "probe":
        raw = json.load(sys.stdin)
        print(json.dumps({"api_version": 1, **probe(raw, args.request_id or "")}, ensure_ascii=False))
        return 0
    if args.command == "show":
        print(json.dumps(show(Path(args.path)), ensure_ascii=False))
        return 0
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
    if args.command in ("configure", "apply"):
        if not args.request_id or not args.evidence:
            parser.error("configure 需要 --request-id 与 --evidence")
        try:
            candidate = json.load(sys.stdin)
            evidence = json.loads(Path(args.evidence).expanduser().read_text())
            result = (apply if args.command == "apply" else configure)(Path(args.path), candidate, args.base_hash, evidence, args.request_id)
        except (OSError, ValueError) as error:
            result = {"status": "rejected", "error": {"code": "invalid_candidate", "message": str(error)}}
        print(json.dumps({"api_version": 1, **result}, ensure_ascii=False))
        return {"applied": 0, "rejected": 1, "commit_unverified": 3}[result["status"]]
    if args.command == "migrate":
        try:
            result = migrate_path(Path(args.path))
        except CommitUnverified as error:
            print(json.dumps({"api_version": 1, **error.result}, ensure_ascii=False))
            return 3
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
        if args.task == "review":
            if (args.review_scope != "whole-change" or args.output_mode != "verdict"
                    or not args.required_axes or not args.request_id or not args.implementation_registry
                    or not args.fixed_point or args.ticket_mode or args.map_mode):
                raise ValueError("review requires whole-change verdict, axes, request_id and Registry fixed point")
            core = Path(__file__).resolve().parents[2] / "delivery-pipeline/scripts"
            sys.path.insert(0, str(core))
            import lane_registry
            implementations = lane_registry.collect_implementation_identities(
                lane_registry.rows(Path(args.implementation_registry)), args.fixed_point)
            review = resolve_review_plan(load_document(Path(args.path)), required_axes=args.required_axes,
                implementations=implementations, evidence=evidence,
                native_capabilities=load_review_native_capabilities(args.native_capabilities, args.request_id), request_id=args.request_id)
            plan = review_start_plan(review, evidence)
        else:
            plan = resolve_plan(load_document(Path(args.path)), args.task,
                ticket_mode=args.ticket_mode, map_mode=args.map_mode, evidence=evidence,
                output_mode=args.output_mode)
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

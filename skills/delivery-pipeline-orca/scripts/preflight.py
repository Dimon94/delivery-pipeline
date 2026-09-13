#!/usr/bin/env python3
"""Orca 入口的只读、operation-scoped preflight；不创建或分派资源。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SETUP_SCRIPTS = ROOT / "skills" / "delivery-pipeline-setup" / "scripts"
MODEL_CONFIG = SETUP_SCRIPTS / "model_config.py"

UNKNOWN = "Unknown"
ORCA_SKILL_NAME = "delivery-pipeline-orca"


class PreflightError(ValueError):
    pass


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip().lower() == "unknown"
    ):
        raise PreflightError(f"{field} 必须是已知非空文本")
    return value.strip()


def resolve_orca_executable(env: dict[str, str] | None = None) -> str:
    """按原生 discovery 规则固定一个 executable；选中失败后不尝试 fallback。"""
    source = os.environ if env is None else env
    configured = source.get("ORCA_CLI_COMMAND")
    if configured:
        candidate = configured.strip()
        if not candidate or any(character.isspace() for character in candidate):
            raise PreflightError("ORCA_CLI_COMMAND 必须只指向一个 executable")
    elif source.get("ORCA_DEV_REPO_ROOT"):
        candidate = "orca-dev"
    elif sys.platform.startswith("linux") and not source.get("ORCA_TERMINAL_HANDLE"):
        candidate = "orca-ide"
    else:
        candidate = "orca"
    selected = (
        candidate
        if Path(candidate).is_absolute()
        else shutil.which(candidate, path=source.get("PATH"))
    )
    if not selected:
        raise PreflightError(f"选定 Orca executable 不可解析: {candidate}")
    try:
        path = Path(selected).expanduser().resolve()
        executable = path.is_file() and os.access(path, os.X_OK)
    except OSError as error:
        raise PreflightError(f"选定 Orca executable 不可读取: {selected}") from error
    if not executable:
        raise PreflightError(f"选定 Orca executable 不可执行: {path}")
    return str(path)


def _decode_json(raw: str, source: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise PreflightError(f"{source} JSON readback 非法: {error}") from error


def _run(executable: str, *arguments: str, json_output: bool = True) -> Any:
    command = arguments + (("--json",) if json_output else ())
    result = subprocess.run(
        [executable, *command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit {result.returncode}"
        )
        raise PreflightError(
            f"Orca readback 失败（不 fallback）: {' '.join(command)}: {detail}"
        )
    if not json_output:
        return _text(result.stdout, "orca --version")
    value = _decode_json(result.stdout, f"Orca {' '.join(command)}")
    if isinstance(value, dict) and "ok" in value:
        if not isinstance(value["ok"], bool) or not value["ok"]:
            raise PreflightError(
                f"Orca readback 拒绝: {' '.join(command)}: {value.get('error')}"
            )
    return value


def _guide(executable: str, name: str) -> dict[str, Any]:
    arguments = ["skills", "get", name, "--full"]
    value = _run(executable, *arguments)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("full"), bool)
        or not value["full"]
        or value.get("name") != name
    ):
        raise PreflightError(f"version-matched {name} full guide 不可读")
    _text(value.get("markdown"), f"{name}.markdown")
    return {
        "name": name,
        "full": True,
        "source": {
            "executable": executable,
            "command": [executable, *arguments, "--json"],
        },
    }


def _reference(executable: str, name: str) -> dict[str, Any]:
    arguments = ["skills", "get", "orchestration", "--reference", name]
    value = _run(executable, *arguments)
    if not isinstance(value, dict) or value.get("name") != "orchestration":
        raise PreflightError(f"orchestration reference 不可读: {name}")
    observed = value.get("reference")
    if observed not in {name, f"references/{name}.md"}:
        raise PreflightError(f"orchestration reference identity 不匹配: {name}")
    _text(value.get("markdown"), f"orchestration reference {name}")
    return {
        "name": observed,
        "source": {
            "executable": executable,
            "command": [executable, *arguments, "--json"],
        },
    }


def _runtime(status: object) -> dict[str, Any]:
    if (
        not isinstance(status, dict)
        or not isinstance(status.get("ok"), bool)
        or not status["ok"]
    ):
        raise PreflightError("Orca status receipt 缺失或失败")
    result = status.get("result")
    runtime = result.get("runtime") if isinstance(result, dict) else None
    if not isinstance(runtime, dict):
        raise PreflightError("Orca runtime readback 缺失")
    if (
        runtime.get("state") != "ready"
        or not isinstance(runtime.get("reachable"), bool)
        or not runtime["reachable"]
        or runtime.get("connectionState") != "connected"
    ):
        raise PreflightError(
            "Orca runtime 非 ready/reachable/connected: "
            f"state={runtime.get('state')}, reachable={runtime.get('reachable')}, "
            f"connectionState={runtime.get('connectionState')}"
        )
    _text(runtime.get("runtimeId"), "runtime.runtimeId")
    capabilities = runtime.get("capabilities")
    if not isinstance(capabilities, list) or any(
        not isinstance(item, str) for item in capabilities
    ):
        raise PreflightError("runtime.capabilities 必须是字符串列表")
    return runtime


def _host(status: object, expected: object, executable: str) -> dict[str, Any]:
    result = status.get("result") if isinstance(status, dict) else None
    runtime = result.get("runtime") if isinstance(result, dict) else None
    target = result.get("target") if isinstance(result, dict) else None
    if not isinstance(target, dict) or not target or not isinstance(runtime, dict):
        raise PreflightError("目标 host identity readback 缺失")
    observed = {
        "target": target,
        "runtimeId": _text(runtime.get("runtimeId"), "host.runtimeId"),
    }
    if not isinstance(expected, dict) or expected != observed:
        raise PreflightError(
            f"目标 host identity 不匹配: expected={expected}, observed={observed}"
        )
    return {
        "identity": observed,
        "source": {
            "executable": executable,
            "command": [executable, "status", "--json"],
        },
    }


def _commands(context: object) -> dict[str, set[str]]:
    if not isinstance(context, dict) or not isinstance(context.get("commands"), list):
        raise PreflightError("agent-context commands readback 缺失")
    result: dict[str, set[str]] = {}
    for entry in context["commands"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
            continue
        flags = entry.get("flags")
        result[entry["command"]] = set(flags) if isinstance(flags, list) else set()
    return result


def _discovery(value: object, expected_name: str) -> dict[str, Any]:
    result = value.get("result") if isinstance(value, dict) else None
    skills = result.get("skills") if isinstance(result, dict) else None
    if not isinstance(skills, list):
        raise PreflightError("skills installed readback 缺失")
    matches = [
        item
        for item in skills
        if isinstance(item, dict) and item.get("name") == expected_name
    ]
    if len(matches) != 1:
        raise PreflightError(
            f"skills installed exact name 必须唯一: {expected_name}; observed={len(matches)}"
        )
    item = matches[0]
    for field in ("id", "name", "sourceKind", "sourceLabel"):
        _text(item.get(field), f"discovery.{field}")
    providers = item.get("providers")
    if (
        not isinstance(providers, list)
        or not providers
        or any(not isinstance(provider, str) or not provider for provider in providers)
    ):
        raise PreflightError("discovery.providers 必须是非空字符串列表")
    return {
        field: item[field]
        for field in ("id", "name", "providers", "sourceKind", "sourceLabel")
    }


def _owner(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {
        "name",
        "skill_path",
        "invocation_label",
    }:
        raise PreflightError("owner 必须精确包含 name/skill_path/invocation_label")
    name = _text(value["name"], "owner.name")
    label = _text(value["invocation_label"], "owner.invocation_label")
    path = Path(_text(value["skill_path"], "owner.skill_path")).expanduser()
    if not path.is_absolute() or path.name != "SKILL.md" or not path.is_file():
        raise PreflightError("owner.skill_path 必须是已存在的绝对 SKILL.md 路径")
    realpath = path.resolve()
    match = re.match(r"^---\n(.*?)\n---\n", realpath.read_text(), re.DOTALL)
    frontmatter_name = None
    if match:
        for line in match.group(1).splitlines():
            key, separator, candidate = line.partition(":")
            if separator and key.strip() == "name":
                frontmatter_name = candidate.strip()
                break
    if frontmatter_name != name:
        raise PreflightError(
            f"owner frontmatter name 不匹配: expected={name}, observed={frontmatter_name}"
        )
    return {
        "name": name,
        "skill_path": str(path),
        "realpath": str(realpath),
        "invocation_label": label,
    }


def _model_command(
    request: dict[str, Any], command: str
) -> tuple[dict[str, Any], str, str]:
    """通过既有 setup helper 解析/冻结；不复制 schema，也不调用 Herdr start/resume。"""
    _, config_path = _read_json_file(request["config"], "config")
    _, evidence_path = _read_json_file(request["model_evidence"], "model_evidence")
    arguments = [
        sys.executable,
        str(MODEL_CONFIG),
        command,
        config_path,
        _text(request["task"], "task"),
        "--output-mode",
        _text(request["output_mode"], "output_mode"),
        "--evidence",
        evidence_path,
    ]
    if request.get("ticket_mode") is not None:
        arguments.extend(
            ("--ticket-mode", _text(request["ticket_mode"], "ticket_mode"))
        )
    if request.get("map_mode") is not None:
        arguments.extend(("--map-mode", _text(request["map_mode"], "map_mode")))
    result = subprocess.run(
        arguments,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    value = _decode_json(result.stdout, f"共享 model_config.py {command}")
    invalid = (
        isinstance(value, dict)
        and isinstance(value.get("valid"), bool)
        and not value["valid"]
    )
    if result.returncode or not isinstance(value, dict) or invalid:
        raise PreflightError(f"共享 worker policy {command} blocked: {value}")
    return value, config_path, evidence_path


def _test_config() -> dict[str, Any]:
    pair = {"model": "provider/model", "effort": "high"}
    work = {
        task: {"agent": "pi", **pair}
        for task in ("planning", "design", "frontend", "backend", "testing")
    }
    stages = {
        stage: {"model": "provider/model", "effort": effort}
        for stage, effort in (
            ("starting", "high"),
            ("execution", "medium"),
            ("direct", "low"),
        )
    }
    return {
        "version": 4,
        "default_mode": "standard",
        "work": work,
        "modes": {
            "standard": {
                "kind": "staged",
                "agents": {agent: dict(stages) for agent in ("pi", "codex", "claude")},
            }
        },
        "review": {
            scope: {axis: {"agent": "pi", **pair} for axis in ("standards", "spec")}
            for scope in ("implementation", "whole-change")
        },
    }


def _read_json_file(value: object, field: str) -> tuple[dict[str, Any], str]:
    path = Path(_text(value, field)).expanduser()
    if not path.is_file():
        raise PreflightError(f"{field} 不可读: {path}")
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise PreflightError(f"{field} JSON 非法: {error}") from error
    if not isinstance(document, dict):
        raise PreflightError(f"{field} 必须是 JSON object")
    return document, str(path.resolve())


def _terminal(value: object, expected_handle: str) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("ok"), bool)
        or not value["ok"]
    ):
        raise PreflightError("coordinator terminal readback 失败")
    result = value.get("result")
    terminal = (
        result.get("terminal")
        if isinstance(result, dict) and isinstance(result.get("terminal"), dict)
        else result
    )
    if not isinstance(terminal, dict):
        raise PreflightError("coordinator terminal identity 缺失")
    handle = (
        terminal.get("handle") or terminal.get("terminalHandle") or terminal.get("id")
    )
    if handle != expected_handle:
        raise PreflightError(
            f"coordinator terminal identity 不匹配: expected={expected_handle}, observed={handle}"
        )
    return {"handle": handle, "readback": "terminal show"}


def _evidence_source(value: object, field: str) -> str:
    path = Path(_text(value, field)).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise PreflightError(f"{field} 必须是可读的绝对 evidence 文件")
    return str(path.resolve())


def _matching_readback(
    value: object, plan: dict[str, Any], phase: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreflightError("shared agent/model/effort runtime readback 为 Unknown")
    mode = plan.get("mode")
    allowed_phases = {"starting", "execution"} if mode == "staged" else {"direct"}
    if phase not in allowed_phases:
        raise PreflightError(
            f"phase 与 worker policy 不匹配: mode={mode}, phase={phase}"
        )
    pair = plan.get(phase) if mode == "staged" else plan
    if not isinstance(pair, dict):
        raise PreflightError(f"worker policy 缺少 phase: {phase}")
    expected = {
        "agent": plan["agent"],
        "model": pair["model"],
        "effort": pair["effort"],
    }
    if value.get("status") != "ready" or any(
        value.get(field) != candidate for field, candidate in expected.items()
    ):
        raise PreflightError(
            f"shared agent/model/effort runtime readback 不匹配: expected={expected}"
        )
    return {
        **expected,
        "status": "ready",
        "source": _evidence_source(value.get("source"), "agent_readback.source"),
    }


def _same_session(value: object, agent: str) -> dict[str, str]:
    if not isinstance(value, dict) or value.get("status") != "verified":
        raise PreflightError("staged native same-session capability 为 Unknown")
    if value.get("agent") != agent:
        raise PreflightError("staged same-session agent identity 不匹配")
    return {
        "status": "verified",
        "agent": agent,
        "source": _evidence_source(value.get("source"), "same_session_readback.source"),
    }


def _blocked(
    operation: str,
    error: Exception,
    executable: str | None = None,
    readback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "operation": operation,
        "dispatch": "unavailable",
        "authority": False,
        "evidence_authority": "none; blocked preflight",
        "fallback": False,
        "executable": executable or UNKNOWN,
        "readback": readback or {},
        "blockers": [str(error)],
    }


def preflight(request: object, env: dict[str, str] | None = None) -> dict[str, Any]:
    operation = (
        request.get("operation", UNKNOWN) if isinstance(request, dict) else UNKNOWN
    )
    executable: str | None = None
    readback: dict[str, Any] = {"observed_at": datetime.now(timezone.utc).isoformat()}
    try:
        if not isinstance(request, dict):
            raise PreflightError("request 顶层必须是 object")
        required = {
            "operation",
            "skill_name",
            "references",
            "required_commands",
            "required_capabilities",
            "config",
            "model_evidence",
            "task",
            "output_mode",
            "phase",
            "target_host",
            "owner",
            "agent_readback",
            "same_session_readback",
        }
        optional = {"ticket_mode", "map_mode", "terminal_handle"}
        if not required <= set(request) or not set(request) <= required | optional:
            raise PreflightError(
                f"request 字段不匹配: missing={sorted(required - set(request))}, extra={sorted(set(request) - required - optional)}"
            )
        operation = _text(request["operation"], "operation")
        skill_name = _text(request["skill_name"], "skill_name")
        if skill_name != ORCA_SKILL_NAME:
            raise PreflightError(f"skill_name 必须是 {ORCA_SKILL_NAME}")
        references = request["references"]
        required_commands = request["required_commands"]
        required_capabilities = request["required_capabilities"]
        if any(
            not isinstance(items, list)
            for items in (references, required_commands, required_capabilities)
        ):
            raise PreflightError(
                "references/required_commands/required_capabilities 必须是列表"
            )
        references = [_text(item, "references[]") for item in references]
        required_commands = [
            _text(item, "required_commands[]") for item in required_commands
        ]
        required_capabilities = [
            _text(item, "required_capabilities[]") for item in required_capabilities
        ]

        executable = resolve_orca_executable(env)
        readback["executable"] = executable
        version = _run(executable, "--version", json_output=False)
        readback["version"] = version
        guides = [_guide(executable, name) for name in ("orca-cli", "orchestration")]
        readback["guides"] = guides
        loaded_references = [_reference(executable, name) for name in references]
        readback["references"] = loaded_references
        command_readback = _commands(_run(executable, "agent-context"))
        readback["available_commands"] = sorted(command_readback)
        missing_commands = sorted(set(required_commands) - set(command_readback))
        if missing_commands:
            raise PreflightError(
                f"当前 operation 缺少 Orca command capability: {missing_commands}"
            )
        status_readback = _run(executable, "status")
        runtime = _runtime(status_readback)
        host = _host(status_readback, request["target_host"], executable)
        readback["runtime"] = {
            "state": runtime["state"],
            "reachable": runtime["reachable"],
            "connectionState": runtime["connectionState"],
            "runtimeId": runtime["runtimeId"],
        }
        readback["host"] = host
        readback["runtime_capabilities"] = runtime["capabilities"]
        missing_capabilities = sorted(
            set(required_capabilities) - set(runtime["capabilities"])
        )
        if missing_capabilities:
            raise PreflightError(
                f"当前 operation 缺少 runtime capability: {missing_capabilities}"
            )

        discovery = _discovery(_run(executable, "skills", "installed"), skill_name)
        readback["discovery"] = discovery
        owner = _owner(request["owner"])
        readback["owner"] = owner
        plan, config_path, evidence_path = _model_command(request, "resolve")
        frozen, _, _ = _model_command(request, "freeze")
        readback["worker_policy"] = {
            "config": config_path,
            "model_evidence": evidence_path,
            "plan": plan,
            "frozen": frozen,
        }

        source = os.environ if env is None else env
        terminal_handle = _text(
            source.get("ORCA_TERMINAL_HANDLE"), "current Orca terminal identity"
        )
        expected_terminal = request.get("terminal_handle")
        if (
            expected_terminal is not None
            and _text(expected_terminal, "terminal_handle") != terminal_handle
        ):
            raise PreflightError("request/current Orca terminal identity 不一致")
        terminal = _terminal(
            _run(executable, "terminal", "show", "--terminal", terminal_handle),
            terminal_handle,
        )
        readback["terminal"] = terminal
        phase = _text(request["phase"], "phase")
        agent_readback = _matching_readback(request["agent_readback"], plan, phase)
        same_session = None
        if plan.get("mode") == "staged":
            command = command_readback.get("orchestration worker-start")
            if command is None or "terminal" not in command:
                raise PreflightError(
                    "staged native same-session command/--terminal capability 缺失"
                )
            same_session = _same_session(
                request["same_session_readback"], plan["agent"]
            )
        return {
            "ok": True,
            "status": "ready",
            "dispatch": "preflight-ready",
            "authority": False,
            "evidence_authority": "caller-declared; coordinator must validate native provenance",
            "fallback": False,
            "operation": operation,
            "executable": executable,
            "version": version,
            "observed_at": readback["observed_at"],
            "runtime": {
                "state": runtime["state"],
                "reachable": runtime["reachable"],
                "connectionState": runtime["connectionState"],
                "runtimeId": runtime["runtimeId"],
            },
            "terminal": terminal,
            "host": host,
            "guides": guides,
            "references": loaded_references,
            "capabilities": {
                "commands": required_commands,
                "runtime": required_capabilities,
            },
            "discovery": discovery,
            "owner": owner,
            "worker_policy": {
                "config": config_path,
                "model_evidence": evidence_path,
                "plan": plan,
                "frozen": frozen,
                "runtime_readback": agent_readback,
                "same_session": same_session,
            },
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return _blocked(str(operation), error, executable, readback)


def self_test() -> None:
    """用临时 executable 验证 ready、缺能力和 no-fallback 三个外部 seam。"""
    import tempfile

    fake = """#!/usr/bin/env python3
import json, os, sys
args = [item for item in sys.argv[1:] if item != '--json']
log = os.environ.get('FAKE_ORCA_LOG')
if log:
    with open(log, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(args) + '\\n')
if args == ['--version']:
    print('9.9.9')
elif args[:2] == ['skills', 'get']:
    name = args[2]
    if '--reference' in args:
        ref = args[args.index('--reference') + 1]
        print(json.dumps({'name': name, 'reference': ref, 'markdown': '# reference'}))
    else:
        print(json.dumps({'name': name, 'full': True, 'markdown': '# guide'}))
elif args == ['agent-context']:
    print(json.dumps({'schemaVersion': 1, 'commands': [
        {'command': 'orchestration worker-start', 'flags': ['terminal']},
        {'command': 'status'},
    ]}))
elif args == ['status']:
    if os.environ.get('FAKE_ORCA_FAIL'):
        raise SystemExit(7)
    print(json.dumps({'ok': True, 'result': {
        'target': {'kind': 'local'},
        'runtime': {
            'state': 'ready', 'reachable': True, 'connectionState': 'connected',
            'runtimeId': 'runtime-test', 'capabilities': ['runtime.test'],
        },
    }}))
elif args[:2] == ['skills', 'installed']:
    skills = [] if os.environ.get('FAKE_ORCA_NO_SKILL') else [{
        'id': 'skill-test', 'name': 'delivery-pipeline-orca',
        'providers': ['agent-skills'], 'sourceKind': 'home', 'sourceLabel': 'test home',
    }]
    print(json.dumps({'result': {'skills': skills}}))
elif args[:2] == ['terminal', 'show']:
    print(json.dumps({'ok': True, 'result': {'terminal': {'handle': 'term-test'}}}))
else:
    raise SystemExit(8)
"""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        executable = root / "orca-test"
        executable.write_text(fake)
        executable.chmod(0o755)
        owner = root / "implement" / "SKILL.md"
        owner.parent.mkdir()
        owner.write_text("---\nname: implement\n---\n")
        config_path = root / "config.json"
        config_path.write_text(json.dumps(_test_config()))
        evidence_path = root / "evidence.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "pi": {
                        "binary": True,
                        "models": {"provider/model": ["high", "medium", "low"]},
                    }
                }
            )
        )
        agent_source = root / "agent-readback.json"
        agent_source.write_text("{}")
        session_source = root / "same-session-readback.json"
        session_source.write_text("{}")
        request = {
            "operation": "entry-preflight",
            "skill_name": "delivery-pipeline-orca",
            "references": ["coordinator-loop"],
            "required_commands": ["orchestration worker-start"],
            "required_capabilities": ["runtime.test"],
            "config": str(config_path),
            "model_evidence": str(evidence_path),
            "task": "backend",
            "output_mode": "commit",
            "phase": "starting",
            "terminal_handle": "term-test",
            "target_host": {"target": {"kind": "local"}, "runtimeId": "runtime-test"},
            "owner": {
                "name": "implement",
                "skill_path": str(owner),
                "invocation_label": "/skill:implement",
            },
            "agent_readback": {
                "status": "ready",
                "agent": "pi",
                "model": "provider/model",
                "effort": "high",
                "source": str(agent_source),
            },
            "same_session_readback": {
                "status": "verified",
                "agent": "pi",
                "source": str(session_source),
            },
        }
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request))
        old_command = os.environ.get("ORCA_CLI_COMMAND")
        old_log = os.environ.get("FAKE_ORCA_LOG")
        old_terminal = os.environ.get("ORCA_TERMINAL_HANDLE")
        log = root / "orca.log"
        os.environ["ORCA_CLI_COMMAND"] = str(executable)
        os.environ["FAKE_ORCA_LOG"] = str(log)
        os.environ["ORCA_TERMINAL_HANDLE"] = "term-test"
        try:
            result = preflight(request)
            if (
                not result.get("ok")
                or result.get("dispatch") != "preflight-ready"
                or not isinstance(result.get("authority"), bool)
                or result["authority"]
                or not isinstance(result.get("fallback"), bool)
                or result["fallback"]
            ):
                raise AssertionError(f"ready preflight failed: {result}")
            if result.get("host", {}).get("identity") != request["target_host"]:
                raise AssertionError(f"host identity was not preserved: {result}")
            if not all(
                item.get("source", {}).get("executable") == str(executable.resolve())
                for item in result["guides"] + result["references"]
            ):
                raise AssertionError(
                    f"native guide/reference provenance was not preserved: {result}"
                )
            wrong_skill = preflight({**request, "skill_name": "another-skill"})
            if wrong_skill.get("status") != "blocked":
                raise AssertionError(
                    f"wrong skill entrypoint was accepted: {wrong_skill}"
                )
            missing_host = preflight({**request, "target_host": None})
            if missing_host.get("status") != "blocked":
                raise AssertionError(
                    f"missing host identity was not blocked: {missing_host}"
                )
            mismatched_host = preflight(
                {
                    **request,
                    "target_host": {
                        "target": {"kind": "remote"},
                        "runtimeId": "runtime-other",
                    },
                }
            )
            if mismatched_host.get("status") != "blocked":
                raise AssertionError(
                    f"mismatched host identity was not blocked: {mismatched_host}"
                )
            wrong_owner_file = root / "implement" / "OWNER.md"
            wrong_owner_file.write_text(owner.read_text())
            wrong_owner = preflight(
                {
                    **request,
                    "owner": {**request["owner"], "skill_path": str(wrong_owner_file)},
                }
            )
            if wrong_owner.get("status") != "blocked":
                raise AssertionError(
                    f"non-SKILL.md owner path was accepted: {wrong_owner}"
                )
            missing = preflight(
                {**request, "required_capabilities": ["missing.capability"]}
            )
            if (
                missing.get("status") != "blocked"
                or missing.get("dispatch") != "unavailable"
                or not isinstance(missing.get("fallback"), bool)
                or missing["fallback"]
            ):
                raise AssertionError(f"missing capability was not blocked: {missing}")
            missing_command = preflight(
                {**request, "required_commands": ["orchestration missing"]}
            )
            if missing_command.get("status") != "blocked":
                raise AssertionError(
                    f"missing command was not blocked: {missing_command}"
                )
            missing_agent = preflight({**request, "agent_readback": None})
            if missing_agent.get("status") != "blocked":
                raise AssertionError(
                    f"Unknown shared agent was not blocked: {missing_agent}"
                )
            inline_agent = preflight(
                {
                    **request,
                    "agent_readback": {
                        **request["agent_readback"],
                        "source": "inline-claim",
                    },
                }
            )
            if inline_agent.get("status") != "blocked":
                raise AssertionError(f"inline agent claim was accepted: {inline_agent}")
            missing_session = preflight({**request, "same_session_readback": None})
            if missing_session.get("status") != "blocked":
                raise AssertionError(
                    f"Unknown same-session capability was not blocked: {missing_session}"
                )
            mismatched_identity = preflight(
                {**request, "terminal_handle": "term-other"}
            )
            if mismatched_identity.get("status") != "blocked":
                raise AssertionError(
                    f"mismatched identity was not blocked: {mismatched_identity}"
                )
            invalid_config = root / "invalid-config.json"
            invalid_config.write_text("{}")
            invalid_policy = preflight({**request, "config": str(invalid_config)})
            if invalid_policy.get("status") != "blocked":
                raise AssertionError(
                    f"invalid shared config was not blocked: {invalid_policy}"
                )
            os.environ["FAKE_ORCA_NO_SKILL"] = "1"
            missing_discovery = preflight(request)
            os.environ.pop("FAKE_ORCA_NO_SKILL")
            if missing_discovery.get("status") != "blocked":
                raise AssertionError(
                    f"missing exact discovery was not blocked: {missing_discovery}"
                )
            os.environ["FAKE_ORCA_FAIL"] = "1"
            failed = preflight(request)
            if (
                failed.get("status") != "blocked"
                or not isinstance(failed.get("fallback"), bool)
                or failed["fallback"]
            ):
                raise AssertionError(f"failed fixed executable fell through: {failed}")
            commands = [json.loads(line) for line in log.read_text().splitlines()]
            if any(
                "worker-start" in command or "task-create" in command
                for command in commands
            ):
                raise AssertionError(
                    "preflight invoked a mutating orchestration command"
                )
        finally:
            if old_command is None:
                os.environ.pop("ORCA_CLI_COMMAND", None)
            else:
                os.environ["ORCA_CLI_COMMAND"] = old_command
            if old_log is None:
                os.environ.pop("FAKE_ORCA_LOG", None)
            else:
                os.environ["FAKE_ORCA_LOG"] = old_log
            if old_terminal is None:
                os.environ.pop("ORCA_TERMINAL_HANDLE", None)
            else:
                os.environ["ORCA_TERMINAL_HANDLE"] = old_terminal
            os.environ.pop("FAKE_ORCA_FAIL", None)
            os.environ.pop("FAKE_ORCA_NO_SKILL", None)


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "self-test":
        self_test()
        print(json.dumps({"valid": True}, ensure_ascii=False))
        return 0
    if len(sys.argv) != 3 or sys.argv[1] != "run":
        print(f"Usage: {Path(sys.argv[0]).name} run <request.json>", file=sys.stderr)
        return 2
    try:
        request = json.loads(Path(sys.argv[2]).expanduser().read_text())
    except (OSError, json.JSONDecodeError) as error:
        result = _blocked(UNKNOWN, error)
    else:
        result = preflight(request)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

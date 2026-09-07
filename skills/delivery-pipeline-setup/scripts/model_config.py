#!/usr/bin/env python3
import argparse
import json
import sys
import tempfile
from pathlib import Path

CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "delivery-pipeline" / "scripts"
sys.path.insert(0, str(CORE_SCRIPTS))
from pi_adapter import PiAdapterError, build_start_command

ROLES = {"planning", "design", "frontend", "backend", "testing", "review"}
AGENTS = {"pi", "codex", "claude"}
FIELDS = {"agent", "model", "effort"}
TOP_LEVEL = {"version", "roles"}
IMPLEMENTATION_ROLES = {"design", "frontend", "backend"}
MODES = {"staged", "direct"}
STAGES = ("starting", "execution", "direct")
EXECUTION_FIELDS = {"default_mode", *STAGES}


def validate_document(document: object) -> list[str]:
    """只检查结构，不探测或修改用户配置。"""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level value must be an object"]
    version = document.get("version")
    top_level = TOP_LEVEL | {"execution"} if version == 3 else TOP_LEVEL
    if set(document) != top_level:
        errors.append(f"top-level keys must be exactly {sorted(top_level)}")
    if type(version) is not int or version not in (2, 3):
        errors.append("version must equal 2 or 3")
    if version == 3:
        execution = document.get("execution")
        if not isinstance(execution, dict) or set(execution) != AGENTS:
            errors.append(f"execution must define exactly {sorted(AGENTS)}")
        else:
            for agent, plan in sorted(execution.items()):
                prefix = f"execution.{agent}"
                if not isinstance(plan, dict):
                    errors.append(f"{prefix} must be an object")
                    continue
                if set(plan) != EXECUTION_FIELDS:
                    errors.append(f"{prefix} must define default_mode, starting, execution, direct")
                if plan.get("default_mode") not in MODES:
                    errors.append(f"{prefix}.default_mode must equal staged or direct")
                for stage in STAGES:
                    pair = plan.get(stage)
                    if not isinstance(pair, dict) or set(pair) != {"model", "effort"}:
                        errors.append(f"{prefix}.{stage} must define exactly model and effort")
                        continue
                    for field, candidate in pair.items():
                        if not isinstance(candidate, str) or not candidate.strip() or candidate.strip().lower() == "unknown":
                            errors.append(f"{prefix}.{stage}.{field} must be a known non-empty string")
    roles = document.get("roles")
    if not isinstance(roles, dict):
        errors.append("roles must be an object")
        return errors
    if set(roles) != ROLES:
        errors.append(f"role keys must be exactly {sorted(ROLES)}")
    for role in sorted(ROLES & set(roles)):
        value = roles[role]
        if not isinstance(value, dict):
            errors.append(f"roles.{role} must be an object")
            continue
        if set(value) != FIELDS:
            errors.append(f"roles.{role} keys must be exactly {sorted(FIELDS)}")
        if value.get("agent") not in AGENTS:
            errors.append(f"roles.{role}.agent must be one of {sorted(AGENTS)}")
        for field in ("model", "effort"):
            candidate = value.get(field)
            if not isinstance(candidate, str) or not candidate.strip():
                errors.append(f"roles.{role}.{field} must be a non-empty string")
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


def capability_errors(agent: str, model: str, effort: str, evidence: object) -> list[str]:
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
        for stage in ("starting", "execution"):
            pair = plan.get(stage, {})
            errors.extend(capability_errors(plan["agent"], pair.get("model"),
                                             pair.get("effort"), evidence))
        return errors
    return capability_errors(plan["agent"], plan["model"], plan["effort"], evidence)


def resolve_plan(document: dict, role: str, *, ticket_mode: str | None = None,
                 map_mode: str | None = None, evidence: object = None,
                 output_mode: str | None = None) -> dict:
    """解析并冻结一条 lane 的 mode 与模型选择，不修改配置。"""
    errors = validate_document(document)
    if errors:
        raise ValueError("; ".join(errors))
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    role_config = document["roles"][role]
    plan = {"version": document["version"], "role": role, **role_config}
    if document["version"] == 2 or role not in IMPLEMENTATION_ROLES or output_mode != "commit":
        if document["version"] == 2 and evidence is None:
            return {**plan, "mode": "legacy", "phase": "direct", "source": "role-config",
                    "capability": "legacy-config"}
        if evidence is None:
            capability = "unknown"
        else:
            errors = capability_errors(role_config["agent"], role_config["model"],
                                       role_config["effort"], evidence)
            if errors:
                raise ValueError("; ".join(errors))
            capability = "verified"
        return {**plan, "mode": "legacy", "phase": "direct", "source": "role-config",
                "capability": capability}

    requested = ticket_mode if ticket_mode is not None else map_mode
    source = "ticket" if ticket_mode is not None else "map" if map_mode is not None else "user-config"
    if requested is None:
        requested = document["execution"][role_config["agent"]]["default_mode"]
    if requested not in MODES:
        raise ValueError(f"{source} execution mode must equal staged or direct")
    agent_plan = document["execution"][role_config["agent"]]
    if requested == "staged":
        resolved = {**plan, "model": agent_plan["starting"]["model"],
                    "effort": agent_plan["starting"]["effort"],
                    "mode": "staged", "phase": "starting", "source": source,
                    "starting": agent_plan["starting"], "execution": agent_plan["execution"]}
    else:
        resolved = {**plan, "mode": "direct", "phase": "direct", "source": source,
                    **agent_plan["direct"]}
    if evidence is None:
        return {**resolved, "capability": "unknown"}
    errors = plan_capability_errors(resolved, evidence)
    if errors:
        raise ValueError("; ".join(errors))
    return {**resolved, "capability": "verified"}


def freeze_overlay(plan: dict) -> dict:
    """返回 coordinator 写入 packet 与 registry 的唯一计划 overlay。"""
    if plan.get("mode") == "staged":
        starting = plan["starting"]
        execution = plan["execution"]
    else:
        starting = execution = None
    return {
        "execution_mode": plan["mode"],
        "execution_source": plan["source"],
        "agent": plan["agent"],
        "model": plan.get("model"),
        "effort": plan.get("effort"),
        "starting_model": starting["model"] if starting else None,
        "starting_effort": starting["effort"] if starting else None,
        "execution_model": execution["model"] if execution else None,
        "execution_effort": execution["effort"] if execution else None,
        "direct_model": plan["model"] if plan["mode"] in {"direct", "legacy"} else None,
        "direct_effort": plan["effort"] if plan["mode"] in {"direct", "legacy"} else None,
        "execution_phase": plan["phase"],
    }


def verify_overlay(plan: dict, overlay: object) -> dict:
    expected = freeze_overlay(plan)
    if overlay != expected:
        raise ValueError("packet/registry execution plan readback mismatch")
    return expected


def startup_request(plan: dict, *, worker_name: str, pane_id: str) -> list[str]:
    """构造 Herdr 原生请求；Pi staged 使用原生 TUI adapter。"""
    if plan.get("mode") == "staged":
        if plan.get("agent") != "pi":
            raise ValueError(f"staged execution adapter unavailable for {plan.get('agent')}; refusing silent direct fallback")
        if plan.get("capability") != "verified":
            raise ValueError("capability evidence is required before staged startup")
        starting = plan.get("starting")
        if not isinstance(starting, dict):
            raise ValueError("Pi staged plan is missing starting model/effort")
        try:
            return build_start_command(worker_name=worker_name, pane_id=pane_id,
                                       model=starting.get("model"), effort=starting.get("effort"))
        except PiAdapterError as error:
            raise ValueError(str(error)) from error
    if plan.get("mode") not in {"legacy", "direct"}:
        raise ValueError("execution plan is not runnable")
    if plan.get("capability") not in {"legacy-config", "verified"}:
        raise ValueError("capability evidence is required before startup")
    agent, model, effort = plan.get("agent"), plan.get("model"), plan.get("effort")
    if agent not in AGENTS or not all(isinstance(value, str) and value.strip()
                                      for value in (worker_name, pane_id, model, effort)):
        raise ValueError("startup request requires agent, model, effort, worker_name and pane_id")
    prefix = ["herdr", "agent", "start", worker_name, "--kind", agent, "--pane", pane_id, "--"]
    if agent == "pi":
        return prefix + ["--approve", "--model", model, "--thinking", effort]
    if agent == "codex":
        return prefix + ["--model", model, "-c", f'model_reasoning_effort="{effort}"',
                         "-s", "danger-full-access", "-a", "never"]
    return prefix + ["--model", model, "--effort", effort, "--dangerously-skip-permissions"]


def valid_fixture() -> dict:
    return {
        "version": 2,
        "roles": {
            role: {"agent": "pi", "model": "provider/model", "effort": "high"}
            for role in sorted(ROLES)
        },
    }


def self_test() -> list[str]:
    failures: list[str] = []
    if validate_document(valid_fixture()):
        failures.append("valid fixture was rejected")

    phased = valid_fixture()
    phased["version"] = 3
    phased["execution"] = {
        agent: {
            "default_mode": "staged",
            **{stage: {"model": "provider/model", "effort": "high"}
               for stage in ("starting", "execution", "direct")},
        }
        for agent in sorted(AGENTS)
    }
    evidence = {
        agent: {"binary": True, "models": {"provider/model": ["low", "high", "medium"]}}
        for agent in sorted(AGENTS)
    }
    if validate_document(phased):
        failures.append("explicit v3 execution config was rejected")
    if resolve_plan(phased, "backend", output_mode="commit")["source"] != "user-config":
        failures.append("user execution mode was not selected")
    if resolve_plan(phased, "backend")["mode"] != "legacy":
        failures.append("missing output mode enabled implementation phases")
    if resolve_plan(phased, "backend", map_mode="direct", output_mode="commit")["mode"] != "direct":
        failures.append("map execution mode was not selected")
    selected = resolve_plan(phased, "backend", ticket_mode="direct", map_mode="staged", output_mode="commit")
    if selected["mode"] != "direct" or selected["source"] != "ticket":
        failures.append("ticket execution mode did not override map mode")
    verified = resolve_plan(phased, "backend", ticket_mode="direct", evidence=evidence, output_mode="commit")
    if verified["capability"] != "verified":
        failures.append("live capability evidence was not recorded")
    if resolve_plan(phased, "design", output_mode="artifact")["mode"] != "legacy":
        failures.append("design artifact lane was assigned implementation phases")
    overlay = freeze_overlay(verified)
    if verify_overlay(verified, json.loads(json.dumps(overlay))) != overlay:
        failures.append("frozen packet/registry overlay failed readback")
    with tempfile.TemporaryDirectory() as directory:
        config_path = Path(directory) / "model-roles.json"
        packet_path = Path(directory) / "packet-overlay.json"
        registry_path = Path(directory) / "registry-overlay.json"
        config_path.write_text(json.dumps(phased), encoding="utf-8")
        persisted = resolve_plan(load_document(config_path), "backend", ticket_mode="direct",
                                 evidence=evidence, output_mode="commit")
        persisted_overlay = freeze_overlay(persisted)
        for path in (packet_path, registry_path):
            path.write_text(json.dumps(persisted_overlay, sort_keys=True), encoding="utf-8")
            verify_overlay(persisted, json.loads(path.read_text(encoding="utf-8")))
    for agent in sorted(AGENTS):
        case = json.loads(json.dumps(phased))
        case["roles"]["backend"] = {"agent": agent, "model": "provider/model", "effort": "high"}
        resolved = resolve_plan(case, "backend", ticket_mode="direct", evidence=evidence,
                                output_mode="commit")
        command = startup_request(resolved, worker_name="worker", pane_id="pane")
        if command[5] != agent:
            failures.append(f"config-to-start mapping selected the wrong {agent} kind")
    bad_evidence = json.loads(json.dumps(evidence))
    bad_evidence["pi"]["binary"] = False
    try:
        resolve_plan(phased, "backend", ticket_mode="direct", evidence=bad_evidence,
                     output_mode="commit")
    except ValueError:
        pass
    else:
        failures.append("unavailable binary was accepted")
    mismatched_evidence = json.loads(json.dumps(evidence))
    mismatched_evidence["pi"]["models"]["provider/model"] = ["low"]
    try:
        resolve_plan(phased, "backend", ticket_mode="direct", evidence=mismatched_evidence,
                     output_mode="commit")
    except ValueError:
        pass
    else:
        failures.append("model/effort mismatch was accepted")
    if resolve_plan(phased, "planning")["mode"] != "legacy":
        failures.append("non-implementation role did not retain legacy behavior")
    legacy = valid_fixture()
    legacy_plan = resolve_plan(legacy, "backend")
    if legacy_plan["mode"] != "legacy" or startup_request(legacy_plan, worker_name="worker", pane_id="pane")[4] != "--kind":
        failures.append("v2 legacy startup behavior changed")
    legacy_bad_evidence = {"pi": {"binary": False, "models": {"provider/model": ["high"]}}}
    try:
        resolve_plan(legacy, "backend", evidence=legacy_bad_evidence)
    except ValueError:
        pass
    else:
        failures.append("v2 capability mismatch was accepted")
    staged_pi = resolve_plan(phased, "backend", evidence=evidence, output_mode="commit")
    try:
        command = startup_request(staged_pi, worker_name="worker", pane_id="pane")
    except ValueError:
        failures.append("Pi staged mode did not use its native adapter")
    else:
        if command[5] != "pi" or "--thinking" not in command:
            failures.append("Pi staged startup omitted its native model/thinking arguments")
    for agent in ("codex", "claude"):
        case = json.loads(json.dumps(phased))
        case["roles"]["backend"]["agent"] = agent
        try:
            plan = resolve_plan(case, "backend", evidence=evidence, output_mode="commit")
            startup_request(plan, worker_name="worker", pane_id="pane")
        except ValueError as error:
            if "adapter unavailable" not in str(error):
                failures.append(f"{agent} staged mode failed for the wrong reason")
        else:
            failures.append(f"{agent} staged mode silently became runnable")
    for agent in sorted(AGENTS):
        plan = {"mode": "direct", "agent": agent, "model": "provider/model", "effort": "high",
                "capability": "verified"}
        command = startup_request(plan, worker_name="worker", pane_id="pane")
        if command[4] != "--kind" or command[5] != agent:
            failures.append(f"{agent} startup mapping omitted its kind")
        if agent == "pi" and "--thinking" not in command:
            failures.append("pi startup mapping omitted thinking")
        if agent == "codex" and "model_reasoning_effort=\"high\"" not in command:
            failures.append("codex startup mapping omitted reasoning effort")
        if agent == "claude" and "--effort" not in command:
            failures.append("claude startup mapping omitted effort")
    for agent in sorted(AGENTS):
        for field in ("default_mode", "starting", "execution", "direct"):
            case = json.loads(json.dumps(phased))
            del case["execution"][agent][field]
            if not validate_document(case):
                failures.append(f"missing execution.{agent}.{field} was accepted")
    for field, value in (("default_mode", "Unknown"), ("direct", {"model": "", "effort": "high"})):
        case = json.loads(json.dumps(phased))
        case["execution"]["pi"][field] = value
        if not validate_document(case):
            failures.append(f"invalid execution.pi.{field} was accepted")

    cases: dict[str, dict] = {}
    case = valid_fixture(); case["version"] = 1; cases["old-version"] = case
    case = valid_fixture(); del case["roles"]["review"]; cases["missing-role"] = case
    case = valid_fixture(); case["roles"]["extra"] = case["roles"]["planning"].copy(); cases["extra-role"] = case
    case = valid_fixture(); case["roles"]["backend"]["extra"] = True; cases["extra-field"] = case
    case = valid_fixture(); case["roles"]["testing"]["agent"] = "bogus"; cases["bogus-agent"] = case
    case = valid_fixture(); case["roles"]["design"]["model"] = ""; cases["blank-model"] = case
    case = valid_fixture(); case["extra"] = True; cases["extra-top-level"] = case

    for name, document in cases.items():
        if not validate_document(document):
            failures.append(f"invalid fixture accepted: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate delivery-pipeline model role config")
    parser.add_argument("command", choices=("validate", "self-test", "resolve", "freeze", "start"))
    parser.add_argument("path", nargs="?", default="~/.config/delivery-pipeline/model-roles.json")
    parser.add_argument("role", nargs="?")
    parser.add_argument("--ticket-mode")
    parser.add_argument("--map-mode")
    parser.add_argument("--output-mode")
    parser.add_argument("--evidence", help="归一化实时能力 evidence JSON")
    parser.add_argument("--worker-name", default="worker")
    parser.add_argument("--pane-id", default="pane")
    args = parser.parse_args()

    if args.command == "self-test":
        errors = self_test()
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    if args.command == "validate":
        errors = validate_path(Path(args.path))
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    if not args.role:
        parser.error(f"{args.command} 需要 ROLE")
    try:
        evidence = json.loads(Path(args.evidence).expanduser().read_text()) if args.evidence else None
        plan = resolve_plan(load_document(Path(args.path)), args.role,
                            ticket_mode=args.ticket_mode, map_mode=args.map_mode, evidence=evidence,
                            output_mode=args.output_mode)
        if args.command == "start":
            result = startup_request(plan, worker_name=args.worker_name, pane_id=args.pane_id)
        elif args.command == "freeze":
            result = freeze_overlay(plan)
        else:
            result = plan
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "errors": [str(error)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "delivery-pipeline" / "scripts"
sys.path.insert(0, str(CORE_SCRIPTS))
from pi_adapter import build_start_command, build_tui_switch
import codex_cli_adapter
import checkpoint

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
        for stage in STAGES:
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
                    **{stage: dict(agent_plan[stage]) for stage in STAGES}}
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
        for stage in STAGES:
            pair = plan.get(stage)
            if (not isinstance(pair, dict) or set(pair) != {"model", "effort"}
                    or any(not isinstance(value, str) or not value.strip()
                           or value.strip().lower() == "unknown" for value in pair.values())):
                raise ValueError(f"staged plan missing {stage} model/effort")
        starting = plan["starting"]
        execution = plan["execution"]
        direct = plan["direct"]
    else:
        starting = execution = None
        direct = plan
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
    if isinstance(payload, dict) and payload.get("runtime") in {"herdr-pi-pane", "herdr-codex-pane"}:
        if set(payload) != {"runtime", "checkpoint_path", "request", "observation", "evidence"}:
            raise ValueError("continuation payload 字段不匹配")
        path = payload["checkpoint_path"]
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError("checkpoint_path 必须是绝对路径")
        document = codex_cli_adapter._load_checkpoint(path)
        if document["runtime"] != payload["runtime"]:
            raise ValueError("checkpoint runtime 不匹配")
        observation = payload["observation"]
        ready = checkpoint.evaluate_signal(document,
            f"WORKER_STOPPED {document['lane_id']} {document['checkpoint_path']}", observation)
        if (not ready["can_continue"] or observation.get("coordinator_active") is not False
                or observation.get("session_resumable") is not True):
            raise ValueError("原 session 停止或接续证据不足")
        request = payload["request"]
        if not isinstance(request, dict) or set(request) != {"request_id", "intent_sha256", "target_request"}:
            raise ValueError("canonical continuation request 字段不匹配")
        intent = checkpoint.build_continuation_intent(document, target_request=request["target_request"])
        if (request["intent_sha256"] != intent[checkpoint.INTENT_FINGERPRINT_FIELD]
                or request["request_id"] != "request-" + request["intent_sha256"]):
            raise ValueError("continuation intent 与 checkpoint 不匹配")
        agent = "pi" if payload["runtime"] == "herdr-pi-pane" else "codex"
        target = request["target_request"]
        errors = capability_errors(agent, target["model"], target["effort"], payload["evidence"])
        if errors:
            raise ValueError("; ".join(errors))
        if agent == "codex":
            return codex_cli_adapter.resume_from_checkpoint(document, request)
        return {**build_tui_switch(request), "session_id": document["session_id"],
                "worktree": document["execution_worktree"],
                "checkpoint_sha256": document[checkpoint.FINGERPRINT_FIELD]}

    if not isinstance(payload, dict) or payload.get("runtime") != "herdr-claude-pane":
        raise ValueError("Claude continuation caller 只接受 herdr-claude-pane")
    adapter_path = Path(__file__).resolve().parents[2] / "delivery-pipeline" / "scripts" / "claude_adapter.py"
    spec = importlib.util.spec_from_file_location("delivery_pipeline_claude_adapter", adapter_path)
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
    if plan.get("mode") not in {"legacy", "direct", "staged"}:
        raise ValueError("execution plan is not runnable")
    if plan.get("capability") != "verified":
        raise ValueError("capability evidence is required before startup")
    if plan.get("mode") == "staged":
        freeze_overlay(plan)
        if (plan.get("model"), plan.get("effort")) != (plan["starting"]["model"], plan["starting"]["effort"]):
            raise ValueError("staged startup 与冻结 starting 不匹配")
        if plan.get("agent") == "pi":
            return build_start_command(worker_name=worker_name, pane_id=pane_id,
                                       model=plan["model"], effort=plan["effort"])
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
            **{stage: {"model": "provider/model", "effort": effort}
               for stage, effort in (("starting", "high"), ("execution", "medium"), ("direct", "low"))},
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
    mismatched_evidence["pi"]["models"]["provider/model"] = []
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
    if legacy_plan["mode"] != "legacy" or startup_request(resolve_plan(legacy, "backend", evidence=evidence), worker_name="worker", pane_id="pane")[4] != "--kind":
        failures.append("v2 legacy startup behavior changed")
    try:
        startup_request(legacy_plan, worker_name="worker", pane_id="pane")
    except ValueError:
        pass
    else:
        failures.append("v2 startup accepted missing capability evidence")
    staged = resolve_plan(phased, "backend", evidence=evidence, output_mode="commit")
    frozen = freeze_overlay(staged)
    verify_overlay(staged, json.loads(json.dumps(frozen)))
    for stage in STAGES:
        for field in ("model", "effort"):
            key = f"{stage}_{field}"
            if frozen[key] != phased["execution"]["pi"][stage][field]:
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
    case = json.loads(json.dumps(phased))
    case["roles"]["backend"]["agent"] = "codex"
    try:
        plan = resolve_plan(case, "backend", evidence=evidence, output_mode="commit")
        startup_request(plan, worker_name="worker", pane_id="pane")
    except ValueError:
        failures.append("codex staged mode did not enter native startup caller")
    claude_case = json.loads(json.dumps(phased))
    claude_case["roles"]["backend"]["agent"] = "claude"
    claude_staged = resolve_plan(claude_case, "backend", evidence=evidence, output_mode="commit")
    claude_command = startup_request(claude_staged, worker_name="worker", pane_id="pane")
    if (claude_command[5] != "claude" or "--model" not in claude_command
            or "--effort" not in claude_command):
        failures.append("Claude staged plan did not enter the existing startup caller")
    try:
        continuation_request({"runtime": "herdr-codex-pane"})
    except ValueError:
        pass
    else:
        failures.append("non-Claude continuation was accepted by Claude caller")
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
    # 复用 checkpoint fixture；生产入口必须绑定持久现场，且不发送任何请求。
    import checkpoint_check as fixture
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "execution"
        root.mkdir()
        fixture.git(root, "init", "-b", "check")
        fixture.git(root, "-c", "user.name=check", "-c", "user.email=check@example.invalid",
                    "commit", "--allow-empty", "--no-verify", "-m", "base")
        (root / "worker.py").write_text("first edit\n")
        path = Path(folder) / "checkpoint.json"
        base = fixture.document_for(checkpoint.snapshot_worktree(root), path)
        for agent in ("pi", "codex"):
            path = Path(folder) / f"{agent}-checkpoint.json"
            document = fixture.with_update(base, checkpoint_path=str(path), runtime=f"herdr-{agent}-pane",
                session_id="018f47a0-1b2c-7d3e-8f40-123456789abc")
            checkpoint.write_checkpoint(path, document, worktree=root)
            intent = checkpoint.build_continuation_intent(document,
                target_request={"model": "provider/model", "effort": "high"})
            payload = {"runtime": document["runtime"], "checkpoint_path": str(path),
                "request": {"request_id": "request-" + intent[checkpoint.INTENT_FINGERPRINT_FIELD],
                            "intent_sha256": intent[checkpoint.INTENT_FINGERPRINT_FIELD],
                            "target_request": intent["target_request"]},
                "observation": fixture.observation(document, status="stopped", writer_active=False,
                    coordinator_active=False, ready_seen=True, stop_evidence=True, session_resumable=True),
                "evidence": evidence}
            result = continuation_request(payload)
            assert result["session_id"] == document["session_id"]
            assert result["checkpoint_sha256"] == document["checkpoint_sha256"]
            if agent == "pi":
                assert result["commands"][0]["text"] == "/model provider/model"
            else:
                assert result["native_args"][:2] == ["resume", document["session_id"]]
            for field, value in (("evidence", {}), ("runtime", "herdr-claude-pane"),
                                 ("observation", {**payload["observation"], "writer_active": True}),
                                 ("request", {**payload["request"], "intent_sha256": "b" * 64})):
                try:
                    continuation_request({**payload, field: value})
                except ValueError:
                    pass
                else:
                    failures.append(f"{agent} continuation accepted invalid {field}")
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
    parser.add_argument("command", choices=("validate", "self-test", "resolve", "freeze", "start", "resume"))
    parser.add_argument("path", nargs="?", default="~/.config/delivery-pipeline/model-roles.json")
    parser.add_argument("role", nargs="?")
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
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    if args.command == "validate":
        errors = validate_path(Path(args.path))
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    if args.command == "resume":
        if not args.request:
            parser.error("resume 需要 --request PAYLOAD_JSON")
        try:
            payload = json.loads(Path(args.request).expanduser().read_text())
            result = continuation_request(payload)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(json.dumps({"valid": False, "errors": [str(error)]}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
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

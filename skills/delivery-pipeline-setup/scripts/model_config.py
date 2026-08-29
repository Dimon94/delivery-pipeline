#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROLES = {"planning", "design", "frontend", "backend", "testing", "review"}
IMPLEMENTATION_ROLES = {"frontend", "backend"}
AGENTS = {"pi", "codex", "claude"}
BASE_FIELDS = {"agent", "model", "effort"}
BOOTSTRAP_FIELDS = {"model", "effort"}
TOP_LEVEL = {"version", "gearshift", "roles"}
GEARSHIFT_FIELDS = {"mode", "optInLabel"}
GEARSHIFT_MODES = {"off", "opt_in", "all_eligible"}


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_label(value: object) -> bool:
    return _non_empty(value) and len(value) <= 50 and all(ord(char) >= 32 and ord(char) != 127 for char in value)


def validate_document(document: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level value must be an object"]
    if set(document) != TOP_LEVEL:
        errors.append(f"top-level keys must be exactly {sorted(TOP_LEVEL)}")
    if document.get("version") != 3:
        errors.append("version must equal 3")

    gearshift = document.get("gearshift")
    if not isinstance(gearshift, dict):
        errors.append("gearshift must be an object")
        mode = None
    else:
        if set(gearshift) != GEARSHIFT_FIELDS:
            errors.append(f"gearshift keys must be exactly {sorted(GEARSHIFT_FIELDS)}")
        mode = gearshift.get("mode")
        if mode not in GEARSHIFT_MODES:
            errors.append(f"gearshift.mode must be one of {sorted(GEARSHIFT_MODES)}")
        if not _valid_label(gearshift.get("optInLabel")):
            errors.append("gearshift.optInLabel must be a 1-50 character string without control characters")

    roles = document.get("roles")
    if not isinstance(roles, dict):
        errors.append("roles must be an object")
        return errors
    if set(roles) != ROLES:
        errors.append(f"role keys must be exactly {sorted(ROLES)}")

    eligible_bootstraps = 0
    for role in sorted(ROLES & set(roles)):
        value = roles[role]
        if not isinstance(value, dict):
            errors.append(f"roles.{role} must be an object")
            continue
        allowed = BASE_FIELDS | ({"bootstrap"} if role in IMPLEMENTATION_ROLES else set())
        if set(value) - allowed or not BASE_FIELDS.issubset(value):
            errors.append(f"roles.{role} keys must be exactly {sorted(BASE_FIELDS)} with optional bootstrap only on frontend/backend")
        if value.get("agent") not in AGENTS:
            errors.append(f"roles.{role}.agent must be one of {sorted(AGENTS)}")
        for field in ("model", "effort"):
            if not _non_empty(value.get(field)):
                errors.append(f"roles.{role}.{field} must be a non-empty string")

        if "bootstrap" not in value:
            continue
        bootstrap = value["bootstrap"]
        if role not in IMPLEMENTATION_ROLES:
            errors.append(f"roles.{role}.bootstrap is not allowed")
            continue
        if value.get("agent") != "pi":
            errors.append(f"roles.{role}.bootstrap requires agent pi")
        if not isinstance(bootstrap, dict):
            errors.append(f"roles.{role}.bootstrap must be an object")
            continue
        if set(bootstrap) != BOOTSTRAP_FIELDS:
            errors.append(f"roles.{role}.bootstrap keys must be exactly {sorted(BOOTSTRAP_FIELDS)}")
        for field in sorted(BOOTSTRAP_FIELDS):
            if not _non_empty(bootstrap.get(field)):
                errors.append(f"roles.{role}.bootstrap.{field} must be a non-empty string")
        if _non_empty(bootstrap.get("model")) and bootstrap.get("model") == value.get("model"):
            errors.append(f"roles.{role}.bootstrap.model must differ from the ordinary Target Model")
        if value.get("agent") == "pi" and set(bootstrap) == BOOTSTRAP_FIELDS and all(
            _non_empty(bootstrap.get(field)) for field in BOOTSTRAP_FIELDS
        ):
            eligible_bootstraps += 1

    if mode in {"opt_in", "all_eligible"} and eligible_bootstraps == 0:
        errors.append(f"gearshift.mode {mode} requires at least one eligible pi frontend/backend bootstrap")
    return errors


def validate_path(path: Path) -> list[str]:
    try:
        return validate_document(json.loads(path.expanduser().read_text()))
    except FileNotFoundError:
        return [f"config file not found: {path.expanduser()}"]
    except json.JSONDecodeError as error:
        return [f"invalid JSON: {error}"]


def valid_fixture() -> dict:
    roles = {
        role: {"agent": "pi", "model": "provider/fast", "effort": "high"}
        for role in sorted(ROLES)
    }
    roles["backend"]["bootstrap"] = {"model": "provider/high", "effort": "high"}
    return {
        "version": 3,
        "gearshift": {"mode": "opt_in", "optInLabel": "bootstrap-handoff"},
        "roles": roles,
    }


def self_test() -> list[str]:
    failures: list[str] = []
    if validate_document(valid_fixture()):
        failures.append("valid fixture was rejected")
    off = valid_fixture()
    off["gearshift"]["mode"] = "off"
    del off["roles"]["backend"]["bootstrap"]
    if validate_document(off):
        failures.append("valid Gearshift-off fixture was rejected")
    punctuation_label = valid_fixture()
    punctuation_label["gearshift"]["optInLabel"] = "type: bootstrap #1"
    if validate_document(punctuation_label):
        failures.append("valid punctuation label fixture was rejected")

    cases: dict[str, dict] = {}
    case = valid_fixture(); case["version"] = 2; cases["old-version"] = case
    case = valid_fixture(); del case["roles"]["review"]; cases["missing-role"] = case
    case = valid_fixture(); case["roles"]["extra"] = case["roles"]["planning"].copy(); cases["extra-role"] = case
    case = valid_fixture(); case["roles"]["backend"]["extra"] = True; cases["extra-field"] = case
    case = valid_fixture(); case["roles"]["testing"]["agent"] = "bogus"; cases["bogus-agent"] = case
    case = valid_fixture(); case["roles"]["design"]["model"] = ""; cases["blank-model"] = case
    case = valid_fixture(); case["extra"] = True; cases["extra-top-level"] = case
    case = valid_fixture(); case["gearshift"]["mode"] = "automatic"; cases["bad-mode"] = case
    case = valid_fixture(); case["gearshift"]["extra"] = True; cases["extra-gearshift-field"] = case
    case = valid_fixture(); case["gearshift"]["optInLabel"] = ""; cases["blank-opt-in-label"] = case
    case = valid_fixture(); case["gearshift"]["optInLabel"] = "bad\nlabel"; cases["control-character-label"] = case
    case = valid_fixture(); case["gearshift"]["optInLabel"] = "x" * 51; cases["overlong-label"] = case
    case = valid_fixture(); case["roles"]["backend"]["agent"] = "codex"; cases["bootstrap-non-pi"] = case
    case = valid_fixture(); case["roles"]["design"]["bootstrap"] = {"model": "x", "effort": "high"}; cases["bootstrap-design"] = case
    case = valid_fixture(); del case["roles"]["backend"]["bootstrap"]; cases["active-without-bootstrap"] = case
    case = valid_fixture(); case["roles"]["backend"]["bootstrap"] = {"model": "x"}; cases["incomplete-bootstrap"] = case
    case = valid_fixture(); case["gearshift"]["mode"] = "off"; case["roles"]["backend"]["bootstrap"] = None; cases["null-bootstrap"] = case
    case = valid_fixture(); case["roles"]["backend"]["bootstrap"]["model"] = "provider/fast"; cases["same-source-target"] = case

    for name, document in cases.items():
        if not validate_document(document):
            failures.append(f"invalid fixture accepted: {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate delivery-pipeline model role config")
    parser.add_argument("command", choices=("validate", "self-test"))
    parser.add_argument("path", nargs="?", default="~/.config/delivery-pipeline/model-roles.json")
    args = parser.parse_args()

    errors = self_test() if args.command == "self-test" else validate_path(Path(args.path))
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

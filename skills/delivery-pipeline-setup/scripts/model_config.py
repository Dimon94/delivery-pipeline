#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROLES = {"planning", "design", "frontend", "backend", "testing", "review"}
AGENTS = {"pi", "codex", "claude"}
FIELDS = {"agent", "model", "effort"}
TOP_LEVEL = {"version", "roles"}


def validate_document(document: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level value must be an object"]
    if set(document) != TOP_LEVEL:
        errors.append(f"top-level keys must be exactly {sorted(TOP_LEVEL)}")
    if document.get("version") != 2:
        errors.append("version must equal 2")
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
    parser.add_argument("command", choices=("validate", "self-test"))
    parser.add_argument("path", nargs="?", default="~/.config/delivery-pipeline/model-roles.json")
    args = parser.parse_args()

    errors = self_test() if args.command == "self-test" else validate_path(Path(args.path))
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

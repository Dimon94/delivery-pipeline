#!/usr/bin/env python3
"""DD-685：CLI v9 任务类型目录校验、v6–v8 升级与动态 show 合同（S1/S2/S3/S4/S8）。"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_config_transaction import m, SCRIPT


def _v8_fixture() -> dict:
    base = m.valid_fixture()
    return {
        **base,
        "version": 8,
        "model_families": {},
        "dispatch": {"parallel": 4, "max_turns": 100},
    }


def _run(path: Path, command: str, candidate=None, *args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), command, str(path), *args],
        input=json.dumps(candidate) if candidate is not None else None,
        text=True,
        capture_output=True,
    )
    assert proc.stdout.strip(), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cli_path = root / "model-roles.json"
        app_path = root / "app-models.json"
        ev_path = root / "evidence.json"

        evidence = {
            "request_id": "req-v9",
            "observed_at": "2026-11-27T12:00:00Z",
            "sources": {a: {"status": "ok"} for a in ("pi", "codex", "claude", "antigravity")},
            "capabilities": {
                a: {"binary": True, "models": {"provider/model": ["low", "medium", "high"]}}
                for a in ("pi", "codex", "claude", "antigravity")
            },
        }
        ev_path.write_text(json.dumps(evidence), encoding="utf-8")

        # S1（T1, R4）：合法 CLI v8 迁移两次；App v5 不受影响。
        v8 = _v8_fixture()
        v8_snapshot = copy.deepcopy(v8)
        normalized = m.normalize_work_entries(v8)
        assert v8 == v8_snapshot, "normalize_work_entries 不得修改输入"
        assert set(normalized) == set(m.CLI_REQUIRED_WORK)
        for task, meta in m.DEFAULT_TASK_META.items():
            assert normalized[task] == {**v8["work"][task], **meta}

        cli_path.write_text(json.dumps(v8, indent=2) + "\n", encoding="utf-8")
        app_doc = m.valid_app_fixture()
        app_path.write_text(json.dumps(app_doc, indent=2) + "\n", encoding="utf-8")
        app_before = app_path.read_bytes()
        app_hash = hashlib.sha256(app_before).hexdigest()

        code, first = _run(cli_path, "migrate")
        assert code == 0 and first["transport"] == "cli" and first["changed"] is True, first
        migrated = json.loads(cli_path.read_text(encoding="utf-8"))
        assert migrated["version"] == 9
        assert migrated["modes"] == v8["modes"]
        assert migrated["review"] == v8["review"]
        assert migrated["dispatch"] == v8["dispatch"]
        assert migrated["model_families"] == v8["model_families"]
        for task, meta in m.DEFAULT_TASK_META.items():
            assert migrated["work"][task] == {**v8["work"][task], **meta}

        v9_bytes = cli_path.read_bytes()
        v9_hash = hashlib.sha256(v9_bytes).hexdigest()
        v9_stat = cli_path.stat()
        code, second = _run(cli_path, "migrate")
        assert code == 0 and second["changed"] is False, second
        assert cli_path.read_bytes() == v9_bytes
        assert hashlib.sha256(cli_path.read_bytes()).hexdigest() == v9_hash
        assert cli_path.stat().st_mtime_ns == v9_stat.st_mtime_ns

        # 同目录 App v5 不被迁移、校验结果不变。
        assert app_path.read_bytes() == app_before
        assert hashlib.sha256(app_path.read_bytes()).hexdigest() == app_hash
        assert m.validate_document(json.loads(app_before), "app") == []
        code, app_mig = _run(app_path, "migrate")
        assert code == 0 and app_mig["transport"] == "app" and app_mig["changed"] is False, app_mig
        assert app_path.read_bytes() == app_before
        assert json.loads(app_path.read_text(encoding="utf-8"))["version"] == 5

        # S2（R1）：含自定义 work.advisory-doc 的 v9 文档校验通过，show.cells 出现 work.advisory-doc。
        custom = copy.deepcopy(migrated)
        custom["work"]["advisory-doc"] = {
            "agent": "pi",
            "model": "provider/model",
            "effort": "high",
            "fallbacks": [],
            "label": "咨询建议",
            "hint": "输出调研与方案建议文档",
            "purpose": "artifact",
        }
        assert m.validate_document(custom) == []
        cli_path.write_text(json.dumps(custom, indent=2) + "\n", encoding="utf-8")
        custom_raw = cli_path.read_bytes()
        code, shown = _run(cli_path, "show")
        assert code == 0 and shown["file_state"] == "ready" and shown["validation"]["valid"] is True, shown
        assert "work.advisory-doc" in shown["cells"]
        assert shown["cells"]["work.advisory-doc"] == {"status": "unknown"}
        assert cli_path.read_bytes() == custom_raw

        # S3（R2）：删 frontend/design 通过；删最后一个 code/planning/checks 报错且 apply 拒绝不改字节。
        minimal = copy.deepcopy(migrated)
        del minimal["work"]["frontend"]
        del minimal["work"]["design"]
        assert m.validate_document(minimal) == []
        cli_path.write_text(json.dumps(minimal, indent=2) + "\n", encoding="utf-8")
        min_raw = cli_path.read_bytes()
        min_hash = hashlib.sha256(min_raw).hexdigest()
        for task, purpose in (("backend", "code"), ("planning", "planning"), ("testing", "checks")):
            broken = copy.deepcopy(minimal)
            del broken["work"][task]
            errors = m.validate_document(broken)
            assert errors and any(purpose in err for err in errors), (task, purpose, errors)
            code, res = _run(
                cli_path,
                "apply",
                broken,
                "--base-hash",
                min_hash,
                "--request-id",
                "req-v9",
                "--evidence",
                str(ev_path),
            )
            assert code == 1 and res["status"] == "rejected", (task, res)
            assert cli_path.read_bytes() == min_raw

        # S4（R1）：非法 id、保留词、空/Unknown label、缺/多字段、非法 purpose 逐项拒绝且原文件不变。
        valid_entry = copy.deepcopy(migrated["work"]["planning"])
        invalid_cases: list[tuple[str, dict]] = []
        for bad_id in ("BadId", "bad id", "bad_id", "-leading", "trailing-"):
            doc = copy.deepcopy(migrated)
            doc["work"][bad_id] = copy.deepcopy(valid_entry)
            invalid_cases.append((f"bad-id:{bad_id}", doc))
        for reserved in ("review", "map", "all"):
            doc = copy.deepcopy(migrated)
            doc["work"][reserved] = copy.deepcopy(valid_entry)
            invalid_cases.append((f"reserved:{reserved}", doc))
        for bad_label in ("", "   ", "Unknown", "unknown"):
            doc = copy.deepcopy(migrated)
            doc["work"]["planning"]["label"] = bad_label
            invalid_cases.append((f"bad-label:{bad_label!r}", doc))
        doc_missing = copy.deepcopy(migrated)
        del doc_missing["work"]["planning"]["hint"]
        invalid_cases.append(("missing-field", doc_missing))
        doc_extra = copy.deepcopy(migrated)
        doc_extra["work"]["planning"]["extra"] = True
        invalid_cases.append(("extra-field", doc_extra))
        doc_purpose = copy.deepcopy(migrated)
        doc_purpose["work"]["planning"]["purpose"] = "invalid-purpose"
        invalid_cases.append(("bad-purpose", doc_purpose))

        cli_path.write_text(json.dumps(migrated, indent=2) + "\n", encoding="utf-8")
        orig_raw = cli_path.read_bytes()
        orig_hash = hashlib.sha256(orig_raw).hexdigest()
        for name, doc in invalid_cases:
            errors = m.validate_document(doc)
            assert errors, f"{name} should fail validate_document"
            code, res = _run(
                cli_path,
                "apply",
                doc,
                "--base-hash",
                orig_hash,
                "--request-id",
                "req-v9",
                "--evidence",
                str(ev_path),
            )
            assert code == 1 and res["status"] == "rejected", (name, res)
            assert cli_path.read_bytes() == orig_raw

        # S8（T1, R4）：合法 CLI v8 调用 show 不改字节与 hash；提交只改一格模型的 v9 候选经 apply 原子升级。
        cli_path.write_text(json.dumps(v8, separators=(",", ":")), encoding="utf-8")
        v8_raw = cli_path.read_bytes()
        v8_hash = hashlib.sha256(v8_raw).hexdigest()
        code, shown_v8 = _run(cli_path, "show")
        assert code == 0 and shown_v8["file_state"] == "ready" and shown_v8["base_hash"] == v8_hash
        assert cli_path.read_bytes() == v8_raw
        assert hashlib.sha256(cli_path.read_bytes()).hexdigest() == v8_hash

        v9_candidate = copy.deepcopy(migrated)
        v9_candidate["work"]["planning"]["effort"] = "low"
        # 改动只读 modes 的 v8→v9 候选必须被拒且原字节不变。
        tampered = copy.deepcopy(v9_candidate)
        tampered["modes"] = {}
        code, rej = _run(
            cli_path,
            "apply",
            tampered,
            "--base-hash",
            v8_hash,
            "--request-id",
            "req-v9",
            "--evidence",
            str(ev_path),
        )
        assert code == 1 and rej["status"] == "rejected" and cli_path.read_bytes() == v8_raw

        code, applied = _run(
            cli_path,
            "apply",
            v9_candidate,
            "--base-hash",
            v8_hash,
            "--request-id",
            "req-v9",
            "--evidence",
            str(ev_path),
        )
        assert code == 0 and applied["status"] == "applied" and applied["changed"] is True, applied
        saved = json.loads(cli_path.read_text(encoding="utf-8"))
        assert saved == v9_candidate
        assert saved["version"] == 9
        assert saved["modes"] == v8["modes"]
        for task in ("design", "frontend", "backend", "testing"):
            assert saved["work"][task] == migrated["work"][task]

    print("task-types: pass")


if __name__ == "__main__":
    check()

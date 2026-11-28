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

        # S2（R1/DD-687）：v9 候选新增 work.advisory-doc（purpose artifact，三元组在本次 request_id 证据内），
        # apply 返回 applied，show 读回含全部字段且 modes 字节级不变；同一候选改 modes 被拒且原字节不变。
        advisory_entry = {
            "agent": "pi",
            "model": "provider/model",
            "effort": "high",
            "fallbacks": [],
            "label": "咨询建议",
            "hint": "输出调研与方案建议文档",
            "purpose": "artifact",
        }
        custom = copy.deepcopy(migrated)
        custom["work"]["advisory-doc"] = copy.deepcopy(advisory_entry)
        assert m.validate_document(custom) == []

        v9_before_s2 = cli_path.read_bytes()
        v9_hash_s2 = hashlib.sha256(v9_before_s2).hexdigest()
        modes_bytes = json.dumps(migrated["modes"], ensure_ascii=False, indent=2).encode("utf-8")

        custom_tampered_modes = copy.deepcopy(custom)
        custom_tampered_modes["modes"] = {}
        code, rej_modes = _run(
            cli_path,
            "apply",
            custom_tampered_modes,
            "--base-hash",
            v9_hash_s2,
            "--request-id",
            "req-v9",
            "--evidence",
            str(ev_path),
        )
        assert code == 1 and rej_modes["status"] == "rejected", rej_modes
        assert cli_path.read_bytes() == v9_before_s2

        code, applied_s2 = _run(
            cli_path,
            "apply",
            custom,
            "--base-hash",
            v9_hash_s2,
            "--request-id",
            "req-v9",
            "--evidence",
            str(ev_path),
        )
        assert code == 0 and applied_s2["status"] == "applied" and applied_s2["changed"] is True, applied_s2
        custom_raw = cli_path.read_bytes()
        code, shown = _run(cli_path, "show")
        assert code == 0 and shown["file_state"] == "ready" and shown["validation"]["valid"] is True, shown
        assert shown["config"]["work"]["advisory-doc"] == advisory_entry
        assert json.dumps(shown["config"]["modes"], ensure_ascii=False, indent=2).encode("utf-8") == modes_bytes
        assert "work.advisory-doc" in shown["cells"]
        assert shown["cells"]["work.advisory-doc"] == {"status": "unknown"}
        assert cli_path.read_bytes() == custom_raw

        # S5（DD-687）：原模型能力不可用且三元组未改时，改 label/hint 或删另一可选类型不带新证据也 applied；
        # 新增类型或改该类型模型缺本次证据时返回 capability_unavailable 且磁盘原字节不变。
        s5_base = copy.deepcopy(migrated)
        s5_base["work"]["backend"]["model"] = "provider/unavailable-model"
        cli_path.write_text(json.dumps(s5_base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        unavail_ev_path = root / "evidence-unavailable.json"
        unavail_ev_path.write_text(
            json.dumps(
                {
                    "request_id": "req-s5",
                    "observed_at": "2026-11-27T12:10:00Z",
                    "sources": {a: {"status": "unknown"} for a in ("pi", "codex", "claude", "antigravity")},
                    "capabilities": {a: {"binary": True, "models": {}} for a in ("pi", "codex", "claude", "antigravity")},
                }
            ),
            encoding="utf-8",
        )
        s5_hash = hashlib.sha256(cli_path.read_bytes()).hexdigest()
        s5_meta = copy.deepcopy(s5_base)
        s5_meta["work"]["backend"]["label"] = "服务端"
        s5_meta["work"]["backend"]["hint"] = "只改描述不改模型"
        code, res_s5_meta = _run(
            cli_path,
            "apply",
            s5_meta,
            "--base-hash",
            s5_hash,
            "--request-id",
            "req-s5",
            "--evidence",
            str(unavail_ev_path),
        )
        assert code == 0 and res_s5_meta["status"] == "applied" and res_s5_meta["changed"] is True, res_s5_meta
        assert res_s5_meta["config"]["work"]["backend"]["label"] == "服务端"
        assert res_s5_meta["config"]["work"]["backend"]["model"] == "provider/unavailable-model"

        s5_hash = res_s5_meta["base_hash"]
        s5_del = copy.deepcopy(s5_meta)
        del s5_del["work"]["design"]
        code, res_s5_del = _run(
            cli_path,
            "apply",
            s5_del,
            "--base-hash",
            s5_hash,
            "--request-id",
            "req-s5",
            "--evidence",
            str(unavail_ev_path),
        )
        assert code == 0 and res_s5_del["status"] == "applied" and res_s5_del["changed"] is True, res_s5_del
        assert "design" not in res_s5_del["config"]["work"]

        # 不传证据对象（evidence=None）时，仅改 hint 也 applied。
        s5_hash = res_s5_del["base_hash"]
        s5_hint = copy.deepcopy(s5_del)
        s5_hint["work"]["backend"]["hint"] = "无证据更新说明"
        res_s5_none = m.apply(cli_path, s5_hint, s5_hash, None, "req-s5-none")
        assert res_s5_none["status"] == "applied" and res_s5_none["changed"] is True, res_s5_none

        s5_raw = cli_path.read_bytes()
        s5_hash = hashlib.sha256(s5_raw).hexdigest()
        s5_add = copy.deepcopy(s5_hint)
        s5_add["work"]["advisory-doc"] = copy.deepcopy(advisory_entry)
        code, res_s5_add = _run(
            cli_path,
            "apply",
            s5_add,
            "--base-hash",
            s5_hash,
            "--request-id",
            "req-s5",
            "--evidence",
            str(unavail_ev_path),
        )
        assert code == 1 and res_s5_add["status"] == "rejected" and res_s5_add["error"]["code"] == "capability_unavailable", res_s5_add
        assert cli_path.read_bytes() == s5_raw

        s5_change = copy.deepcopy(s5_hint)
        s5_change["work"]["backend"]["model"] = "provider/model"
        code, res_s5_change = _run(
            cli_path,
            "apply",
            s5_change,
            "--base-hash",
            s5_hash,
            "--request-id",
            "req-s5",
            "--evidence",
            str(unavail_ev_path),
        )
        assert code == 1 and res_s5_change["status"] == "rejected" and res_s5_change["error"]["code"] == "capability_unavailable", res_s5_change
        assert cli_path.read_bytes() == s5_raw

        # 旧 request_id 证据与 evidence=None 均拒绝改动模型并保持原字节。
        code, res_s5_stale = _run(
            cli_path,
            "apply",
            s5_change,
            "--base-hash",
            s5_hash,
            "--request-id",
            "req-s5-new",
            "--evidence",
            str(ev_path),
        )
        assert code == 1 and res_s5_stale["status"] == "rejected" and res_s5_stale["error"]["code"] == "capability_unavailable", res_s5_stale
        assert cli_path.read_bytes() == s5_raw

        res_s5_none_rej = m.apply(cli_path, s5_add, s5_hash, None, "req-s5-none")
        assert res_s5_none_rej["status"] == "rejected" and res_s5_none_rej["error"]["code"] == "capability_unavailable", res_s5_none_rej
        assert cli_path.read_bytes() == s5_raw

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

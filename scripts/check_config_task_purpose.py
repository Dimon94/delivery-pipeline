#!/usr/bin/env python3
"""DD-688：执行计划按用途解析、preview_review_choice 按 code 用途计入厂商、已删除类型新派发阻断（S6/S7）。"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_config_transaction import m, SCRIPT, ROOT


def _identity(model: str, effort: str = "high", agent: str = "pi") -> dict:
    return {"agent": agent, "model": model, "effort": effort}


def _v9_fixture() -> tuple[dict, dict, dict]:
    doc = m.migrate_document(m.valid_fixture())[0]
    for task in list(doc["work"]):
        doc["work"][task] = {**doc["work"][task], **_identity("gpt-6.1-sol"), "fallbacks": []}
    for scope in doc["review"].values():
        for axis in scope:
            scope[axis] = {**_identity("gpt-6.1-sol"), "candidates": []}
    doc["review"]["whole-change"]["standards"]["candidates"] = [_identity("claude-opus-5-5")]

    doc["modes"]["fast"] = {
        "kind": "direct",
        "agents": {
            "pi": {
                "starting": {"model": "gpt-6.1-mini", "effort": "low"},
                "execution": {"model": "gpt-6.1-mini", "effort": "low"},
                "direct": {"model": "gpt-6.1-mini", "effort": "low"},
            }
        },
    }
    doc["work"]["advisory-doc"] = {
        **_identity("claude-opus-5-5", "high"),
        "fallbacks": [_identity("gpt-6.1-sol", "medium")],
        "label": "咨询建议",
        "hint": "输出调研与方案建议文档",
        "purpose": "artifact",
    }
    doc["work"]["rust-service"] = {
        **_identity("gpt-6.1-sol", "high"),
        "fallbacks": [_identity("claude-opus-5-5", "medium")],
        "label": "Rust 服务",
        "hint": "写 Rust 服务端代码",
        "purpose": "code",
    }

    capabilities = {
        "pi": {
            "binary": True,
            "models": {
                "gpt-6.1-sol": ["low", "medium", "high"],
                "gpt-6.1-mini": ["low", "medium", "high"],
                "claude-opus-5-5": ["low", "medium", "high"],
            },
        }
    }
    envelope = {
        "request_id": "req-dd688",
        "observed_at": "2026-11-27T12:00:00Z",
        "sources": {"pi": {"status": "ok"}},
        "capabilities": capabilities,
    }
    return doc, capabilities, envelope


def _run_cli(command: str, *args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), command, *args],
        text=True,
        capture_output=True,
    )
    assert proc.stdout.strip(), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def check() -> None:
    doc, capabilities, envelope = _v9_fixture()
    assert m.validate_document(doc) == []

    # 公开 task_purpose 接口：返回已定义项的 purpose，缺失项报错。
    assert m.task_purpose(doc, "frontend") == "code"
    assert m.task_purpose(doc, "advisory-doc") == "artifact"
    try:
        m.task_purpose(doc, "nonexistent-task")
    except ValueError as err:
        assert str(err) == "task type not defined in config: nonexistent-task", str(err)
    else:
        raise AssertionError("task_purpose unexpectedly succeeded for missing task")

    # 合法 v8 可选任务 research 也冻结 recovery_plan。
    v8_opt = m.apply_limits(m.valid_fixture(), m.DEFAULT_LIMITS.copy())
    v8_opt["work"]["research"] = m.triple(v8_opt["work"]["backend"])
    assert m.validate_document(v8_opt) == []
    res_v8 = m.resolve_plan(v8_opt, "research", output_mode="artifact")
    assert res_v8["purpose"] == "artifact" and "recovery_plan" in res_v8, res_v8
    assert res_v8["recovery_plan"]["fallbacks"] == [], res_v8

    # ST-5：内置 planning 被合法替换为唯一 planning 用途类型 plan-notes 时，默认 planning 入口按用途解析。
    doc_plan = copy.deepcopy(doc)
    doc_plan["work"]["plan-notes"] = doc_plan["work"].pop("planning")
    assert m.validate_document(doc_plan) == []
    assert m.resolve_planning_task(doc_plan) == "plan-notes"
    plan_entry = m.resolve_plan(doc_plan, "planning", output_mode="artifact", evidence=capabilities)
    assert plan_entry["task"] == "plan-notes" and plan_entry["purpose"] == "planning", plan_entry

    # S6-1: advisory-doc (purpose=artifact) 返回主三元组、purpose=artifact、含 fallbacks 的 recovery_plan 且不套 modes。
    advisory_plan = m.resolve_plan(
        doc,
        "advisory-doc",
        output_mode="artifact",
        ticket_mode="fast",
        evidence=capabilities,
    )
    assert (advisory_plan["agent"], advisory_plan["model"], advisory_plan["effort"]) == (
        "pi",
        "claude-opus-5-5",
        "high",
    ), advisory_plan
    assert advisory_plan["purpose"] == "artifact", advisory_plan
    assert advisory_plan["mode"] == "none" and advisory_plan["mode_name"] is None, advisory_plan
    assert advisory_plan["source"] == "work" and advisory_plan["capability"] == "verified", advisory_plan
    assert advisory_plan["recovery_plan"] == {
        "plan_version": 1,
        "source": "work",
        "primary": _identity("claude-opus-5-5", "high"),
        "fallbacks": [_identity("gpt-6.1-sol", "medium")],
    }, advisory_plan
    assert advisory_plan["recovery_progress"] == {"current_index": None, "next_cursor": 0}, advisory_plan

    # 非 code 用途即使传 output_mode=commit 也不套 modes。
    advisory_commit = m.resolve_plan(
        doc,
        "advisory-doc",
        output_mode="commit",
        ticket_mode="fast",
        evidence=capabilities,
    )
    assert advisory_commit["mode"] == "none" and advisory_commit["mode_name"] is None
    assert advisory_commit["model"] == "claude-opus-5-5" and advisory_commit["effort"] == "high"
    assert advisory_commit["recovery_plan"]["source"] == "work"

    # S6-2: rust-service (purpose=code) 在 commit + ticket_mode=fast 下返回 modes.fast 三元组。
    rust_fast = m.resolve_plan(
        doc,
        "rust-service",
        output_mode="commit",
        ticket_mode="fast",
        evidence=capabilities,
    )
    assert (rust_fast["agent"], rust_fast["model"], rust_fast["effort"]) == (
        "pi",
        "gpt-6.1-mini",
        "low",
    ), rust_fast
    assert rust_fast["purpose"] == "code", rust_fast
    assert rust_fast["mode"] == "direct" and rust_fast["mode_name"] == "fast", rust_fast
    assert rust_fast["source"] == "ticket" and rust_fast["capability"] == "verified", rust_fast
    assert rust_fast["recovery_plan"] == {
        "plan_version": 1,
        "source": "explicit_mode",
        "primary": _identity("gpt-6.1-mini", "low"),
        "fallbacks": [],
    }, rust_fast

    # rust-service 不带 mode 时返回自身主三元组与 fallbacks；非 commit 不套 modes。
    rust_default = m.resolve_plan(doc, "rust-service", output_mode="commit", evidence=capabilities)
    assert (rust_default["model"], rust_default["effort"]) == ("gpt-6.1-sol", "high")
    assert rust_default["recovery_plan"]["fallbacks"] == [_identity("claude-opus-5-5", "medium")]
    rust_artifact = m.resolve_plan(doc, "rust-service", output_mode="artifact", ticket_mode="fast")
    assert rust_artifact["mode"] == "none" and rust_artifact["model"] == "gpt-6.1-sol"

    # S6-3: preview_review_choice 计入 rust-service(code) 厂商，不计 advisory-doc(artifact)。
    preview_a = m.preview_review_choice(doc, envelope)
    assert preview_a["standards"] == {
        "selected": _identity("claude-opus-5-5", "high"),
        "selected_index": 1,
        "outcome": "different",
        "unrecognized": [],
    }, preview_a

    # 删掉内置 design/frontend，仅保留 backend(openai) 与 rust-service(anthropic) 作为 code；
    # advisory-doc(artifact) 仍不影响写代码一方，而 rust-service 改 anthropic 后触发 no_different_family。
    doc_b = copy.deepcopy(doc)
    del doc_b["work"]["design"]
    del doc_b["work"]["frontend"]
    doc_b["work"]["rust-service"]["model"] = "claude-opus-5-5"
    assert m.validate_document(doc_b) == []
    preview_b = m.preview_review_choice(doc_b, envelope)
    assert preview_b["standards"] == {
        "selected": _identity("gpt-6.1-sol", "high"),
        "selected_index": 0,
        "outcome": "no_different_family",
        "unrecognized": [],
    }, preview_b

    # S7: registry 已冻结 advisory-doc 后配置删除该类型，recover_registry 返回原冻结计划，
    # resolve_plan 与 CLI resolve/start 均失败并报 task type not defined in config: advisory-doc，无回落模型。
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config_path = root / "model-roles.json"
        evidence_path = root / "evidence.json"
        registry_path = root / "registry-advisory.md"

        evidence_path.write_text(json.dumps(capabilities), encoding="utf-8")
        overlay = m.freeze_overlay(advisory_plan)
        m.verify_overlay(advisory_plan, overlay)

        spec = importlib.util.spec_from_file_location(
            "dispatch", ROOT / "skills/delivery-pipeline-herdr/scripts/dispatch.py"
        )
        dispatch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dispatch)
        row = {
            "lane_id": "dd688-advisory",
            "work_item": "DD-688",
            "role": "advisory-doc",
            "output_mode": "artifact",
            "runtime": "herdr-pi-pane",
            "state": "running",
            **overlay,
        }
        dispatch.write_registry(registry_path, row)

        deleted_doc = copy.deepcopy(doc)
        del deleted_doc["work"]["advisory-doc"]
        assert m.validate_document(deleted_doc) == []
        config_path.write_text(json.dumps(deleted_doc, indent=2) + "\n", encoding="utf-8")

        recovered = m.recover_registry(registry_path)
        assert recovered["status"] == "frozen", recovered
        assert recovered["recovery_plan"] == overlay["recovery_plan"], recovered
        assert recovered["recovery_progress"] == overlay["recovery_progress"], recovered
        assert (recovered["agent"], recovered["model"], recovered["effort"]) == (
            "pi",
            "claude-opus-5-5",
            "high",
        ), recovered

        expected_err = "task type not defined in config: advisory-doc"
        try:
            m.resolve_plan(deleted_doc, "advisory-doc", output_mode="artifact", evidence=capabilities)
        except ValueError as err:
            assert str(err) == expected_err, str(err)
        else:
            raise AssertionError("resolve_plan unexpectedly succeeded for deleted task type")

        for command, extra in (
            ("resolve", []),
            ("start", ["--worker-name", "w", "--pane-id", "p"]),
        ):
            code, payload = _run_cli(
                command,
                str(config_path),
                "advisory-doc",
                "--output-mode",
                "artifact",
                "--evidence",
                str(evidence_path),
                *extra,
            )
            assert code != 0, (command, payload)
            assert payload == {"valid": False, "errors": [expected_err]}, (command, payload)
            assert "model" not in payload and "agent" not in payload and "recovery_plan" not in payload

    print("task-purpose: pass")


if __name__ == "__main__":
    check()

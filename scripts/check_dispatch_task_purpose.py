#!/usr/bin/env python3
"""DD-689：Driver 与各 Transport 按任务类型用途派发、whole-change checks 替换与已删除类型阻断（S6/S7）。"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "skills/delivery-pipeline/scripts"),
    str(ROOT / "skills/delivery-pipeline-setup/scripts"),
]
import driver  # noqa: E402
import lane_registry  # noqa: E402
import model_config as mc  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _identity(model: str, effort: str = "high", agent: str = "pi") -> dict:
    return {"agent": agent, "model": model, "effort": effort}


def _v9_config() -> tuple[dict, dict]:
    doc = mc.migrate_document(mc.valid_fixture())[0]
    for task in list(doc["work"]):
        doc["work"][task] = {
            **doc["work"][task],
            **_identity("magpie/gpt-6.1-sol", "high"),
            "fallbacks": [],
        }
    for scope in doc["review"].values():
        for axis in scope:
            scope[axis] = {**_identity("magpie/gpt-6.1-sol", "high"), "candidates": []}

    doc["modes"]["fast"] = {
        "kind": "direct",
        "agents": {
            "pi": {
                "starting": {"model": "magpie/gpt-6.1-mini", "effort": "low"},
                "execution": {"model": "magpie/gpt-6.1-mini", "effort": "low"},
                "direct": {"model": "magpie/gpt-6.1-mini", "effort": "low"},
            }
        },
    }
    doc["work"]["advisory-doc"] = {
        **_identity("magpie/claude-opus-5-5", "high"),
        "fallbacks": [_identity("magpie/gpt-6.1-sol", "medium")],
        "label": "咨询建议",
        "hint": "输出调研与方案建议文档",
        "purpose": "artifact",
    }
    doc["work"]["rust-service"] = {
        **_identity("magpie/gpt-6.1-sol", "high"),
        "fallbacks": [_identity("magpie/claude-opus-5-5", "medium")],
        "label": "Rust 服务",
        "hint": "写 Rust 服务端代码",
        "purpose": "code",
    }
    assert mc.validate_document(doc) == [], mc.validate_document(doc)

    capabilities = {
        "pi": {
            "binary": True,
            "models": {
                "magpie/gpt-6.1-sol": ["low", "medium", "high"],
                "magpie/gpt-6.1-mini": ["low", "medium", "high"],
                "magpie/claude-opus-5-5": ["low", "medium", "high"],
            },
        }
    }
    return doc, capabilities


def _write_config(home: Path, doc: dict) -> Path:
    path = home / ".config/delivery-pipeline/model-roles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _make_map(map_dir: Path, tickets: list[dict], *, map_id: str = "m-dd689") -> None:
    map_dir.mkdir(parents=True, exist_ok=True)
    plan = {"tickets": tickets, "test_strategy": {"level": "focused"}, "risk": "low"}
    sha = driver.plan_sha(plan)
    driver.write_json(
        map_dir / driver.DRIVER_FILE,
        {
            "version": driver.VERSION,
            "map": map_id,
            "gates": {"discovery": "d", "spec": "s", "tickets": "t"},
            "plan": plan,
            "plan_check": "pass",
            "grant": {"plan_sha": sha},
            "published": "p",
            "test_strategy": {"level": "focused", "scope_sha": sha, "risk": "low"},
            "scope": {"sha": sha, "risk": "low"},
        },
    )
    driver.persist_lanes(
        map_dir,
        [
            {
                "lane_id": map_id,
                "work_item": map_id,
                "role": "map",
                "output_mode": "none",
                "state": "running",
                "integration_worktree_path": str(map_dir),
                "_file": str(map_dir / "registry.md"),
            }
        ],
    )


def _brief(ticket_id: str) -> dict:
    return {
        "ticket": ticket_id,
        "slice_id": "all",
        "writable": ["src/lib.rs"],
        "read_first": ["README.md"],
        "check": ["true"],
        "expected": "ok",
    }


def _t3_caps(model: str, effort: str) -> dict:
    return {
        "parentThreadId": "parent",
        "inheritedProviderInstanceId": "pi",
        "providers": [
            {
                "providerInstanceId": "pi",
                "canRunChildTask": True,
                "canRunCrossProviderChildTask": True,
                "models": [
                    {
                        "id": model,
                        "options": [{"id": "thinking", "values": [effort]}],
                    }
                ],
            }
        ],
    }


def check() -> None:
    doc, capabilities = _v9_config()
    advisory_plan = mc.resolve_plan(
        doc, "advisory-doc", output_mode="artifact", ticket_mode="fast", evidence=capabilities
    )
    rust_fast_plan = mc.resolve_plan(
        doc, "rust-service", output_mode="commit", ticket_mode="fast", evidence=capabilities
    )
    assert (rust_fast_plan["agent"], rust_fast_plan["model"], rust_fast_plan["effort"]) == (
        "pi",
        "magpie/gpt-6.1-mini",
        "low",
    ), rust_fast_plan

    check_work_dispatch = _load_module(
        "check_work_dispatch", ROOT / "skills/delivery-pipeline-t3code/scripts/check_work_dispatch.py"
    )
    dispatch_check = _load_module(
        "dispatch_check", ROOT / "skills/delivery-pipeline-herdr/scripts/dispatch_check.py"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        home = root / "home"
        home.mkdir()
        _write_config(home, doc)

        with patch.dict(os.environ, {"HOME": str(home), "MAGPIE_API_KEY": "fixture-only"}):
            # ---------- S6-1: Driver 按用途推导 output_mode，artifact 不要求合同，code 要求合同 ----------
            map_s6 = root / "map-s6"
            _make_map(
                map_s6,
                [
                    {"id": "T1", "wave": 1, "task": "advisory-doc", "deps": []},
                    {"id": "T2", "wave": 1, "task": "rust-service", "ticket_mode": "fast", "deps": ["T1"]},
                ],
            )
            a1 = driver.run(map_s6)
            assert a1["action"] == "dispatch" and a1["id"] == "dispatch:T1", a1
            assert a1["args"]["task"] == "advisory-doc", a1
            assert a1["args"]["output_mode"] == "artifact", a1
            assert "contract" not in a1["args"], a1

            driver.record(
                map_s6,
                a1["id"],
                {
                    "lane": {
                        "lane_id": "T1",
                        "work_item": "T1",
                        "role": "advisory-doc",
                        "output_mode": "artifact",
                        "state": "closed",
                    }
                },
            )
            a2_contract = driver.run(map_s6)
            assert a2_contract["action"] == "prepare_contract" and a2_contract["id"] == "contract:T2", a2_contract
            driver.record(map_s6, a2_contract["id"], {"briefs": [_brief("T2")]})
            a2 = driver.run(map_s6)
            assert a2["action"] == "dispatch" and a2["id"] == "dispatch:T2", a2
            assert a2["args"]["task"] == "rust-service", a2
            assert a2["args"]["output_mode"] == "commit", a2
            assert a2["args"]["ticket_mode"] == "fast", a2

            # ---------- S6-2: T3Code WorkDispatch 冻结 role 分别为 design 与 implementation ----------
            t3_repo = root / "t3-repo"
            t3_repo.mkdir()
            subprocess.run(["git", "init", "-q", str(t3_repo)], check=True)
            t3_status = {"attached": False, "projectWorkspaceRoot": str(t3_repo)}

            t3_adv_reg = t3_repo / "registry-t3-adv.md"
            t3_adv_req = {
                "action": "dispatch",
                "path": str(t3_adv_reg),
                "row": {
                    "lane_id": "t3-adv",
                    "work_item": "DD-689-A",
                    "role": "advisory-doc",
                    "output_mode": "artifact",
                    "base_commit": "a" * 40,
                    "map": "m-dd689",
                },
                "task": "advisory packet",
                "source": str(t3_repo),
                "ticket_mode": "fast",
            }
            adv_receipt = {"taskId": "task-adv", "childThreadId": "child-adv", "next": "yield"}
            adv_res, adv_calls = check_work_dispatch.invoke(
                t3_adv_req,
                [
                    ("orchestrator_capabilities", _t3_caps(advisory_plan["model"], advisory_plan["effort"])),
                    ("t3_worktree_status", t3_status),
                    ("delegate_task", adv_receipt),
                ],
            )
            assert adv_res["state"] == "created", adv_res
            assert adv_calls[2]["role"] == "design", adv_calls[2]
            assert adv_res["t3code"]["native_request"]["role"] == "design", adv_res
            assert (adv_res["agent"], adv_res["model"], adv_res["effort"]) == (
                advisory_plan["agent"],
                advisory_plan["model"],
                advisory_plan["effort"],
            ), adv_res
            assert adv_res["recovery_plan"] == advisory_plan["recovery_plan"], adv_res

            t3_rust_reg = t3_repo / "registry-t3-rust.md"
            t3_rust_req = {
                "action": "dispatch",
                "path": str(t3_rust_reg),
                "row": {
                    "lane_id": "t3-rust",
                    "work_item": "DD-689-B",
                    "role": "rust-service",
                    "output_mode": "commit",
                    "base_commit": "b" * 40,
                    "map": "m-dd689",
                },
                "task": "rust packet",
                "source": str(t3_repo),
                "ticket_mode": "fast",
            }
            rust_receipt = {"taskId": "task-rust", "childThreadId": "child-rust", "next": "yield"}
            rust_res, rust_calls = check_work_dispatch.invoke(
                t3_rust_req,
                [
                    ("orchestrator_capabilities", _t3_caps(rust_fast_plan["model"], rust_fast_plan["effort"])),
                    ("t3_worktree_status", t3_status),
                    ("delegate_task", rust_receipt),
                ],
            )
            assert rust_res["state"] == "created", rust_res
            assert rust_calls[2]["role"] == "implementation", rust_calls[2]
            assert rust_res["t3code"]["native_request"]["role"] == "implementation", rust_res
            assert (rust_res["agent"], rust_res["model"], rust_res["effort"]) == (
                rust_fast_plan["agent"],
                rust_fast_plan["model"],
                rust_fast_plan["effort"],
            ), rust_res
            assert rust_res["recovery_plan"] == rust_fast_plan["recovery_plan"], rust_res

            # ---------- S6-3: Herdr dispatch 与 delivery-dispatch 冻结三元组与 resolve_plan 一致 ----------
            herdr_root = root / "herdr-sim"
            herdr_root.mkdir()
            (herdr_root / "herdr").write_text(f"#!{sys.executable}\n" + dispatch_check.FAKE_HERDR)
            (herdr_root / "watch").write_text("#!/bin/sh\nexit 0\n")
            for name in ("herdr", "watch"):
                (herdr_root / name).chmod(0o755)
            herdr_base = {
                "tabs": [{"tab_id": "w1:t1", "label": "coord", "pane_count": 1, "workspace_id": "w1"}],
                "panes": [{"pane_id": "w1:p1", "tab_id": "w1:t1", "workspace_id": "w1"}],
            }

            def _herdr_dispatch(lane: str, task: str, output_mode: str, extra: tuple[str, ...] = ()):
                (herdr_root / "state.json").write_text(json.dumps(copy.deepcopy(herdr_base)))
                (herdr_root / "calls.jsonl").write_text("")
                ev_path = herdr_root / "evidence.json"
                ev_path.write_text(json.dumps(capabilities))
                pkt = herdr_root / f"packet-{lane}.md"
                pkt.write_text("packet\n")
                reg = herdr_root / f"registry-{lane}.md"
                map_reg = herdr_root / "registry-map-demo.md"
                map_reg.write_text(dispatch_check.GOOD_MAP)
                env = {
                    **os.environ,
                    "HOME": str(home),
                    "PATH": f"{herdr_root}:{os.environ['PATH']}",
                    "HERDR_ENV": "1",
                    "HERDR_WORKSPACE_ID": "w1",
                    "HERDR_TAB_ID": "w1:t1",
                    "HERDR_PANE_ID": "w1:p1",
                    "DP_LANE_WATCH": str(herdr_root / "watch"),
                }
                proc = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "skills/delivery-pipeline-herdr/scripts/dispatch.py"),
                        "--evidence",
                        str(ev_path),
                        "--task",
                        task,
                        "--output-mode",
                        output_mode,
                        "--lane",
                        lane,
                        "--work-item",
                        "https://x/1",
                        "--title",
                        "#1 演示",
                        "--tab-prefix",
                        "#1 实施",
                        "--worktree",
                        str(herdr_root),
                        "--branch",
                        "b",
                        "--base",
                        "abc",
                        "--packet",
                        str(pkt),
                        "--registry",
                        str(reg),
                        "--map-registry",
                        str(map_reg),
                        *extra,
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                return proc, reg

            p_adv, herdr_adv_reg = _herdr_dispatch(
                "lane-adv", "advisory-doc", "artifact", ("--ticket-mode", "fast")
            )
            assert p_adv.returncode == 0, (p_adv.stdout, p_adv.stderr)
            herdr_adv_row, _ = lane_registry.read(herdr_adv_reg, "lane-adv")
            assert (herdr_adv_row["agent"], herdr_adv_row["model"], herdr_adv_row["effort"]) == (
                advisory_plan["agent"],
                advisory_plan["model"],
                advisory_plan["effort"],
            ), herdr_adv_row
            assert herdr_adv_row["recovery_plan"] == advisory_plan["recovery_plan"], herdr_adv_row

            p_rust, herdr_rust_reg = _herdr_dispatch(
                "lane-rust", "rust-service", "commit", ("--ticket-mode", "fast")
            )
            assert p_rust.returncode == 0, (p_rust.stdout, p_rust.stderr)
            herdr_rust_row, _ = lane_registry.read(herdr_rust_reg, "lane-rust")
            assert (herdr_rust_row["agent"], herdr_rust_row["model"], herdr_rust_row["effort"]) == (
                rust_fast_plan["agent"],
                rust_fast_plan["model"],
                rust_fast_plan["effort"],
            ), herdr_rust_row
            assert herdr_rust_row["recovery_plan"] == rust_fast_plan["recovery_plan"], herdr_rust_row

            # delivery-dispatch preflight 与 resolve_plan 一致
            dd_cli = str(ROOT / "scripts/delivery-dispatch")
            pf = subprocess.run(
                [dd_cli, "preflight", "advisory-doc", "rust-service", "--mode", "fast"],
                capture_output=True,
                text=True,
            )
            assert pf.returncode == 0, (pf.stdout, pf.stderr)
            pf_rows = {row["task"]: row for row in map(json.loads, pf.stdout.splitlines())}
            assert (pf_rows["advisory-doc"]["agent"], pf_rows["advisory-doc"]["model"], pf_rows["advisory-doc"]["effort"]) == (
                advisory_plan["agent"],
                advisory_plan["model"],
                advisory_plan["effort"],
            ), pf_rows
            assert (pf_rows["rust-service"]["agent"], pf_rows["rust-service"]["model"], pf_rows["rust-service"]["effort"]) == (
                rust_fast_plan["agent"],
                rust_fast_plan["model"],
                rust_fast_plan["effort"],
            ), pf_rows

            # ---------- S6-4: 删除同名 testing 键、另有一个 checks 类型时 whole-change testing 解析到该类型 ----------
            doc_checks = copy.deepcopy(doc)
            del doc_checks["work"]["testing"]
            doc_checks["work"]["qa-checks"] = {
                **_identity("magpie/gpt-6.1-sol", "high"),
                "fallbacks": [],
                "label": "质量验证",
                "hint": "运行整票验收测试",
                "purpose": "checks",
            }
            assert mc.validate_document(doc_checks) == [], mc.validate_document(doc_checks)
            _write_config(home, doc_checks)

            driver.record(
                map_s6,
                a2["id"],
                {
                    "lane": {
                        "lane_id": "T2",
                        "work_item": "T2",
                        "role": "rust-service",
                        "output_mode": "commit",
                        "state": "closed",
                    }
                },
            )
            a_test = driver.run(map_s6)
            assert a_test["action"] == "dispatch" and a_test["id"] == "dispatch:testing", a_test
            assert a_test["args"]["task"] == "qa-checks", a_test
            assert a_test["args"]["output_mode"] == "checks", a_test
            assert a_test["args"]["work_item"] == "m-dd689#testing", a_test

            driver.record(
                map_s6,
                a_test["id"],
                {
                    "lane": {
                        "lane_id": a_test["args"]["lane_id"],
                        "work_item": a_test["args"]["work_item"],
                        "role": "qa-checks",
                        "output_mode": "checks",
                        "state": "closed",
                    }
                },
            )
            a_review = driver.run(map_s6)
            assert a_review["action"] == "dispatch" and a_review["id"] == "dispatch:review", a_review

            # ---------- S7: 删除 advisory-doc 后新票 halt 且不写新 lane；已冻结旧 lane 仍按 recovery_plan 恢复 ----------
            doc_deleted = copy.deepcopy(doc)
            del doc_deleted["work"]["advisory-doc"]
            assert mc.validate_document(doc_deleted) == [], mc.validate_document(doc_deleted)
            _write_config(home, doc_deleted)

            map_s7 = root / "map-s7"
            _make_map(
                map_s7,
                [{"id": "T-new", "wave": 1, "task": "advisory-doc", "deps": []}],
                map_id="m-s7",
            )
            lanes_before = set(driver.load(map_s7)["lanes"])
            halt_action = driver.run(map_s7)
            assert halt_action["action"] == "halt", halt_action
            assert "task type not defined in config: advisory-doc" in halt_action["args"]["reason"], halt_action
            lanes_after = set(driver.load(map_s7)["lanes"])
            assert lanes_after == lanes_before == {"m-s7"}, (lanes_before, lanes_after)

            # 已冻结的 Herdr advisory-doc lane 仍按 recovery_plan 恢复
            recovered = mc.recover_registry(herdr_adv_reg)
            assert recovered["status"] == "frozen", recovered
            assert recovered["recovery_plan"] == advisory_plan["recovery_plan"], recovered
            assert (recovered["agent"], recovered["model"], recovered["effort"]) == (
                advisory_plan["agent"],
                advisory_plan["model"],
                advisory_plan["effort"],
            ), recovered

            # 已冻结的 T3Code advisory-doc lane 仍可 recover 而不依赖配置中存在 advisory-doc
            child_wt = t3_repo / "child-adv"
            child_wt.mkdir()
            (child_wt / ".git").write_text(f"gitdir: {t3_repo / '.git'}\n")
            t3_thread = {
                "threadId": "child-adv",
                "parentThreadId": "parent",
                "relationshipToParent": "subagent",
                "providerInstanceId": "pi",
                "model": advisory_plan["model"],
                "worktreePath": str(child_wt),
                "branch": "temp",
            }
            rec_res, _ = check_work_dispatch.invoke(
                {"action": "recover", "path": str(t3_adv_reg), "lane": "t3-adv"},
                [("t3_thread_read", {"thread": t3_thread, "recentRuns": [{"executedModel": advisory_plan["model"]}]})],
            )
            assert rec_res["state"] == "running" and rec_res["recovery_plan"] == advisory_plan["recovery_plan"], rec_res

    print("dispatch-task-purpose: pass")


if __name__ == "__main__":
    check()

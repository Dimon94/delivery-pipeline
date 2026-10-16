#!/usr/bin/env python3
"""分派 CLI 的可观察行为检查；隔离临时 Git repo，无 App 请求。"""

import copy
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
import os
import runpy
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HELPER = Path(__file__).with_name("prewalk.py")
CHECKPOINT = runpy.run_path(
    str(HELPER.resolve().parents[2] / "delivery-pipeline/scripts/checkpoint.py")
)
EXECUTION_TARGET_MARKER = "app.execution_target:"


def git_env():
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def call(command, data, success=True, extra_env=None) -> Any:
    env = git_env()
    env.update(extra_env or {})
    result = subprocess.run(
        [sys.executable, str(HELPER), command],
        input=json.dumps(data),
        text=True,
        capture_output=True,
        env=env,
    )
    assert (result.returncode == 0) == success, result.stderr or result.stdout
    return json.loads(result.stdout) if success else result.stderr


def check_review_preflight():
    """回放真实 Git 边界；只测试机械门，不重跑业务检查。"""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "repo"
        root.mkdir()

        def git(*args):
            return subprocess.check_output(
                ["git", "-C", str(root), *args], env=git_env(), stderr=subprocess.PIPE
            ).decode().strip()

        with patch.dict(os.environ, {
            "GIT_CONFIG_PARAMETERS": "'core.bare=true'", "GIT_PREFIX": "caller/",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": str(root / "caller-worktree"), "FIXTURE_CONTEXT": "keep",
        }):
            env = git_env()
            assert not [key for key in env if key.startswith("GIT_")], sorted(key for key in env if key.startswith("GIT_"))
            assert env["FIXTURE_CONTEXT"] == "keep"
            git("init", "-b", "probe")
        assert git("config", "--get", "core.bare") == "false"
        git("config", "user.name", "Probe")
        git("config", "user.email", "probe@example.invalid")
        (root / "base.txt").write_text("base\n")
        for name in ("prod/dep.txt", "runtime/config.txt"):
            (root / name).parent.mkdir()
            (root / name).write_text("unchanged input\n")
        git("add", ".")
        git("commit", "-m", "base")
        base = git("rev-parse", "HEAD")
        (root / "body.txt").write_text("body\n")
        (root / "prior-only.txt").write_text("prior fixture\n")
        git("add", ".")
        git("commit", "-m", "prior")
        prior = git("rev-parse", "HEAD")
        (root / "prior-only.txt").unlink()
        (root / "new.txt").write_text("new\n")
        git("add", "-A")
        git("commit", "-m", "candidate")
        head = git("rev-parse", "HEAD")
        plan = {
            "worktree": str(root), "head_commit": head,
            "checks_source": "fixture module AGENTS and CI readback",
            "required_checks": [
                {"command": "TZ=UTC go test ./...", "cwd": str(root), "source": "module AGENTS"},
                {"command": "TZ=Asia/Shanghai go test ./...", "cwd": str(root), "source": "module AGENTS"},
            ],
        }
        data = {
            **plan, "base_commit": base, "target_commit": base, "review_scope": "whole-change",
            "bundle_path": str(Path(folder) / "bundle"), "check_results": [],
        }
        dispatch = {
            "work": "review", "active_count": 0, "source": "host list",
            "read_only": True, "review_scope": "whole-change", "preflight": data,
        }
        # 原入口会先派出昂贵两轴；现在缺终态必须在 invoke-owner 前非零。
        assert "required_checks[0]" in call("subagent", dispatch, False)
        candidate = call("checks", plan)["candidate_sha256"]
        results = []
        for index, requirement in enumerate(plan["required_checks"]):
            log = Path(folder) / f"check-{index}.log"
            log.write_text("fixture terminal exit 0 (not business execution)\n")
            results.append({
                **requirement, "head_commit": head, "candidate_sha256": candidate,
                "status": "completed", "exit_code": 0,
                "stdout_log": str(log), "stderr_log": str(log),
            })
        data["check_results"] = results
        missing_tz = {**data, "check_results": results[:1]}
        assert "required_checks[1]" in call("preflight", missing_tz, False)
        wrong_head = copy.deepcopy(data)
        wrong_head["check_results"][1]["head_commit"] = prior
        assert "head_commit" in call("preflight", wrong_head, False)
        for field, value in (("status", "running"), ("exit_code", 1), ("exit_code", False),
                             ("stdout_log", "/missing.log"), ("stderr_log", "/missing.log")):
            bad = copy.deepcopy(data)
            bad["check_results"][1][field] = value
            error = call("preflight", bad, False)
            assert field in error
            if field in ("stdout_log", "stderr_log"):
                assert all(text in error for text in (
                    "下一步", "保存当前候选的真实日志", "修正绝对路径", "重新预检"
                )), error
        invalid_text = (
            ("missing", None), ("blank", ""), ("blank", " \t\n"),
            ("unknown", "Unknown"), ("unknown", " unknown "),
            ("placeholder", "none"), ("placeholder", "null"),
            ("nontext", None), ("nontext", False), ("nontext", 42),
            ("nontext", []), ("nontext", {}),
        )
        log_action = "下一步：保存当前候选的真实日志、修正绝对路径后重新预检"
        for key in ("stdout_log", "stderr_log"):
            for kind, value in (*invalid_text, ("relative", "check-0.log"),
                                ("missing-file", str(Path(folder) / "missing.log")),
                                ("directory", folder), ("nul-path", folder + "/\0")):
                bad = copy.deepcopy(data)
                if kind == "missing":
                    del bad["check_results"][1][key]
                else:
                    bad["check_results"][1][key] = value
                assert call("checks", bad)["action"] == "checks-listed"
                error = call("preflight", bad, False)
                assert all(text in error for text in (
                    "required_checks[1]." + key, log_action,
                )), (key, kind, error)
        for kind, value in invalid_text:
            bad = copy.deepcopy(data)
            if kind == "missing":
                del bad["checks_source"]
            else:
                bad["checks_source"] = value
            for command in ("checks", "preflight"):
                error = call(command, bad, False)
                assert all(text in error for text in (
                    "checks_source", "下一步：补齐该字段为有效文本后重新预检",
                )), (command, kind, error)
        for requirement, field, action in (
            (None, "required_checks[1]", "补齐 command/cwd/source"),
            *(({**plan["required_checks"][1], "cwd": cwd}, "required_checks[1].cwd",
               "修正为当前 repo 内的绝对目录")
              for cwd in (folder, "relative", str(root / "missing"), str(root / "base.txt"))),
            (plan["required_checks"][0], "required_checks[1]", "合并重复条目"),
        ):
            bad = copy.deepcopy(plan)
            bad["required_checks"][1] = requirement
            error = call("checks", bad, False)
            assert all(text in error for text in (field, "下一步", action, "重新预检")), error
        for key in ("command", "cwd", "source"):
            for kind, value in invalid_text:
                bad = copy.deepcopy(data)
                if kind == "missing":
                    del bad["required_checks"][1][key]
                else:
                    bad["required_checks"][1][key] = value
                for command in ("checks", "preflight"):
                    error = call(command, bad, False)
                    assert all(text in error for text in (
                        "required_checks[1]." + key,
                        "下一步：补齐该字段为有效文本后重新预检",
                    )), (command, key, kind, error)
        made = call("bundle", data)
        assert made["action"] == "preflight-passed"
        assert made["base_commit"] == base and made["head_commit"] == head
        assert made["target_commit"] == base and made["target_reason"]
        assert len(made["check_decisions"]) == 2
        assert call("preflight", data)["action"] == "preflight-passed"
        # 非祖先 target 不得绕过；fixture 只写自己的对象库。
        tree = git("rev-parse", head + "^{tree}")
        unrelated = subprocess.check_output(
            ["git", "-C", str(root), "commit-tree", tree], input=b"unrelated target\n", env=git_env()
        ).decode().strip()
        bad_target = {**data, "target_commit": unrelated}
        error = call("preflight", bad_target, False)
        assert all(word in error for word in ("target_commit", unrelated, head, "下一步")), error
        assert "target_commit" in call("preflight", {k: v for k, v in data.items() if k != "target_commit"}, False)
        missing_diagnostics = {}
        for command, key, recovery in (
            ("checks", "worktree", "绝对路径"),
            ("preflight", "base_commit", "固定版本"),
            ("preflight", "bundle_path", "绝对路径"),
        ):
            bad = copy.deepcopy(data)
            del bad[key]
            error = json.loads(call(command, bad, False))
            assert set(error) == {"error"}, error
            if not all(text in error["error"] for text in (key, "下一步", "补齐", recovery, "重新预检")):
                missing_diagnostics[key] = error["error"]
        assert not missing_diagnostics, missing_diagnostics
        bundle = Path(data["bundle_path"])
        names = (bundle / "changed-paths.txt").read_text()
        assert "A\tbody.txt" in names and "A\tnew.txt" in names
        assert "prior-only.txt" not in names
        patch_lines = (bundle / "diff.patch").read_text().splitlines()
        for row in names.splitlines():
            status, name, start = row.split("\t")
            assert start.startswith("@") and patch_lines[int(start[1:]) - 1] == f"diff --git a/{name} b/{name}", row
        assert (bundle / "fixed-point-added-paths.txt").read_text() == "A\tbase.txt\nA\tprod/dep.txt\nA\truntime/config.txt\n"
        invoked = call("subagent", dispatch)
        assert invoked["action"] == "invoke-owner"
        assert invoked["preflight"]["target_commit"] == base
        assert "target_commit" in call("subagent", {**dispatch, "target_commit": unrelated}, False)
        originals = {p.name: p.read_bytes() for p in bundle.iterdir()}
        for name, broken in (
            ("changed-paths.txt", b"body.txt\nnew.txt\n"),
            ("changed-paths.txt", b"A\tbody.txt\nD\tprior-only.txt\n"),
            ("fixed-point-added-paths.txt", b"A\tbody.txt\nA\tnew.txt\n"),
            ("fixed-point.txt", originals["fixed-point.txt"].replace(head.encode(), prior.encode())),
            ("diff.patch", originals["diff.patch"].replace(b"+body", b"+other")),
        ):
            (bundle / name).write_bytes(broken)
            assert name in call("preflight", data, False)
            assert (bundle / name).read_bytes() == broken  # 门禁保留原 FAIL bytes。
            (bundle / name).write_bytes(originals[name])
        for name in originals:
            (bundle / name).write_bytes(originals[name].removesuffix(b"\n"))
        assert call("preflight", data)["action"] == "preflight-passed"
        for name, raw in originals.items():
            (bundle / name).write_bytes(raw)
        helper = runpy.run_path(str(HELPER.resolve().parents[2] / "delivery-pipeline/scripts/review_evidence.py"))
        # 只观察真实 Git 调用，并对合成 ignored 正文拒读；不伪造 Git 返回或 snapshot。
        policy_file = root / "ignored-policy.txt"
        policy_dir = root / "ignored-policy-dir"
        policy_dir.mkdir()
        policy_nested = policy_dir / "nested.txt"
        policy_file.write_text("synthetic excluded file\n")
        policy_nested.write_text("synthetic excluded directory input\n")
        exclude = root / ".git/info/exclude"
        original_exclude = exclude.read_bytes()
        exclude.write_bytes(original_exclude + b"\n/ignored-policy.txt\n/ignored-policy-dir/\n")
        policy_data = {**data, "bundle_path": str(Path(folder) / "git-only-bundle")}
        original_run, original_read = subprocess.run, Path.read_bytes
        ignored_enumerations, ignored_reads = [], []
        policy_paths = {policy_file.resolve(), policy_nested.resolve()}

        def observe_git(*args, **kwargs):
            argv = args[0] if args else kwargs["args"]
            if argv[0] == "git" and "--ignored" in argv:
                ignored_enumerations.append(argv)
            return original_run(*args, **kwargs)

        def reject_ignored_read(path):
            if path.resolve() in policy_paths:
                ignored_reads.append(str(path))
                raise PermissionError("synthetic ignored read forbidden")
            return original_read(path)

        with patch.object(subprocess, "run", observe_git), patch.object(Path, "read_bytes", reject_ignored_read):
            for command, payload in (("checks", plan), ("bundle", policy_data), ("preflight", policy_data)):
                stdout, stderr, code = io.StringIO(), io.StringIO(), 0
                with patch.object(sys, "argv", ["review_evidence.py", command]), \
                        patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    try:
                        helper["main"]()
                    except SystemExit as error:
                        code = error.code
                assert code == 0, (command, stderr.getvalue(), ignored_enumerations, ignored_reads)
                assert json.loads(stdout.getvalue())["candidate_sha256"] == candidate
            current_state, current_candidate = helper["current"](plan)
            excluded = helper["CHECKPOINT"]["snapshot_worktree"](root, include_ignored=False)
            assert excluded == current_state and current_candidate == candidate
            assert excluded["ignored"] == {"delivery_input": "Unknown", "fingerprints": {}, "paths": []}
            assert not ignored_enumerations and not ignored_reads
        default = call("snapshot", {"worktree": str(root)})
        assert default["ignored"]["paths"] == ["ignored-policy-dir/nested.txt", "ignored-policy.txt"]
        assert default["ignored"]["delivery_input"] == "Unknown"
        assert all(default["ignored"]["fingerprints"][name]["kind"] == "file" for name in default["ignored"]["paths"])
        assert "ignored 交付输入" in call("snapshot", {"worktree": str(root), "required_ignored": [policy_file.name]}, False)
        for options, field in (({"include_ignored": False, "required_ignored": [policy_file.name]}, "required_ignored"),
                               ({"include_ignored": "false"}, "include_ignored")):
            try:
                helper["CHECKPOINT"]["snapshot_worktree"](root, **options)
            except ValueError as error:
                assert field in str(error)
            else:
                raise AssertionError("读取策略不能跳过 " + field)
        (root / "body.txt").write_text("staged policy input\n")
        git("add", "body.txt")
        (root / "new.txt").write_text("unstaged policy input\n")
        untracked = root / "policy-untracked.txt"
        untracked.write_text("nonignored input\n")
        with patch.object(subprocess, "run", observe_git), patch.object(Path, "read_bytes", reject_ignored_read):
            dirty_state, dirty_candidate = helper["current"](plan)
        assert set(dirty_state["dirty"]) == {"body.txt", "new.txt", untracked.name}
        assert dirty_state["staged"] == ["body.txt"] and dirty_candidate != candidate
        default = call("snapshot", {"worktree": str(root)})
        assert all(dirty_state[key] == default[key] for key in ("head", "dirty", "index_sha256", "working_tree_diff_sha256"))
        assert call("checks", plan)["candidate_sha256"] == dirty_candidate
        assert not ignored_enumerations and not ignored_reads
        git("restore", "--staged", "--worktree", "body.txt", "new.txt")
        untracked.unlink()
        assert call("preflight", policy_data)["candidate_sha256"] == candidate
        policy_file.unlink()
        policy_nested.unlink()
        policy_dir.rmdir()
        exclude.write_bytes(original_exclude)
        assert call("snapshot", {"worktree": str(root)})["ignored"] == {"delivery_input": "none", "fingerprints": {}, "paths": []}
        print("review Git-only: pass (excluded Unknown, default fingerprints, required_ignored, WIP/index/untracked)")
        # 精确注入读取失败，避免 chmod 样本依赖测试用户权限。
        original_read = Path.read_bytes
        for key in ("stdout_log", "stderr_log"):
            bad = copy.deepcopy(data)
            unreadable = Path(folder) / (key + ".log")
            unreadable.write_bytes(b"")
            bad["check_results"][1][key] = str(unreadable)
            failure = PermissionError("sensitive fixture input must not be echoed")

            def read_log(path):
                if path == unreadable:
                    raise failure
                return original_read(path)

            with patch.object(Path, "read_bytes", read_log):
                try:
                    helper["checks"](bad, terminal=True)
                except ValueError as error:
                    assert error.__cause__ is failure
                    assert all(text in str(error) for text in (
                        "required_checks[1]." + key, log_action, "PermissionError",
                    )), str(error)
                else:
                    raise AssertionError("日志读取失败不能通过")
                stderr = io.StringIO()
                with patch.object(sys, "argv", ["review_evidence.py", "preflight"]), \
                        patch.object(sys, "stdin", io.StringIO(json.dumps(bad))), redirect_stderr(stderr):
                    try:
                        helper["main"]()
                    except SystemExit as error:
                        assert error.code == 1
                    else:
                        raise AssertionError("日志读取失败 CLI 必须非零")
                error = json.loads(stderr.getvalue())["error"]
                assert all(text in error for text in ("required_checks[1]." + key, log_action)), error
                assert str(failure) not in error
        assert helper["mode_category"]("0664") == helper["mode_category"]("100644")
        assert helper["mode_category"]("0775") == helper["mode_category"]("100755")
        assert helper["mode_category"]("100644") != helper["mode_category"]("100755")
        import hashlib
        inherited = {
            "axis": "standards", "source": "prior independent standards terminal",
            "status": "completed", "verdict": "pass", "base_commit": base,
            "head_commit": prior, "paths": ["body.txt"],
            "inputs": {"body.txt": {"content_sha256": hashlib.sha256(b"body\n").hexdigest(), "mode": "0664"}},
            "reuse_contract": {
                "source": "fixture owner: body input, prod complete closure, runtime complete assembly; no external inputs",
                "paths": ["body.txt"], "production_closure": ["prod"], "runtime_assembly": ["runtime"],
            },
            "input_snapshot": {
                name: {"mode": "100644", "blob": git("rev-parse", prior + ":" + name)}
                for name in ("body.txt", "prod/dep.txt", "runtime/config.txt")
            },
        }
        data["coverage"] = {
            "standards": {"fresh_paths": ["new.txt"], "inherited": [inherited]},
            "spec": {"fresh_paths": ["body.txt", "new.txt"], "inherited": []},
        }
        data["bundle_path"] = str(Path(folder) / "coverage-bundle")
        assert call("bundle", data)["action"] == "preflight-passed"
        malformed_coverage = {}
        for axis in ("standards", "spec"):
            control = copy.deepcopy(data)
            receipt = {**inherited, "axis": axis}
            empty = {**receipt, "paths": [], "inputs": {}}
            control["coverage"][axis] = {"fresh_paths": ["new.txt"], "inherited": [empty, receipt]}
            control["bundle_path"] = str(Path(folder) / (axis + "-coverage-bundle"))
            assert call("bundle", control)["action"] == "preflight-passed"
            cases = []
            for value in (None, [], "invalid", False, 42, {}, {"fresh_paths": []}, {"inherited": []}):
                bad = copy.deepcopy(control)
                bad["coverage"][axis] = value
                cases.append(("coverage." + axis, value, bad))
            for index in (0, 1):
                for value in (None, [], "invalid", False, 42):
                    bad = copy.deepcopy(control)
                    bad["coverage"][axis]["inherited"][index] = value
                    cases.append((f"coverage.{axis}.inherited[{index}]", value, bad))
            for key in ("source", "head_commit"):
                for kind, value in (invalid_text[0], invalid_text[3]):
                    bad = copy.deepcopy(control)
                    if kind == "missing":
                        del bad["coverage"][axis]["inherited"][1][key]
                    else:
                        bad["coverage"][axis]["inherited"][1][key] = value
                    cases.append((f"coverage.{axis}.inherited[1].{key}", kind, bad))
            if axis == "spec":
                for key, value, field in (
                    ("axis", "standards", "coverage.spec.inherited[1]"),
                    ("head_commit", "0" * 40, "coverage.spec.inherited[1].head_commit"),
                    ("inputs", {}, "coverage.spec.inherited[1].inputs"),
                    ("paths", [{}], "coverage.spec.inherited[1].inputs"),
                ):
                    bad = copy.deepcopy(control)
                    bad["coverage"][axis]["inherited"][1][key] = value
                    cases.append((field, key, bad))
                for key, value, field in (
                    ("content_sha256", None, "coverage.spec.inherited[1].inputs.body.txt"),
                    ("mode", "invalid", "coverage.spec.inherited[1].inputs.body.txt.mode"),
                    ("content_sha256", hashlib.sha256(b"body").hexdigest(), "coverage.spec.inherited[1].inputs.body.txt"),
                    ("mode", "0775", "coverage.spec.inherited[1].inputs.body.txt"),
                ):
                    bad = copy.deepcopy(control)
                    recorded = bad["coverage"][axis]["inherited"][1]["inputs"]["body.txt"]
                    if value is None:
                        del recorded[key]
                    else:
                        recorded[key] = value
                    cases.append((field, key + ":" + str(value), bad))
                bad = copy.deepcopy(control)
                bad["coverage"][axis]["fresh_paths"] = []
                cases.append(("coverage.spec", "missing-path", bad))
                bad = copy.deepcopy(control)
                bad["coverage"][axis]["fresh_paths"] = [{}]
                cases.append(("coverage.spec", "unhashable-path", bad))
                bad = copy.deepcopy(control)
                del bad["coverage"]["standards"]
                cases.append(("coverage", "missing-axis", bad))
            for field, value, bad in cases:
                raw = call("preflight", bad, False)
                try:
                    error = json.loads(raw)
                except json.JSONDecodeError:
                    malformed_coverage[field + ":" + repr(value)] = raw
                    continue
                if set(error) != {"error"} or not all(text in error["error"] for text in (
                    field, "下一步", "补齐", "重新预检",
                )):
                    malformed_coverage[field + ":" + repr(value)] = error
        assert not malformed_coverage, malformed_coverage
        bad_axis = copy.deepcopy(data)
        bad_axis["coverage"]["standards"]["inherited"][0]["axis"] = "spec"
        assert "coverage.standards" in call("preflight", bad_axis, False)
        missing_coverage = copy.deepcopy(data)
        missing_coverage["coverage"]["spec"]["fresh_paths"] = ["new.txt"]
        assert "coverage.spec" in call("preflight", missing_coverage, False)
        bad_body = copy.deepcopy(data)
        bad_body["coverage"]["standards"]["inherited"][0]["inputs"]["body.txt"]["content_sha256"] = hashlib.sha256(b"body").hexdigest()
        assert "inputs.body.txt" in call("preflight", bad_body, False)
        bad_mode = copy.deepcopy(data)
        bad_mode["coverage"]["standards"]["inherited"][0]["inputs"]["body.txt"]["mode"] = "0775"
        assert "inputs.body.txt" in call("preflight", bad_mode, False)
        # 继承沿同一检查/coverage owner；旧结果不能重贴当前 Head。
        reuse_plan = copy.deepcopy(data)
        requirement = reuse_plan["required_checks"][1]
        requirement["reuse_contract"] = copy.deepcopy(inherited["reuse_contract"])
        old_result = {**results[1], "head_commit": prior,
                      "candidate_sha256": hashlib.sha256(helper["CHECKPOINT"]["canonical_bytes"]({
                          "head": prior, "dirty": {}, "index_sha256": hashlib.sha256(b"").hexdigest(),
                          "working_tree_diff_sha256": hashlib.sha256(b"").hexdigest(),
                      })).hexdigest(),
                      "reuse_contract": copy.deepcopy(inherited["reuse_contract"]),
                      "input_snapshot": copy.deepcopy(inherited["input_snapshot"])}
        reuse_plan["check_results"][1] = {**requirement, "inherited_from": old_result}
        mapped = call("preflight", reuse_plan)
        assert mapped["check_decisions"][1]["decision"] == "inherited"
        assert mapped["check_decisions"][1]["source_head"] == prior
        assert mapped["coverage_decisions"]["standards"]["inherited_paths"] == ["body.txt"]
        assert mapped["coverage_decisions"]["spec"]["fresh_paths"] == ["body.txt", "new.txt"]
        assert old_result["head_commit"] == prior  # 原版本不改写。
        # repo 外日志才可在 worktree Cleanup 后继续核验；两种终态共用同一边界。
        sibling = Path(folder) / "repo-logs"
        sibling.mkdir()
        external = sibling / "terminal.log"
        external.write_text("synthetic external terminal\n")
        assert str(external).startswith(str(root))  # 相似文本前缀不等于 repo 内。
        ignored_log = root / "internal.log"
        internal_link = root / "external-link.log"
        external_link = Path(folder) / "internal-link.log"
        exclude = root / ".git/info/exclude"
        original_exclude = exclude.read_bytes()
        exclude.write_bytes(original_exclude + b"\n/internal.log\n/external-link.log\n/directory-link\n")
        ignored_log.write_text("synthetic ignored terminal\n")
        internal_link.symlink_to(external)
        external_link.symlink_to(root / "body.txt")
        file_chain = Path(folder) / "chain.log"
        file_chain.symlink_to(os.path.relpath(internal_link, file_chain.parent))
        internal_dir = root / "directory-link"
        internal_dir.symlink_to(os.path.relpath(sibling, root), target_is_directory=True)
        directory_chain = Path(folder) / "chain-dir"
        directory_chain.symlink_to(internal_dir, target_is_directory=True)
        outside_file = Path(folder) / "outside-link.log"
        outside_file.symlink_to(os.path.relpath(external, outside_file.parent))
        outside_dir = Path(folder) / "outside-dir"
        outside_dir.symlink_to(sibling, target_is_directory=True)
        loop_log = Path(folder) / "loop.log"
        loop_log.symlink_to(loop_log.name)
        # 只删除 fake repo 的中间入口：外部保存路径断链，但真实日志仍在。
        assert file_chain.is_file() and (directory_chain / "terminal.log").is_file()
        internal_link.unlink()
        assert not file_chain.exists() and external.is_file()
        internal_link.symlink_to(external)
        internal_dir.unlink()
        assert not (directory_chain / "terminal.log").exists() and external.is_file()
        internal_dir.symlink_to(os.path.relpath(sibling, root), target_is_directory=True)
        accepted_internal = []
        for branch, control in (("current", data), ("inherited", reuse_plan)):
            for key in ("stdout_log", "stderr_log"):
                for path in (external, outside_file, outside_dir / "terminal.log"):
                    good = copy.deepcopy(control)
                    receipt = good["check_results"][1]
                    receipt = receipt["inherited_from"] if branch == "inherited" else receipt
                    receipt[key] = str(path)
                    assert call("preflight", good)["action"] == "preflight-passed"
                for kind, path in (("tracked", root / "body.txt"), ("ignored", ignored_log),
                                   ("external-link-to-internal", external_link),
                                   ("internal-link-to-external", internal_link),
                                   ("file-chain", file_chain),
                                   ("directory-chain", directory_chain / "terminal.log")):
                    bad = copy.deepcopy(control)
                    receipt = bad["check_results"][1]
                    receipt = receipt["inherited_from"] if branch == "inherited" else receipt
                    receipt[key] = str(path)
                    try:
                        error = call("preflight", bad, False)
                    except AssertionError:
                        accepted_internal.append((branch, key, kind))
                        continue
                    assert all(text in json.loads(error)["error"] for text in (
                        "required_checks[1]." + key, "repo外", "移到", "持久",
                        "更新绝对路径", "重新预检",
                    )), (branch, key, kind, error)
        assert not accepted_internal, ("repo 内日志被错误接受", accepted_internal)
        for branch, control in (("current", data), ("inherited", reuse_plan)):
            for key in ("stdout_log", "stderr_log"):
                bad = copy.deepcopy(control)
                receipt = bad["check_results"][1]
                receipt = receipt["inherited_from"] if branch == "inherited" else receipt
                receipt[key] = str(loop_log)
                error = json.loads(call("preflight", bad, False))["error"]
                assert all(text in error for text in (
                    "required_checks[1]." + key, "循环", "更新绝对路径", "重新预检",
                )), error
        for path in (ignored_log, internal_link, external_link, file_chain, internal_dir,
                     directory_chain, outside_file, outside_dir, loop_log):
            path.unlink()
        exclude.write_bytes(original_exclude)
        for field, value in (("head_commit", "0" * 40), ("status", "running"), ("exit_code", 1),
                             ("status", "skip"), ("status", "Unknown"), ("candidate_sha256", "wrong"),
                             ("reuse_contract", {}), ("input_snapshot", {})):
            bad = copy.deepcopy(reuse_plan)
            bad["check_results"][1]["inherited_from"][field] = value
            assert field in call("preflight", bad, False)
        bad = copy.deepcopy(data)
        del bad["coverage"]["standards"]["inherited"][0]["reuse_contract"]
        assert "reuse_contract" in call("preflight", bad, False)
        # 真实闭包/装配新增、删除、正文与执行位变化，body/test 未变也拒绝。
        for index, (name, mutation) in enumerate((
            ("prod/dep.txt", "body"), ("runtime/config.txt", "body"),
            ("prod/new.txt", "add"), ("prod/dep.txt", "delete"), ("runtime/config.txt", "mode"),
        )):
            path = root / name
            if mutation == "delete":
                path.unlink()
            elif mutation == "mode":
                path.chmod(0o755)
            else:
                path.write_text("changed input\n")
            git("add", "-A")
            git("commit", "-m", "input changed")
            changed_head = git("rev-parse", "HEAD")
            changed = copy.deepcopy(reuse_plan)
            changed["head_commit"] = changed_head
            changed["bundle_path"] = str(Path(folder) / f"changed-input-{index}-bundle")
            changed_candidate = call("checks", changed)["candidate_sha256"]
            changed["check_results"][0].update(head_commit=changed_head, candidate_sha256=changed_candidate)
            error = call("bundle", changed, False)
            assert all(word in error for word in ("input_snapshot", name, "下一步")), error
            # 去掉检查继承仍应被本轴 coverage 的闭包门拒绝。
            changed["check_results"][1] = {**results[1], "head_commit": changed_head,
                                             "candidate_sha256": changed_candidate}
            for axis in changed["coverage"].values():
                axis["fresh_paths"].append(name)
            assert "coverage.standards.inherited[0].input_snapshot" in call("bundle", changed, False)
            git("checkout", "--detach", head)
        (root / "body.txt").write_text("dirty body\n")
        assert "candidate_sha256" in call("preflight", data, False)
        implementation = {
            **plan, "base_commit": base, "target_commit": base, "review_scope": "implementation",
            "bundle_path": str(Path(folder) / "dirty-bundle"),
            "required_checks": [], "check_results": [], "allowed_dirty_paths": ["body.txt", "untracked.txt"],
        }
        git("add", "body.txt")
        (root / "new.txt").write_text("unstaged\n")
        (root / "untracked.txt").write_text("untracked\n")
        assert "allowed_dirty_paths" in call("bundle", implementation, False)
        implementation["allowed_dirty_paths"].append("new.txt")
        assert call("bundle", implementation)["action"] == "preflight-passed"
        dirty_bundle = Path(implementation["bundle_path"])
        assert "A\tuntracked.txt" in (dirty_bundle / "changed-paths.txt").read_text()
        assert "NO_STAGED_FILES=false" in (dirty_bundle / "worktree-state.txt").read_text()
        assert "+untracked" in (dirty_bundle / "diff.patch").read_text()
        assert "immutable" in call("bundle", implementation, False)
    print("review preflight: pass (pending TZ, candidate, seven files, prior-only, same-axis coverage, LF, exec bit, dirty boundary)")


def check():
    check_review_preflight()
    with tempfile.TemporaryDirectory() as fixture_folder:
        fixture_root = Path(fixture_folder) / "repo"
        fixture_root.mkdir()
        def fixture_git(*args):
            return subprocess.check_output(["git", "-C", str(fixture_root), *args], env=git_env(), stderr=subprocess.PIPE).decode().strip()
        fixture_git("init", "-b", "probe")
        fixture_git("config", "user.name", "Probe")
        fixture_git("config", "user.email", "probe@example.invalid")
        fixture_git("commit", "--allow-empty", "-m", "base")
        fixture_base = fixture_git("rev-parse", "HEAD")
        (fixture_root / "file.txt").write_text("candidate\n")
        fixture_git("add", ".")
        fixture_git("commit", "-m", "candidate")
        fixture_plan = {"worktree": str(fixture_root), "head_commit": fixture_git("rev-parse", "HEAD"),
                        "checks_source": "fixture repo/module/CI readback: no business checks", "required_checks": []}
        fixture_preflights = {}
        for scope in ("implementation", "whole-change"):
            evidence = {**fixture_plan, "base_commit": fixture_base, "target_commit": fixture_base, "review_scope": scope,
                        "bundle_path": str(Path(fixture_folder) / scope), "allowed_dirty_paths": [], "check_results": []}
            call("bundle", evidence)
            fixture_preflights[scope] = evidence
        check_configured(fixture_plan, fixture_preflights)


def check_configured(fixture_plan, fixture_preflights):
    configured = call("models", {})
    assert configured["config"]["default_mode"] == "sol-sol"
    assert call("model", {"work": "planning"})["target"]["model"] == configured["config"]["work"]["planning"]["model"]
    review = {
        "worktree": "unused",
        "base_commit": "unused",
        "head_commit": "unused",
        "review_scope": "implementation",
        "owner": {
            "name": "code-review",
            "skill_path": "/resolved/code-review/SKILL.md",
            "invocation_label": "$code-review",
        },
        "reviews": {},
    }
    assert "缺少独立两轴结论" in call("review", review, False)
    coordinator = call(
        "coordinator",
        {"model": "gpt-6-sol", "effort": "high", "source": "turn_context"},
    )
    assert coordinator["action"] == "verified"
    for model, effort, source in (
        ("gpt-6-sol", "low", "turn_context"),
        ("gpt-6-astra", "high", "turn_context"),
        ("gpt-6-sol", "high", ""),
    ):
        observed = call(
            "coordinator", {"model": model, "effort": effort, "source": source}
        )
        assert observed["action"] == ("verified" if source else "Unknown")
        assert observed["model"] == (model if source else "Unknown")
    sizing = call(
        "subagent",
        {
            "work": "ticket-sizing",
            "active_count": 0,
            "source": "live list",
            "read_only": False,
        },
    )
    assert sizing["request"] == {
        "model": configured["config"]["work"]["ticket-sizing"]["model"],
        "reasoning_effort": "high",
        "fork_turns": "none",
    }
    assert sizing["read_only"] is True
    assert (
        call(
            "subagent",
            {
                "work": "ticket-sizing",
                "active_count": 3,
                "source": "live list",
                "read_only": False,
            },
        )["action"]
        == "wait"
    )
    support = call(
        "subagent",
        {
            "work": "assistance",
            "active_count": 0,
            "source": "live list",
            "read_only": True,
        },
    )
    assert support["request"] == {
        "model": configured["config"]["work"]["assistance"]["model"],
        "reasoning_effort": "max",
        "fork_turns": "none",
    }
    assert support["read_only"] is True
    opinion = call(
        "subagent",
        {
            "work": "second-opinion",
            "active_count": 0,
            "source": "live list",
            "read_only": False,
        },
    )
    assert opinion["request"]["model"] == configured["config"]["work"]["second-opinion"]["model"] and opinion["read_only"] is True
    for work in ("testing", "integration"):
        delegated = call(
            "subagent",
            {
                "work": work,
                "active_count": 0,
                "source": "live list",
                "read_only": False,
            },
        )
        assert delegated["request"] == {
            "model": configured["config"]["work"][work]["model"],
            "reasoning_effort": "max",
            "fork_turns": "none",
        }
        assert delegated["read_only"] is (work == "testing")
        call(
            "subagent",
            {
                "work": work,
                "active_count": 1,
                "source": "live list",
                "read_only": False,
            },
            False,
        )
    call(
        "subagent",
        {
            "work": "integration",
            "active_count": 0,
            "source": "live list",
            "read_only": True,
        },
        False,
    )
    assert (
        call(
            "subagent",
            {
                "work": "assistance",
                "active_count": 3,
                "source": "live list",
                "read_only": False,
            },
        )["request"]
        is None
    )
    assert (
        call(
            "subagent",
            {
                "work": "review",
                "review_scope": "implementation",
                "active_count": 2,
                "source": "live list",
                "read_only": True,
            },
        )["action"]
        == "wait"
    )
    assert (
        call(
            "subagent",
            {
                "work": "review",
                "review_scope": "implementation",
                "preflight": fixture_preflights["implementation"],
                "active_count": 0,
                "source": "live list",
                "read_only": True,
            },
        )["action"]
        == "invoke-owner"
    )
    call(
        "subagent",
        {
            "work": "assistance",
            "active_count": -1,
            "source": "live list",
            "read_only": True,
        },
        False,
    )
    call(
        "subagent",
        {"work": "assistance", "active_count": 0, "source": "", "read_only": True},
        False,
    )
    # #638/#642：原型的实施建议没有 Spec/拆票证据，不能创建实施 lane。
    for mode in ("sol-luna", "sol-sol", "sol-direct"):
        call(
            "resolve",
            {"task": "frontend", "output_mode": "commit", "ticket_mode": mode},
            False,
        )
    gate = {
        "work_item": "ticket-643",
        "map": "map-638",
        "gate_evidence": {
            "readback": "fixture tracker snapshot 2026-09-07",
            "discovery": "decision resolution and user confirmation",
            "spec": {
                "url": "spec-650",
                "source_map": "map-638",
                "body": "spec body",
                "owner_run": "to-spec artifact",
                "confirmation": "user confirmed testing seams",
            },
            "ticket": {
                "url": "ticket-643",
                "parent": "spec-650",
                "body": "ticket body",
                "owner_run": "to-tickets artifact",
                "sizing": "ticket-sizing per-ticket assessment artifact",
                "confirmation": "user approved breakdown",
                "dependencies": [],
            },
        },
    }
    base = {"task": "backend", "output_mode": "commit", **gate, **fixture_plan}
    missing_checks = dict(base)
    del missing_checks["required_checks"]
    assert "required_checks" in call("resolve", missing_checks, False)
    wrong_candidate = {**base, "head_commit": "old-head"}
    assert "head_commit" in call("resolve", wrong_candidate, False)
    # 修改配置本身必须改变每条分派路径；无需修改 Python 或 SKILL。
    with tempfile.TemporaryDirectory() as config_folder:
        config_path = Path(config_folder) / "models.json"
        config = copy.deepcopy(configured["config"])
        custom = {"agent": "codex-app", "model": "host-test-model", "effort": "medium"}
        config["work"] = dict.fromkeys(config["work"], custom)
        config["modes"]["custom"] = {
            "kind": "staged",
            "agents": {
                "codex-app": {
                    phase: {k: custom[k] for k in ("model", "effort")}
                    for phase in ("starting", "execution", "direct")
                }
            },
        }
        config["default_mode"] = "custom"
        config["review"] = {
            scope: dict.fromkeys(axes, custom)
            for scope, axes in config["review"].items()
        }
        config_path.write_text(json.dumps(config))
        source = {"config_path": str(config_path)}
        for work in config["work"]:
            assert call("model", {**source, "work": work})["request"] == {
                "model": custom["model"],
                "thinking": custom["effort"],
            }
        for work in (
            "assistance",
            "testing",
            "integration",
            "second-opinion",
            "ticket-sizing",
        ):
            actual = call(
                "subagent",
                {
                    **source,
                    "work": work,
                    "active_count": 0,
                    "source": "live list",
                    "read_only": False,
                },
            )
            assert actual["request"]["model"] == custom["model"]
            assert actual["request"]["reasoning_effort"] == custom["effort"]
        assert call("coordinator", source)["recommendation"]["model"] == custom["model"]
        for scope in config["review"]:
            actual = call(
                "subagent",
                {
                    **source,
                    "work": "review",
                    "review_scope": scope,
                    "preflight": fixture_preflights[scope],
                    "active_count": 0,
                    "source": "live list",
                    "read_only": True,
                },
            )
            assert all(
                target["model"] == custom["model"]
                for target in actual["review_models"].values()
            )
        resolved = call("resolve", {**base, **source})
        assert resolved["overlay"]["development_mode"] == "custom"
        assert resolved["request"] == {
            "model": custom["model"],
            "thinking": custom["effort"],
        }
        override = call(
            "resolve",
            {
                **base,
                **source,
                "model_overrides": {
                    "starting": {
                        "effort": "high",
                        "scope": "starting",
                        "source": "user",
                    },
                    "execution": {
                        "model": "user-execution",
                        "scope": "execution",
                        "source": "user",
                    },
                },
            },
        )
        assert override["request"]["thinking"] == "high"
        assert override["overlay"]["execution_target"]["model"] == "user-execution"
        assert override["overlay"]["execution_target"]["effort"] == custom["effort"]
        config["modes"]["custom"]["kind"] = "direct"
        config["modes"]["custom"]["agents"]["codex-app"]["direct"] = {
            "model": "direct-test",
            "effort": "low",
        }
        config_path.write_text(json.dumps(config))
        assert call("resolve", {**base, **source})["request"]["model"] == "direct-test"
        assert (
            call(
                "model",
                {
                    **source,
                    "work": "research",
                    "model_override": {
                        "model": "user-model",
                        "scope": "research",
                        "source": "user",
                    },
                },
            )["target"]["model"]
            == "user-model"
        )
        for invalid in (
            {},
            {**config, "work": []},
            {**config, "version": True},
            {**config, "default_mode": "missing"},
            {**config, "review": {}},
            {
                **config,
                "work": {
                    **config["work"],
                    "planning": {
                        "agent": "codex-app",
                        "model": "Unknown",
                        "effort": "low",
                    },
                },
            },
        ):
            config_path.write_text(json.dumps(invalid))
            assert "error" in json.loads(call("models", source, False))
            call("resolve", {**base, **source}, False)
        config_path.unlink()
        call("models", source, False)
        assert (
            call("resolve", {**source, "existing_lane": resolved["overlay"]})["action"]
            == "recover"
        )
        call("models", {"config_path": "relative.json"}, False)
    core_helper = (
        HELPER.resolve().parents[2] / "delivery-pipeline/scripts/implementation_gate.py"
    )
    for payload, expected in ((gate, 0), ({"work_item": "ticket-643"}, 1)):
        result = subprocess.run(
            [sys.executable, str(core_helper)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
        )
        assert result.returncode == expected, result.stderr or result.stdout
    for stage in ("spec", "ticket"):
        for field in ("url", "body", "owner_run", "confirmation"):
            bad = copy.deepcopy(base)
            bad["gate_evidence"][stage][field] = "Unknown"
            call("resolve", bad, False)
    for stage, field, value in (
        ("ticket", "parent", "map-638"),
        ("ticket", "url", "other-ticket"),
        ("ticket", "dependencies", None),
        ("spec", "source_map", "other-map"),
    ):
        bad = copy.deepcopy(base)
        bad["gate_evidence"][stage][field] = value
        call("resolve", bad, False)
    for field in ("readback", "discovery"):
        bad = copy.deepcopy(base)
        del bad["gate_evidence"][field]
        call("resolve", bad, False)
    standalone = copy.deepcopy(base)
    del standalone["map"]
    assert call("resolve", standalone)["action"] == "create"
    assert call("resolve", {"existing_lane": {"model": "old"}})["action"] == "recover"
    missing_sizing = copy.deepcopy(base)
    del missing_sizing["gate_evidence"]["ticket"]["sizing"]
    call("resolve", missing_sizing, False)
    default = call("resolve", base)
    assert default["overlay"]["development_mode"] == "sol-sol"
    assert default["request"] == {"model": configured["config"]["modes"]["sol-sol"]["agents"]["codex-app"]["starting"]["model"], "thinking": "xhigh"}
    assert default["overlay"]["execution_target"]["model"] == configured["config"]["modes"]["sol-sol"]["agents"]["codex-app"]["execution"]["model"]
    assert default["overlay"]["execution_target"]["effort"] == "high"
    default = call("resolve", {**base, "ticket_mode": "sol-luna"})
    assert (
        call("resolve", {**base, "map_mode": "sol-sol"})["overlay"]["mode_source"]
        == "map"
    )
    for legacy_mode in ("astra-luna",):
        call("resolve", {**base, "ticket_mode": legacy_mode}, False)
    direct = call(
        "resolve", {**base, "ticket_mode": "sol-direct", "map_mode": "sol-luna"}
    )
    assert direct["request"] == {"model": configured["config"]["modes"]["sol-direct"]["agents"]["codex-app"]["direct"]["model"], "thinking": "high"}
    assert direct["overlay"]["execution_phase"] == "executing"
    assert (
        call("resolve", {**base, "existing_lane": {"model": "old"}})["request"] is None
    )
    assert (
        call("resolve", {"task": "review", "output_mode": "verdict"})["action"]
        == "not-applicable"
    )
    call("resolve", {**base, "ticket_mode": "invalid"}, False)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "repo"
        root.mkdir()

        def git(*args):
            subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                env=git_env(),
            )

        git("init", "-b", "probe")
        git(
            "-c",
            "user.name=Probe",
            "-c",
            "user.email=probe@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "base",
        )
        git("checkout", "--detach")
        (root / "worker.py").write_text("first edit\n")
        snap = call("snapshot", {"worktree": str(root)})
        assert (
            call(
                "snapshot",
                {"worktree": str(root)},
                extra_env={
                    "GIT_DIR": str(root / ".git"),
                    "GIT_WORK_TREE": str(root / "elsewhere"),
                    "GIT_INDEX_FILE": str(root / "bogus-index"),
                    "GIT_COMMON_DIR": str(root / "bogus-common"),
                },
            )
            == snap
        )
        lane = {
            **default["overlay"],
            "lane_id": "probe",
            "thread_id": "same-task",
            "host_id": "local",
            "coordinator_thread_id": "coordinator-task",
            "coordinator_host_id": "local",
            "worktree": str(root),
            "state": "running",
            "base_commit": snap["head"],
        }
        legacy_dirty = {}
        for name, item in snap["dirty"].items():
            if item["deleted"]:
                legacy_dirty[name] = {"deleted": True}
            else:
                kind = stat.S_IFLNK if item["kind"] == "symlink" else stat.S_IFREG
                legacy_dirty[name] = {
                    "mode": kind | item["mode"],
                    "sha256": item["content_sha256"],
                }
        legacy_snapshot = {
            key: snap[key]
            for key in ("worktree", "head", "branch", "common_dir", "index_sha256")
        }
        legacy_snapshot["dirty"] = legacy_dirty
        legacy_snapshot["ignored"] = {"delivery_input": "none"}
        legacy_path = Path(folder) / "legacy-checkpoint.json"
        legacy_checkpoint = {
            "lane_id": lane["lane_id"],
            "thread_id": lane["thread_id"],
            "host_id": lane["host_id"],
            "base_commit": lane["base_commit"],
            "first_edit": ["worker.py"],
            "snapshot": legacy_snapshot,
            "todo": ["finish"],
            "checks": ["start passed"],
            "evidence": ["spec"],
            "decision": {"critical_design_unknown": False, "reason": "minimal"},
        }
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        legacy_lane = {
            **lane,
            "development_mode": "astra-luna",
            "checkpoint_format": "legacy-app-v0",
            "checkpoint": str(legacy_path),
        }
        for key in (
            "phase_plan",
            "phase_targets",
            "execution_target",
            "execution_kind",
            "config_path",
        ):
            legacy_lane.pop(key, None)
        legacy_data = {
            **gate,
            "lane": legacy_lane,
            "checkpoint": legacy_checkpoint,
            "checkpoint_path": str(legacy_path),
            "legacy_checkpoint": True,
            "observation": {
                "thread_id": "same-task",
                "host_id": "local",
                "status": "idle",
                "source": "probe",
            },
        }
        legacy = call("prepare", legacy_data)
        assert legacy["overlay"]["checkpoint_format"] == "legacy-app-v0"
        assert legacy["overlay"]["checkpoint_sha256"] == "Unknown"
        critical_legacy = copy.deepcopy(legacy_data)
        critical_legacy["checkpoint"]["decision"] = {
            "critical_design_unknown": True,
            "reason": "unresolved architecture",
        }
        legacy_path.write_text(json.dumps(critical_legacy["checkpoint"]))
        critical_error = json.loads(call("prepare", critical_legacy, False))
        assert (
            "关键设计 Unknown" in critical_error["error"]
            and "request" not in critical_error
        )
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        for bad_decision in (
            None,
            "Unknown",
            {},
            {"critical_design_unknown": "Unknown", "reason": "minimal"},
            {"critical_design_unknown": False, "reason": "Unknown"},
            {"critical_design_unknown": False, "reason": " unknown "},
            {"critical_design_unknown": False, "reason": "UNKNOWN"},
        ):
            bad_legacy = copy.deepcopy(legacy_data)
            bad_legacy["checkpoint"]["decision"] = bad_decision
            legacy_path.write_text(json.dumps(bad_legacy["checkpoint"]))
            decision_error = json.loads(call("prepare", bad_legacy, False))
            assert (
                "legacy decision" in decision_error["error"]
                and "request" not in decision_error
            )
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        call("prepare", {**legacy_data, "lane": lane}, False)
        mismatch_lane = {**legacy_lane, "checkpoint": str(Path(folder) / "other.json")}
        assert "path 不匹配" in call(
            "prepare", {**legacy_data, "lane": mismatch_lane}, False
        )
        ignored_legacy = copy.deepcopy(legacy_data)
        ignored_legacy["checkpoint"]["snapshot"]["ignored"] = {
            "delivery_input": "Unknown"
        }
        legacy_path.write_text(json.dumps(ignored_legacy["checkpoint"]))
        assert "legacy ignored" in call("prepare", ignored_legacy, False)
        legacy_path.write_text(json.dumps(legacy_checkpoint))
        without_legacy = copy.deepcopy(legacy_data)
        del without_legacy["legacy_checkpoint"]
        call("prepare", without_legacy, False)
        path = Path(folder) / "checkpoint.json"
        payload = {
            "lane_id": lane["lane_id"],
            "work_item": gate["work_item"],
            "runtime": "codex-thread",
            "session_id": lane["thread_id"],
            "coordinator_thread_id": lane["coordinator_thread_id"],
            "coordinator_host_id": lane["coordinator_host_id"],
            "cli_version": "Unknown",
            "execution_worktree": snap["worktree"],
            "execution_branch": snap["branch"],
            "base_commit": snap["head"],
            "head_commit": snap["head"],
            "phase": "starting",
            "development_mode": "staged",
            "mode_source": "user-config",
            "execution_target": lane["execution_target"],
            "phase_plan": lane["phase_plan"],
            "requested_model": lane["requested_model"],
            "requested_effort": "high",
            "tool_acceptance": {
                "accepted": True,
                "status": "accepted",
                "source": "host readback",
            },
            "actual_model": lane["requested_model"],
            "actual_effort": "high",
            "actual_readback_source": "host turn context",
            "actual_readback_at": "2026-09-08T00:00:00Z",
            "first_edit": ["worker.py"],
            "checks": [{"command": "compile worker.py", "result": "exit 0"}],
            "todo": ["finish"],
            "decision": {"critical_design_unknown": False, "reason": "minimal"},
            "evidence": ["spec"],
            "checkpoint_path": str(path),
        }
        checkpoint = call(
            "checkpoint",
            {"worktree": str(root), "checkpoint_path": str(path), "payload": payload},
        )
        assert checkpoint["checkpoint_sha256"]
        assert path.read_text() == json.dumps(
            checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        data = {
            **gate,
            "lane": lane,
            "checkpoint": checkpoint,
            "checkpoint_path": str(path),
            "observation": {
                "thread_id": "same-task",
                "host_id": "local",
                "status": "idle",
                "source": "probe",
            },
        }
        bad = copy.deepcopy(data)
        del bad["checkpoint"]["first_edit"]
        path.write_text(
            json.dumps(
                bad["checkpoint"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        call("prepare", bad, False)
        for field, value in (
            ("first_edit", ["unrelated.py"]),
            ("base_commit", "wrong-base"),
        ):
            bad = copy.deepcopy(data)
            bad["checkpoint"][field] = value
            path.write_text(
                json.dumps(
                    bad["checkpoint"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            call("prepare", bad, False)
        path.write_text(
            json.dumps(
                checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        )
        missing_gate = copy.deepcopy(data)
        del missing_gate["gate_evidence"]
        call("prepare", missing_gate, False)
        prepared = call("prepare", data)
        assert prepared["action"] == "persist-before-send"
        assert prepared["request"]["threadId"] == "same-task"
        assert prepared["request"]["model"] == lane["execution_target"]["model"]
        assert prepared["request"]["thinking"] == "max"
        assert prepared["overlay"]["requested_effort"] == "max"
        assert prepared["overlay"]["model"] == "Unknown"
        assert prepared["overlay"]["execution_target"] == {
            "model": lane["execution_target"]["model"],
            "effort": "max",
            "source": lane["execution_target"]["source"],
            "scope": "execution",
        }
        assert (
            prepared["overlay"]["checkpoint_sha256"] == checkpoint["checkpoint_sha256"]
        )
        assert "起步轮限制已结束" in prepared["request"]["prompt"]
        assert "不得取消或中断正式 reviewer" in prepared["request"]["prompt"]
        assert "resolved owner 和 review_scope" in prepared["request"]["prompt"]
        assert "不得报告 completed" in prepared["request"]["prompt"]
        # 默认 astra-sol 的 checkpoint -> prepare；配置消失也不能改动已冻结目标。
        astra_lane = {**lane, **call("resolve", {**base, "ticket_mode": "astra-sol"})["overlay"]}
        astra_path = Path(folder) / "astra-checkpoint.json"
        astra_payload = {
            **payload,
            "phase_plan": astra_lane["phase_plan"],
            "execution_target": astra_lane["execution_target"],
            "checkpoint_path": str(astra_path),
            "requested_model": astra_lane["requested_model"],
            "requested_effort": "high",
            "actual_model": astra_lane["requested_model"],
            "actual_effort": "high",
        }
        astra_checkpoint = call(
            "checkpoint",
            {
                "worktree": str(root),
                "checkpoint_path": str(astra_path),
                "payload": astra_payload,
            },
        )
        astra_prepared = call(
            "prepare",
            {
                **data,
                "lane": astra_lane,
                "checkpoint": astra_checkpoint,
                "checkpoint_path": str(astra_path),
                "config_path": str(Path(folder) / "missing.json"),
            },
        )
        assert astra_prepared["request"]["model"] == astra_lane["execution_target"]["model"]
        assert astra_prepared["request"]["thinking"] == "high"
        assert astra_prepared["request"]["threadId"] == lane["thread_id"]
        corrupt = {
            **astra_lane,
            "phase_plan": {
                **astra_lane["phase_plan"],
                "execution": {"model": "changed", "effort": "high"},
            },
        }
        call(
            "prepare",
            {
                **data,
                "lane": corrupt,
                "checkpoint": astra_checkpoint,
                "checkpoint_path": str(astra_path),
            },
            False,
        )
        effort_path = Path(folder) / "effort-override-checkpoint.json"
        effort_payload = copy.deepcopy(payload)
        effort_payload["checkpoint_path"] = str(effort_path)
        effort_payload["phase_plan"]["execution"]["effort"] = "high"
        effort_payload["execution_target"] = {
            "model": lane["execution_target"]["model"],
            "effort": "high",
            "source": "user task override",
            "scope": "execution",
        }
        effort_checkpoint = call(
            "checkpoint",
            {
                "worktree": str(root),
                "checkpoint_path": str(effort_path),
                "payload": effort_payload,
            },
        )
        effort_override = call(
            "prepare",
            {
                **data,
                "checkpoint": effort_checkpoint,
                "checkpoint_path": str(effort_path),
                "execution_override": {
                    "effort": "high",
                    "source": "user task override",
                    "scope": "execution",
                },
            },
        )
        assert effort_override["request"]["model"] == lane["execution_target"]["model"]
        assert effort_override["request"]["thinking"] == "high"
        assert effort_override["overlay"]["execution_target"] == {
            "model": lane["execution_target"]["model"],
            "effort": "high",
            "source": "user task override",
            "scope": "execution",
        }
        changed_source = {
            **data,
            "checkpoint": effort_checkpoint,
            "checkpoint_path": str(effort_path),
            "execution_override": {
                "effort": "high",
                "source": "another source",
                "scope": "execution",
            },
        }
        assert "完整 resolved execution target" in call(
            "prepare", changed_source, False
        )
        changed_scope = {
            **data,
            "checkpoint": effort_checkpoint,
            "checkpoint_path": str(effort_path),
            "execution_override": {
                "effort": "high",
                "source": "user task override",
                "scope": "direct",
            },
        }
        call("prepare", changed_scope, False)
        missing_target = copy.deepcopy(effort_checkpoint)
        missing_target["evidence"] = [
            item
            for item in missing_target["evidence"]
            if not item.startswith(EXECUTION_TARGET_MARKER)
        ]
        missing_target[CHECKPOINT["FINGERPRINT_FIELD"]] = CHECKPOINT[
            "checkpoint_sha256"
        ](missing_target)
        effort_path.write_bytes(CHECKPOINT["canonical_bytes"](missing_target))
        assert "execution_target" in call(
            "prepare",
            {
                **data,
                "checkpoint": missing_target,
                "checkpoint_path": str(effort_path),
                "execution_override": {
                    "effort": "high",
                    "source": "user task override",
                    "scope": "execution",
                },
            },
            False,
        )
        effort_path.write_bytes(CHECKPOINT["canonical_bytes"](effort_checkpoint))
        model_path = Path(folder) / "model-override-checkpoint.json"
        model_payload = copy.deepcopy(payload)
        model_payload["checkpoint_path"] = str(model_path)
        model_payload["phase_plan"]["execution"]["model"] = "gpt-6-sol"
        model_payload["execution_target"] = {
            "model": "gpt-6-sol",
            "effort": "max",
            "source": "user task override",
            "scope": "execution",
        }
        model_checkpoint = call(
            "checkpoint",
            {
                "worktree": str(root),
                "checkpoint_path": str(model_path),
                "payload": model_payload,
            },
        )
        model_override = call(
            "prepare",
            {
                **data,
                "checkpoint": model_checkpoint,
                "checkpoint_path": str(model_path),
                "execution_override": {
                    "model": "gpt-6-sol",
                    "source": "user task override",
                    "scope": "execution",
                },
            },
        )
        assert model_override["request"]["model"] == "gpt-6-sol"
        assert model_override["request"]["thinking"] == "max"
        assert "resolved execution target" in call(
            "prepare",
            {
                **data,
                "checkpoint": model_checkpoint,
                "checkpoint_path": str(model_path),
            },
            False,
        )
        for invalid_override in (
            {"effort": "high", "source": "user task override", "scope": "starting"},
            {"model": "gpt-6-sol", "source": "Unknown", "scope": "execution"},
            {
                "model": "gpt-6-sol",
                "source": "user task override",
                "scope": "execution",
                "unexpected": "value",
            },
        ):
            invalid = {
                **data,
                "checkpoint": model_checkpoint,
                "checkpoint_path": str(model_path),
                "execution_override": invalid_override,
            }
            call("prepare", invalid, False)
        old_lane = {
            k: v
            for k, v in lane.items()
            if k
            not in (
                "phase_plan",
                "phase_targets",
                "execution_target",
                "execution_kind",
                "config_path",
            )
        }
        assert "持久恢复证据" in call(
            "prepare",
            {**data, "lane": {**old_lane, "development_mode": "astra-luna"}},
            False,
        )
        assert call("prepare", {**data, "lane": prepared["overlay"]})["request"] is None
        assert (
            call("prepare", {**data, "lane": {**lane, "execution_phase": "executing"}})[
                "request"
            ]
            is None
        )
        sol_path = Path(folder) / "sol-checkpoint.json"
        sol_payload = copy.deepcopy(payload)
        sol_payload["checkpoint_path"] = str(sol_path)
        sol_plan = call(
            "resolve", {**base, "ticket_mode": "sol-sol"}
        )["overlay"]
        sol_payload["phase_plan"] = sol_plan["phase_plan"]
        sol_payload["execution_target"] = sol_plan["execution_target"]
        sol_payload["requested_model"] = sol_plan["requested_model"]
        sol_payload["actual_model"] = sol_plan["requested_model"]
        sol_payload["requested_effort"] = "xhigh"
        sol_payload["actual_effort"] = "xhigh"
        sol_checkpoint = call(
            "checkpoint",
            {
                "worktree": str(root),
                "checkpoint_path": str(sol_path),
                "payload": sol_payload,
            },
        )
        sol = call(
            "prepare",
            {
                **data,
                "lane": {
                    **lane,
                    **sol_plan,
                },
                "checkpoint": sol_checkpoint,
                "checkpoint_path": str(sol_path),
            },
        )
        assert sol["request"]["model"] == sol_plan["execution_target"]["model"]
        assert sol["request"]["thinking"] == "high"
        pending = call(
            "prepare",
            {**data, "observation": {**data["observation"], "status": "active"}},
        )
        assert pending["action"] == "wait-for-stop" and pending["request"] is None
        assert pending["target"] == {"threadId": "same-task", "hostId": "local"}
        for field, value in (
            ("status", "Unknown"),
            ("thread_id", "other"),
            ("source", ""),
        ):
            bad = copy.deepcopy(data)
            bad["observation"][field] = value
            call("prepare", bad, False)
        call("prepare", {**data, "lane": {**lane, "state": "integrated"}}, False)
        (root / "worker.py").write_text("changed after checkpoint\n")
        assert "已过期" in call("prepare", data, False)
        (root / "worker.py").write_text("first edit\n")
        git("add", "worker.py")
        assert "已过期" in call("prepare", data, False)
        git("reset")
        (root / "extra.txt").write_text("untracked")
        assert "已过期" in call("prepare", data, False)
        (root / "extra.txt").unlink()
        (root / ".gitignore").write_text("ignored.txt\n")
        (root / "ignored.txt").write_text("delivery input\n")
        ignored_path = Path(folder) / "ignored-checkpoint.json"
        ignored_payload = copy.deepcopy(payload)
        ignored_payload["checkpoint_path"] = str(ignored_path)
        call(
            "checkpoint",
            {
                "worktree": str(root),
                "checkpoint_path": str(ignored_path),
                "payload": ignored_payload,
                "required_ignored": ["ignored.txt"],
            },
            False,
        )
        ignored_checkpoint = call(
            "checkpoint",
            {
                "worktree": str(root),
                "checkpoint_path": str(ignored_path),
                "payload": ignored_payload,
            },
        )
        ignored_data = {
            **data,
            "checkpoint": ignored_checkpoint,
            "checkpoint_path": str(ignored_path),
        }
        assert "ignored 交付输入" in call("prepare", ignored_data, False)
        (root / "ignored.txt").unlink()
        (root / ".gitignore").unlink()
        critical_path = Path(folder) / "critical-checkpoint.json"
        critical_payload = copy.deepcopy(payload)
        critical_payload["checkpoint_path"] = str(critical_path)
        critical_payload["decision"] = {
            "critical_design_unknown": True,
            "reason": "still unknown",
        }
        critical_checkpoint = call(
            "checkpoint",
            {
                "worktree": str(root),
                "checkpoint_path": str(critical_path),
                "payload": critical_payload,
            },
        )
        critical_data = {
            **data,
            "checkpoint": critical_checkpoint,
            "checkpoint_path": str(critical_path),
        }
        assert "关键设计 Unknown" in call("prepare", critical_data, False)
        git("add", "worker.py")
        git(
            "-c",
            "user.name=Probe",
            "-c",
            "user.email=probe@example.invalid",
            "commit",
            "-m",
            "candidate",
        )
        head = call("snapshot", {"worktree": str(root)})["head"]
        owner = {
            "name": "code-review",
            "skill_path": "/resolved/code-review/SKILL.md",
            "invocation_label": "$code-review",
        }
        receipt = {
            "worktree": str(root),
            "worker_id": "worker",
            "base_commit": snap["head"],
            "head_commit": head,
            "review_scope": "implementation",
            "owner": owner,
            "reviews": {},
        }
        for name in ("standards", "spec"):
            receipt["reviews"][name] = {
                "reviewer_id": name,
                "source": "host turn result",
                "status": "completed",
                "verdict": "pass",
                "verdict_text": "无阻断项",
                "blocking_findings": 0,
                "review_scope": "implementation",
                "base_commit": snap["head"],
                "head_commit": head,
            }
        receipt["preflight"] = {
            "worktree": str(root), "base_commit": snap["head"], "head_commit": head,
            "review_scope": "implementation", "target_commit": receipt["base_commit"], "allowed_dirty_paths": [],
            "checks_source": "fixture repo/module/CI: no business commands",
            "required_checks": [], "check_results": [],
            "bundle_path": str(Path(folder) / "receipt-bundle"),
        }
        call("bundle", receipt["preflight"])
        reviewed = call("review", receipt)
        assert (
            reviewed["review_scope"] == "implementation" and reviewed["owner"] == owner
        )
        whole_receipt = copy.deepcopy(receipt)
        whole_receipt["review_scope"] = "whole-change"
        whole_receipt["preflight"]["review_scope"] = "whole-change"
        whole_receipt["preflight"]["bundle_path"] = str(Path(folder) / "whole-receipt-bundle")
        call("bundle", whole_receipt["preflight"])
        for axis in whole_receipt["reviews"].values():
            axis["review_scope"] = "whole-change"
        whole_change = call("review", whole_receipt)
        assert whole_change["review_scope"] == "whole-change"
        for field, value in (
            ("status", "interrupted"),
            ("status", "running"),
            ("verdict", "self-approved"),
            ("blocking_findings", 1),
            ("blocking_findings", False),
            ("head_commit", snap["head"]),
            ("review_scope", "whole-change"),
            ("reviewer_id", "worker"),
            ("reviewer_id", "standards"),
            ("source", ""),
            ("verdict_text", "Unknown"),
        ):
            bad = copy.deepcopy(receipt)
            bad["reviews"]["spec"][field] = value
            call("review", bad, False)
        for field in ("owner", "review_scope"):
            bad = copy.deepcopy(receipt)
            del bad[field]
            call("review", bad, False)
        (root / "worker.py").write_text("changed after review")
        call("review", receipt, False)
    print(
        "prewalk dispatch: pass (coordinator, spec/tickets gate, configured modes, canonical checkpoint, legacy recovery, ignored, review independence)"
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--review-preflight"]:
        check_review_preflight()
    else:
        check()

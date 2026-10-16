#!/usr/bin/env python3
"""规定检查与七文件的确定性预检；不执行检查、不派审查、不改原证据。"""

import hashlib
import json
import os
import runpy
import shlex
import stat
import sys
from pathlib import Path

CHECKPOINT = runpy.run_path(str(Path(__file__).with_name("checkpoint.py")))
require_text = runpy.run_path(str(Path(__file__).with_name("implementation_gate.py")))["require_text"]
FILES = ("fixed-point.txt", "diff.patch", "commits.txt", "changed-paths.txt",
         "fixed-point-added-paths.txt", "worktree-state.txt", "commands.txt")


def current(data):
    try:
        require_text(data.get("worktree"), "worktree")
    except ValueError as error:
        raise ValueError(str(error) + "；下一步：补齐该字段为 Git 顶层绝对路径后重新预检") from error
    state = CHECKPOINT["snapshot_worktree"](data["worktree"])
    if data.get("head_commit") != state["head"]:
        raise ValueError("head_commit 不匹配；下一步：回读当前 candidate")
    material = {key: state[key] for key in ("head", "dirty", "index_sha256", "working_tree_diff_sha256")}
    candidate = hashlib.sha256(CHECKPOINT["canonical_bytes"](material)).hexdigest()
    return state, candidate


def input_snapshot(root, head, contract, allow_missing=False):
    """展开合同声明的完整 Git 子树；闭包完整性由原 repo/module owner 提供。"""
    if not isinstance(contract, dict):
        raise ValueError("reuse_contract 缺失；下一步：补齐 repo/module 的有效输入合同，Unknown 不继承")
    require_text(contract.get("source"), "reuse_contract.source")
    names = []
    for key in ("paths", "production_closure", "runtime_assembly"):
        roots = contract.get(key)
        if not isinstance(roots, list) or (key == "paths" and not roots):
            raise ValueError("reuse_contract." + key + " 缺失；下一步：补齐完整输入根或重新执行/审查")
        for name in roots:
            if (not isinstance(name, str) or not name or Path(name).is_absolute()
                    or ".." in Path(name).parts or name.startswith(":") or any(c in name for c in "*?[")):
                raise ValueError("reuse_contract." + key + " 非法路径根；下一步：使用 repo 内字面路径")
            names.append(name)
    result = {}
    for name in sorted(set(names)):
        raw = CHECKPOINT["_run_git"](root, "ls-tree", "-r", "-z", head, "--", name)
        if not raw and not allow_missing:
            raise ValueError("input_snapshot 缺输入根 " + name + "；下一步：核对闭包/装配合同后重新执行/审查")
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            meta, path = entry.split(b"\t", 1)
            mode, kind, blob = meta.decode().split()
            if kind != "blob" or mode == "120000":
                raise ValueError("input_snapshot 不支持外部/submodule/symlink 输入 " + os.fsdecode(path) + "；下一步：重新执行/审查")
            result[os.fsdecode(path)] = {"mode": mode, "blob": blob}
    return result


def reuse_inputs(root, head, receipt, contract):
    """只核原终态声明的输入；不生成新 PASS，不取消规定命令。"""
    if receipt.get("reuse_contract") != contract or contract is None:
        raise ValueError("reuse_contract 不匹配；下一步：补齐原合同或重新执行/审查")
    previous_head = receipt.get("head_commit")
    require_text(previous_head, "head_commit")
    try:
        resolved = CHECKPOINT["_run_git"](root, "rev-parse", "--verify", previous_head + "^{commit}").decode().strip()
        if resolved != previous_head:
            raise ValueError("head_commit 必须是原终态完整 SHA")
        CHECKPOINT["_run_git"](root, "merge-base", "--is-ancestor", previous_head, head)
    except ValueError as error:
        raise ValueError("head_commit 无效或非祖先: " + str(error) + "；下一步：核原版本后重新执行/审查") from error
    before = input_snapshot(root, previous_head, contract)
    now = input_snapshot(root, head, contract, allow_missing=True)
    recorded = receipt.get("input_snapshot")
    if before != now or recorded != before:
        changed = sorted(name for name in set(before) | set(now) | set(recorded or {})
                         if before.get(name) != now.get(name) or not isinstance(recorded, dict)
                         or recorded.get(name) != before.get(name))
        raise ValueError("input_snapshot 闭包/装配/集合/mode/blob 不匹配: " + ", ".join(changed) +
                         "；下一步：保留原结果，对新输入执行规定检查/本轴补审")
    return before


def checks(data, terminal=False):
    """派发前列齐规定命令；Review 前逐条核对当前输入和终态日志。"""
    state, candidate = current(data)
    try:
        require_text(data.get("checks_source"), "checks_source (repo/module/CI 回读)")
    except ValueError as error:
        raise ValueError(str(error) + "；下一步：补齐该字段为有效文本后重新预检") from error
    required = data.get("required_checks")
    if not isinstance(required, list):
        raise ValueError("required_checks 缺失；下一步：读取 repo/module manifest 与 CI")
    results = data.get("check_results")
    if terminal and not isinstance(results, list):
        raise ValueError("check_results pending：缺终态清单；下一步：保存当前候选的命令 exit/日志")
    keys = set()
    decisions = []
    root = Path(state["worktree"])
    for index, item in enumerate(required):
        field = f"required_checks[{index}]"
        if not isinstance(item, dict):
            raise ValueError(field + " 必须为 command/cwd/source；下一步：补齐 command/cwd/source 后重新预检")
        for key in ("command", "cwd", "source"):
            try:
                require_text(item.get(key), field + "." + key)
            except ValueError as error:
                raise ValueError(str(error) + "；下一步：补齐该字段为有效文本后重新预检") from error
        cwd = Path(item["cwd"])
        if not cwd.is_absolute() or not cwd.is_dir() or not cwd.resolve().is_relative_to(Path(state["worktree"])):
            raise ValueError(field + ".cwd 不属于当前 repo；下一步：修正为当前 repo 内的绝对目录后重新预检")
        identity = tuple(item[key] for key in ("command", "cwd", "source"))
        if identity in keys:
            raise ValueError(field + " 重复命令；下一步：合并重复条目后重新预检")
        keys.add(identity)
        if not terminal:
            continue
        matches = [result for result in results
                   if isinstance(result, dict) and all(result.get(key) == item[key] for key in ("command", "cwd", "source"))]
        if len(matches) != 1:
            raise ValueError(field + " pending：缺少唯一命令终态；下一步：完成该命令并保存 exit/日志")
        result = matches[0]
        inherited = "inherited_from" in result
        expected_head, expected_candidate = state["head"], candidate
        if inherited:
            result = result["inherited_from"]
            if not isinstance(result, dict):
                raise ValueError(field + ".inherited_from 必须为原终态对象；下一步：保存原结果")
            try:
                if state["dirty"]:
                    raise ValueError("candidate_sha256 dirty 输入不支持继承")
                if any(result.get(key) != item[key] for key in ("command", "cwd", "source")):
                    raise ValueError("command/cwd/source 不匹配")
                reuse_inputs(root, state["head"], result, item.get("reuse_contract"))
                expected_head = result["head_commit"]
                empty = hashlib.sha256(b"").hexdigest()
                expected_candidate = hashlib.sha256(CHECKPOINT["canonical_bytes"]({
                    "head": expected_head, "dirty": {}, "index_sha256": empty, "working_tree_diff_sha256": empty,
                })).hexdigest()
            except (ValueError, TypeError) as error:
                raise ValueError(field + ".inherited_from: " + str(error) + "；下一步：核原终态或重新执行规定命令") from error
        for key, expected in (("head_commit", expected_head), ("candidate_sha256", expected_candidate), ("status", "completed")):
            if result.get(key) != expected:
                raise ValueError(field + "." + key + " 不匹配或 pending；下一步：核对当前输入终态")
        if type(result.get("exit_code")) is not int or result["exit_code"] != 0:
            raise ValueError(field + ".exit_code 未通过；下一步：保留 FAIL 并修复原检查")
        for key in ("stdout_log", "stderr_log"):
            try:
                require_text(result.get(key), field + "." + key)
                path = Path(result[key])
                if not path.is_absolute() or not path.is_file():
                    raise ValueError("日志路径必须是绝对文件")
                # 入口与实际文件都必须在 repo 外，避免 Cleanup 删除软链入口或日志。
                entry = Path(os.path.abspath(path))
                repo_entry = Path(os.path.abspath(data["worktree"]))
                if (entry.is_relative_to(repo_entry) or entry.is_relative_to(root)
                        or (path.parent.resolve() / path.name).is_relative_to(root)
                        or path.resolve().is_relative_to(root)):
                    raise ValueError("日志入口或解析后的实际位置在 repo 内，必须使用 repo外日志")
                path.read_bytes()
            except (ValueError, OSError) as error:
                reason = ": " + str(error) if isinstance(error, ValueError) else ""
                raise ValueError(field + "." + key + " 缺可读日志 (" + type(error).__name__ + reason +
                                 ")；下一步：保存当前候选的真实日志、修正绝对路径后重新预检；"
                                 "将真实终态日志移到 repo外持久 artifact，更新绝对路径后重新预检") from error
        decisions.append({"command": item["command"], "decision": "inherited" if inherited else "current-pass",
                          "source_head": expected_head, "source": item["source"],
                          "reason": "合同内精确输入/闭包/装配/mode/blob 相同" if inherited else
                                    "当前候选已有规定命令终态 PASS；同输入不因新报告重跑"})
    return {"action": "checks-passed" if terminal else "checks-listed",
            "head_commit": state["head"], "candidate_sha256": candidate,
            "checks_source": data["checks_source"], "required_checks": required, "check_decisions": decisions}


def mode_category(value):
    """tar 权限与 Git mode 只比较文件种类/执行位，不把写权限当执行位。"""
    mode = int(value, 8) if isinstance(value, str) else value
    if type(mode) is not int or mode < 0:
        raise ValueError("source mode 必须为 octal 字符串或整数")
    kind = stat.S_IFMT(mode) or stat.S_IFREG
    if kind not in (stat.S_IFREG, stat.S_IFLNK):
        raise ValueError("不支持的 source mode")
    return kind, bool(mode & 0o111) if kind == stat.S_IFREG else False


def coverage(data, paths, root):
    axes = data.get("coverage")
    if axes is None:
        return {axis: {"fresh_paths": paths, "inherited_paths": []} for axis in ("standards", "spec")}
    if not isinstance(axes, dict) or set(axes) != {"standards", "spec"}:
        raise ValueError("coverage 必须包含独立 standards/spec；下一步：补齐两轴 coverage 对象后重新预检")
    git = lambda *args: CHECKPOINT["_run_git"](root, *args)

    def source(commit, name):
        raw = git("ls-tree", "-z", commit, "--", name)
        entries = [entry for entry in raw.split(b"\0") if entry]
        if not entries:
            return None
        if len(entries) != 1:
            raise ValueError("coverage inputs 路径不唯一: " + name)
        meta, actual = entries[0].split(b"\t", 1)
        mode, kind, oid = meta.split()
        if os.fsdecode(actual) != name or kind != b"blob":
            raise ValueError("coverage inputs 不是文件: " + name)
        return {"content_sha256": hashlib.sha256(git("cat-file", "blob", oid.decode())).hexdigest(),
                "mode": mode_category(mode.decode())}

    decisions = {}
    for axis, value in axes.items():
        field = "coverage." + axis
        if not isinstance(value, dict):
            raise ValueError(field + " 必须为对象；下一步：补齐 fresh_paths/inherited 对象后重新预检")
        fresh, inherited = value.get("fresh_paths"), value.get("inherited")
        if not isinstance(fresh, list) or not isinstance(inherited, list):
            raise ValueError(field + " 缺 fresh_paths/inherited；下一步：补齐 fresh_paths/inherited 列表后重新预检")
        seen = list(fresh)
        for index, receipt in enumerate(inherited):
            receipt_field = f"{field}.inherited[{index}]"
            if not isinstance(receipt, dict):
                raise ValueError(receipt_field + " 必须为对象；下一步：补齐本轴继承记录后重新预检")
            location = receipt_field
            try:
                if (receipt.get("axis") != axis or receipt.get("base_commit") != data["base_commit"]
                        or receipt.get("status") != "completed" or receipt.get("verdict") != "pass"):
                    raise ValueError(field + " 继承错轴/base/终态；下一步：只继承本轴精确覆盖")
                location = receipt_field + ".source"
                require_text(receipt.get("source"), location)
                location = receipt_field + ".head_commit"
                require_text(receipt.get("head_commit"), location)
                git("merge-base", "--is-ancestor", data["base_commit"], receipt["head_commit"])
                names = receipt.get("paths")
                inputs = receipt.get("inputs")
                location = receipt_field + ".inputs/paths"
                if not isinstance(names, list) or not isinstance(inputs, dict) or set(names) != set(inputs):
                    raise ValueError(field + " 缺精确 inputs/paths")
                for name in names:
                    location = receipt_field + ".inputs." + name
                    previous = source(receipt["head_commit"], name)
                    now = source(data["head_commit"], name)
                    recorded = inputs[name]
                    if not isinstance(recorded, dict) or not {"content_sha256", "mode"} <= set(recorded):
                        raise ValueError(field + ".inputs." + name + " 缺正文/执行位来源")
                    location = receipt_field + ".inputs." + name + ".mode"
                    expected = {"content_sha256": recorded["content_sha256"], "mode": mode_category(recorded["mode"])}
                    location = receipt_field + ".inputs." + name
                    if previous is None or previous != now or previous != expected:
                        raise ValueError(field + ".inputs." + name + " 正文/执行位已变；下一步：本轴重新审查")
                if names:
                    location = receipt_field + ".reuse_contract"
                    contract = receipt.get("reuse_contract")
                    location = receipt_field + ".input_snapshot" if contract else location
                    snapshot = reuse_inputs(root, data["head_commit"], receipt, contract)
                    if not set(names) <= set(snapshot):
                        raise ValueError("reuse_contract 未包含被审路径；下一步：补齐完整合同后本轴重审")
                seen.extend(names)
            except (ValueError, KeyError, TypeError, OSError) as error:
                raise ValueError(f"{location}: {error}；下一步：核对并补齐该继承字段或来源证据后重新预检") from error
        try:
            if len(seen) != len(set(seen)) or set(seen) != set(paths):
                raise ValueError(field + " whole-change 路径集合错；下一步：补齐本轴未覆盖路径后重新预检")
        except TypeError as error:
            raise ValueError(f"{field}: {error}；下一步：核对并补齐本轴路径集合后重新预检") from error
        decisions[axis] = {"fresh_paths": fresh, "inherited_paths": [name for r in inherited for name in r["paths"]],
                           "reason": "本轴完整集合＝fresh＋本轴原终态精确输入继承；当前 Head 结论仍须独立返回"}
    return decisions


def materialize(data):
    try:
        require_text(data.get("base_commit"), "base_commit")
    except ValueError as error:
        raise ValueError(str(error) + "；下一步：补齐该字段为 packet 固定版本后重新预检") from error
    state, candidate = current(data)
    root = Path(state["worktree"])
    scope = data.get("review_scope")
    if scope not in ("implementation", "whole-change"):
        raise ValueError("review_scope 非法")
    if scope == "whole-change" and state["dirty"]:
        raise ValueError("whole-change worktree 必须 clean")
    if scope == "implementation":
        allowed = data.get("allowed_dirty_paths")
        if not isinstance(allowed, list) or set(state["dirty"]) - set(allowed):
            raise ValueError("allowed_dirty_paths 缺失或存在票外 dirty；下一步：核隔离范围")
    commands = []

    def git(*args, check=True):
        commands.append(shlex.join(["git", "-C", str(root), *args]))
        return CHECKPOINT["_run_git"](root, *args, check=check)

    base = git("rev-parse", "--verify", data["base_commit"] + "^{commit}").decode().strip()
    head = state["head"]
    git("merge-base", "--is-ancestor", base, head)
    try:
        require_text(data.get("target_commit"), "target_commit")
        target = git("rev-parse", "--verify", data["target_commit"] + "^{commit}").decode().strip()
        git("merge-base", "--is-ancestor", target, head)
    except ValueError as error:
        raise ValueError("target_commit=" + str(data.get("target_commit")) + " head=" + head +
                         " 非有效祖先: " + str(error) +
                         "；下一步：保留现场，由 coordinator 获授权合流后重冻结候选；禁止 force/rewrite") from error
    relation = [base, head] if scope == "whole-change" else [base]
    flags = ["--no-ext-diff", "--no-textconv", "--no-renames", "--no-color"]
    patch = git("diff", "--binary", "--full-index", *flags, *relation, "--", ".")
    names = git("diff", "--name-status", *flags, *relation, "--", ".")
    path_raw = git("diff", "--name-only", "-z", *flags, *relation, "--", ".")
    paths = CHECKPOINT["_nul_paths"](path_raw)
    if scope == "implementation":
        for name in CHECKPOINT["_nul_paths"](git("ls-files", "--others", "--exclude-standard", "-z")):
            patch += git("diff", "--no-index", "--binary", "--full-index", *flags, "--", "/dev/null", name, check=False)
            names += git("diff", "--no-index", "--name-status", *flags, "--", "/dev/null", name, check=False)
            paths.append(name)
    if not patch or not names:
        raise ValueError("diff.patch/changed-paths.txt 为空；下一步：核审查边界")
    starts = [line for line, raw in enumerate(patch.splitlines(), 1) if raw.startswith(b"diff --git ")]
    rows = names.splitlines()
    if len(starts) != len(rows):
        raise ValueError("changed-paths.txt 与 diff.patch 文件边界不匹配；下一步：核审查边界后重建新 bundle")
    names = b"".join(row + b"\t@" + str(line).encode() + b"\n" for row, line in zip(rows, starts))
    if data.get("coverage") is not None and scope != "whole-change":
        raise ValueError("coverage 继承只适用 clean whole-change")
    coverage_decisions = coverage(data, paths, root)
    commits = git("log", "--format=%H %s", base + ".." + head) or b"none\n"
    additions = git("diff-tree", "--root", "--no-commit-id", "--diff-filter=A", "--name-status", "--no-renames", "-r", base) or b"none\n"
    status = git("status", "--short", "--untracked-files=all")
    staged = git("diff", "--cached", "--name-status", "--no-renames", "--", ".")
    fixed = {"packet": data["base_commit"], "resolved_sha": base, "head_sha": head,
             "review_scope": scope, "diff_relation": "git diff " + " ".join(relation) + " -- .",
             "candidate_sha256": candidate, "target_commit": target,
             "target_reason": "一次读取固定 target，已验证 target 为当前 head 祖先；无需追动态主线",
             "coverage_decisions": coverage_decisions}
    values = {
        "fixed-point.txt": (json.dumps(fixed, ensure_ascii=False, indent=2) + "\n").encode(),
        "diff.patch": patch, "commits.txt": commits, "changed-paths.txt": names,
        "fixed-point-added-paths.txt": additions,
        "worktree-state.txt": b"git status --short\n" + status + b"git diff --cached --name-status -- .\n" + staged +
            ("NO_STAGED_FILES=" + ("false" if state["staged"] else "true") + "\n").encode(),
        "commands.txt": ("\n".join(commands) + "\n").encode(),
    }
    if current(data) != (state, candidate):
        raise ValueError("candidate_sha256 生成中变化；下一步：停止 writer 后重建新 bundle")
    return values


def preflight(data, create=False):
    try:
        require_text(data.get("bundle_path"), "bundle_path")
    except ValueError as error:
        raise ValueError(str(error) + "；下一步：补齐该字段为 repo 外绝对路径后重新预检") from error
    checked = checks(data, terminal=True)
    values = materialize(data)
    path = Path(data["bundle_path"]).expanduser()
    root = Path(data["worktree"]).resolve()
    if not path.is_absolute() or path.resolve().is_relative_to(root):
        raise ValueError("bundle_path 必须位于 repo 外")
    if create:
        if path.exists():
            raise ValueError("bundle immutable；下一步：使用新目录，保留原 FAIL")
        path.mkdir(parents=True)
        for name, raw in values.items():
            with (path / name).open("xb") as file:
                file.write(raw)
    readback = {}
    for name in FILES:
        file = path / name
        if not file.is_file():
            raise ValueError(name + " 缺失；下一步：补齐新 bundle")
        raw = file.read_bytes()
        # 仅输出 framing 的一个末尾 LF 可不同；正文 Git blob 和执行位仍精确比较。
        if raw.removesuffix(b"\n") != values[name].removesuffix(b"\n"):
            raise ValueError(name + " 与当前 Git 不匹配；下一步：按固定 base/head 重建新 bundle")
        readback[name] = {"path": str(file), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if current(data)[1] != checked["candidate_sha256"]:
        raise ValueError("candidate_sha256 预检中变化")
    fixed = json.loads(values["fixed-point.txt"])
    return {**checked, "action": "preflight-passed", "review_scope": data["review_scope"],
            "fixed_point": data["base_commit"], "base_commit": fixed["resolved_sha"],
            "target_commit": fixed["target_commit"], "target_reason": fixed["target_reason"],
            "coverage_decisions": fixed["coverage_decisions"], "bundle_path": str(path), "readback": readback}


def main():
    try:
        data = json.load(sys.stdin)
        command = sys.argv[1]
        if command == "checks":
            result = checks(data)
        elif command in ("bundle", "preflight"):
            result = preflight(data, create=command == "bundle")
        else:
            raise ValueError("未知命令")
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, IndexError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

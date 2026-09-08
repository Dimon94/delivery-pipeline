#!/usr/bin/env python3
"""把 canonical continuation request 转成 Codex CLI 精确 resume 参数。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import checkpoint as CHECKPOINT


UNKNOWN = "Unknown"
SHA256 = re.compile(r"[0-9a-f]{64}")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")
EFFORT = re.compile(r"[a-z][a-z0-9-]*")


class CodexAdapterError(ValueError):
    """接续请求不能安全映射为精确 Codex CLI resume。"""


def _text(value: object, field: str, pattern: re.Pattern[str]) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().lower() == UNKNOWN.lower()
            or pattern.fullmatch(value) is None):
        raise CodexAdapterError(f"{field} 缺失、Unknown 或格式不支持")
    return value


def resume_request(request: object) -> dict[str, Any]:
    """把已绑定身份的 request 转成 `codex resume` 的原生参数。"""
    if not isinstance(request, dict) or set(request) != {
        "request_id", "intent_sha256", "session_id", "worktree", "target_request",
    }:
        raise CodexAdapterError("request 字段不完整或包含未支持字段")
    intent = _text(request["intent_sha256"], "intent_sha256", SHA256)
    if request["request_id"] != "request-" + intent:
        raise CodexAdapterError("request_id 未绑定 continuation intent")
    try:
        session_id = str(UUID(str(request["session_id"])))
    except (ValueError, AttributeError) as error:
        raise CodexAdapterError("session_id 必须是精确原生 UUID，禁止 --last") from error
    if session_id != request["session_id"]:
        raise CodexAdapterError("session_id 必须使用 canonical UUID")
    worktree = request["worktree"]
    if not isinstance(worktree, str) or not Path(worktree).is_absolute():
        raise CodexAdapterError("worktree 必须是绝对路径")
    target = request["target_request"]
    if not isinstance(target, dict) or set(target) != {"model", "effort"}:
        raise CodexAdapterError("target_request 必须明确 model/effort")
    model = _text(target["model"], "target_request.model", MODEL)
    effort = _text(target["effort"], "target_request.effort", EFFORT)
    return {
        "agent_kind": "codex",
        "native_args": [
            "resume", session_id, "--model", model,
            "-c", f'model_reasoning_effort="{effort}"',
            "-s", "danger-full-access", "-a", "never",
            "-C", worktree, "--no-alt-screen",
        ],
        "request_id": request["request_id"],
        "session_id": session_id,
        "worktree": worktree,
    }


def resume_from_checkpoint(checkpoint: object, request: object) -> dict[str, Any]:
    """复用 canonical checkpoint/intent，拒绝跨 runtime 或跨阶段接续。"""
    if not isinstance(checkpoint, dict):
        raise CodexAdapterError("checkpoint 必须是 object")
    try:
        CHECKPOINT.validate_checkpoint(checkpoint)
    except CHECKPOINT.CheckpointError as error:
        raise CodexAdapterError(f"checkpoint 不可核验: {error}") from error
    if checkpoint["runtime"] != "herdr-codex-pane":
        raise CodexAdapterError("runtime 不是 herdr-codex-pane")
    if checkpoint["phase"] != "starting" or checkpoint["development_mode"] != "staged":
        raise CodexAdapterError("只有 staged starting checkpoint 可以 resume")
    if not isinstance(request, dict) or set(request) != {
        "request_id", "intent_sha256", "target_request",
    }:
        raise CodexAdapterError("canonical continuation request 字段不完整")
    target = request["target_request"]
    try:
        intent = CHECKPOINT.build_continuation_intent(
            checkpoint, target_request=target)
    except CHECKPOINT.CheckpointError as error:
        raise CodexAdapterError(f"continuation intent 不可核验: {error}") from error
    if request["intent_sha256"] != intent[CHECKPOINT.INTENT_FINGERPRINT_FIELD]:
        raise CodexAdapterError("continuation intent 与 checkpoint 不匹配")
    result = resume_request({
        "request_id": request["request_id"],
        "intent_sha256": request["intent_sha256"],
        "session_id": checkpoint["session_id"],
        "worktree": checkpoint["execution_worktree"],
        "target_request": target,
    })
    return {**result, "checkpoint_sha256": checkpoint[CHECKPOINT.FINGERPRINT_FIELD]}


def _load_checkpoint(path: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve(strict=True)
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("execution_worktree"), str):
        raise CodexAdapterError("checkpoint 缺少 execution_worktree")
    try:
        return CHECKPOINT.read_checkpoint(
            target, worktree=raw["execution_worktree"])
    except CHECKPOINT.CheckpointError as error:
        raise CodexAdapterError(f"checkpoint 持久读回失败: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("request_json", help="canonical continuation request JSON；- 表示 stdin")
    args = parser.parse_args()
    try:
        source = sys.stdin if args.request_json == "-" else open(
            args.request_json, encoding="utf-8")
        with source:
            request = json.load(source)
        print(json.dumps(resume_from_checkpoint(_load_checkpoint(args.checkpoint), request),
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (CodexAdapterError, OSError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

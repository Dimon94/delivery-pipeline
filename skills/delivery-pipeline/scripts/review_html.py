#!/usr/bin/env python3
"""Plan Review 与 Merge Review 的确定性 show-me HTML 渲染模块。

按 PR / Review 决策顺序组织：
1. 顶栏与关键指标（状态、Spec、集成 HEAD、审查/检查摘要）
2. Summary（波次与关键路径流图 + 变更文件树 + 规划建议）
3. Evidence（解析后的整体审查 / 整体检查 / 蜂巢场景证据，缺件保留原始坐标）
4. Merge Danger（风险、验证缺口、非阻断 findings、自动处理的偏差、计划调整）
5. Plan vs Delivery（逐票计划验收与实际交付对照）与测试策略

样式使用宿主主题 CSS 变量（兼顾 T3 Code html_render 与独立浏览器明暗模式），
不在 html/body/外层容器设置页面背景、外框或 vh 高度。
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

ESC = lambda v: html.escape(str(v if v is not None else "Unknown"))  # noqa: E731

CSS = """\
:root {
  color-scheme: light dark;
  --dp-fg: var(--foreground, CanvasText);
  --dp-muted: var(--muted-foreground, color-mix(in srgb, CanvasText 60%, Canvas));
  --dp-card: var(--card, color-mix(in srgb, CanvasText 3%, Canvas));
  --dp-subtle: var(--secondary, color-mix(in srgb, CanvasText 6%, Canvas));
  --dp-code: var(--code-background, color-mix(in srgb, CanvasText 7%, Canvas));
  --dp-border: var(--border, color-mix(in srgb, CanvasText 15%, Canvas));
  --dp-primary: var(--primary, #3b82f6);
  --dp-ok: var(--success, #22c55e);
  --dp-warn: var(--warning, #eab308);
  --dp-danger: var(--destructive, #ef4444);
  --dp-info: var(--info, #38bdf8);
  --dp-radius: var(--radius, 10px);
  --dp-sans: var(--font-sans, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
  --dp-mono: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: transparent; color: var(--dp-fg); font: 14px/1.55 var(--dp-sans); }
.dp-page { width: 100%; max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
h1, h2, h3, p { margin: 0; }
a { color: var(--dp-primary); text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre { font-family: var(--dp-mono); font-size: 12.5px; overflow-wrap: anywhere; }
code { background: var(--dp-code); padding: 1px 5px; border-radius: 5px; }
pre { white-space: pre-wrap; background: var(--dp-code); border: 1px solid var(--dp-border); border-radius: calc(var(--dp-radius) - 2px); padding: 12px; margin: 8px 0 0; font-size: 12px; line-height: 1.5; }
.dp-mono { font-family: var(--dp-mono); font-variant-numeric: tabular-nums; }
.dp-muted { color: var(--dp-muted); font-size: 12.5px; }

/* Header */
.dp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding-bottom: 12px; border-bottom: 1px solid var(--dp-border); }
.dp-head-main { flex: 1 1 320px; min-width: 0; }
.dp-head-badge { flex: 0 0 auto; }
.dp-eyebrow { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.dp-title { font-size: clamp(19px, 3vw, 23px); font-weight: 700; letter-spacing: -0.015em; line-height: 1.25; }
.dp-meta { display: flex; align-items: center; gap: 8px 14px; flex-wrap: wrap; margin-top: 8px; font-size: 12.5px; color: var(--dp-muted); }
.dp-meta-item { display: inline-flex; align-items: center; gap: 5px; }

/* Pills & badges */
.dp-pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 600; line-height: 1.45; white-space: nowrap; border: 1px solid var(--dp-border); background: var(--dp-subtle); color: var(--dp-fg); }
.dp-pill-lg { padding: 4px 11px; font-size: 12.5px; }
.dp-ok { background: color-mix(in srgb, var(--dp-ok) 15%, transparent); border-color: color-mix(in srgb, var(--dp-ok) 38%, transparent); color: var(--dp-ok); }
.dp-warn { background: color-mix(in srgb, var(--dp-warn) 16%, transparent); border-color: color-mix(in srgb, var(--dp-warn) 40%, transparent); color: var(--dp-warn); }
.dp-danger { background: color-mix(in srgb, var(--dp-danger) 15%, transparent); border-color: color-mix(in srgb, var(--dp-danger) 40%, transparent); color: var(--dp-danger); }
.dp-info { background: color-mix(in srgb, var(--dp-primary) 14%, transparent); border-color: color-mix(in srgb, var(--dp-primary) 36%, transparent); color: var(--dp-primary); }
.dp-neutral { background: var(--dp-subtle); border-color: var(--dp-border); color: var(--dp-muted); }

/* KPI strip */
.dp-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.dp-kpi { background: var(--dp-card); border: 1px solid var(--dp-border); border-radius: var(--dp-radius); padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
.dp-kpi-label { font-size: 11.5px; color: var(--dp-muted); font-weight: 500; }
.dp-kpi-val { font-size: 16px; font-weight: 700; line-height: 1.3; font-variant-numeric: tabular-nums; }
.dp-kpi-sub { font-size: 11.5px; color: var(--dp-muted); line-height: 1.4; }

/* Sections & Cards */
.dp-section { display: flex; flex-direction: column; gap: 10px; }
.dp-section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.dp-section-title { font-size: 14px; font-weight: 700; letter-spacing: 0.01em; display: inline-flex; align-items: center; gap: 7px; }
.dp-card { background: var(--dp-card); border: 1px solid var(--dp-border); border-radius: var(--dp-radius); padding: 16px; }
.dp-callout { background: color-mix(in srgb, var(--dp-primary) 7%, var(--dp-card)); border: 1px solid color-mix(in srgb, var(--dp-primary) 24%, var(--dp-border)); border-left: 3px solid var(--dp-primary); border-radius: var(--dp-radius); padding: 12px 14px; font-size: 13px; line-height: 1.55; }

/* Wave DAG */
.dp-waves { display: grid; grid-template-columns: repeat(auto-fit, minmax(195px, 1fr)); gap: 10px; align-items: stretch; }
.dp-wave-col { background: var(--dp-card); border: 1px solid var(--dp-border); border-radius: var(--dp-radius); padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.dp-wave-head { display: flex; align-items: center; justify-content: space-between; font-size: 11.5px; font-weight: 700; color: var(--dp-muted); text-transform: uppercase; letter-spacing: 0.04em; padding-bottom: 6px; border-bottom: 1px solid var(--dp-border); }
.dp-node { background: var(--dp-subtle); border: 1px solid var(--dp-border); border-radius: calc(var(--dp-radius) - 3px); padding: 9px 10px; display: flex; flex-direction: column; gap: 5px; }
.dp-node-crit { border-left: 3px solid var(--dp-primary); }
.dp-node-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.dp-node-id { font-family: var(--dp-mono); font-weight: 700; font-size: 12.5px; }
.dp-node-title { font-size: 12.5px; line-height: 1.4; font-weight: 500; }
.dp-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.dp-tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: var(--dp-code); color: var(--dp-muted); font-family: var(--dp-mono); }

/* Diff Tree */
.dp-tree { display: flex; flex-direction: column; gap: 10px; }
.dp-tree-group { display: flex; flex-direction: column; gap: 4px; }
.dp-tree-dir { display: flex; align-items: center; justify-content: space-between; font-size: 12px; font-weight: 600; color: var(--dp-muted); padding: 4px 0; border-bottom: 1px dashed var(--dp-border); }
.dp-tree-row { display: grid; grid-template-columns: minmax(0, 1fr) auto 64px; align-items: center; gap: 10px; padding: 3px 0; font-size: 12.5px; }
.dp-tree-path { font-family: var(--dp-mono); overflow-wrap: anywhere; }
.dp-stat-num { font-family: var(--dp-mono); font-size: 11.5px; font-variant-numeric: tabular-nums; white-space: nowrap; display: inline-flex; gap: 6px; }
.dp-add { color: var(--dp-ok); }
.dp-del { color: var(--dp-danger); }
.dp-bar { height: 6px; border-radius: 999px; background: var(--dp-subtle); overflow: hidden; display: flex; }
.dp-bar-add { background: var(--dp-ok); height: 100%; }
.dp-bar-del { background: var(--dp-danger); height: 100%; }

/* Evidence Grid */
.dp-ev-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 12px; }
.dp-ev-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.dp-ev-title { font-size: 13.5px; font-weight: 700; }
.dp-axes { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }
.dp-axis { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; padding: 8px 10px; border-radius: calc(var(--dp-radius) - 3px); background: var(--dp-subtle); }
.dp-axis-name { font-weight: 600; font-size: 12.5px; }
.dp-counts { display: inline-flex; gap: 5px; flex-wrap: wrap; }
.dp-checklist { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 7px; }
.dp-check-item { padding: 8px 10px; border-radius: calc(var(--dp-radius) - 3px); background: var(--dp-subtle); font-size: 12.5px; line-height: 1.45; display: flex; flex-direction: column; gap: 3px; }
.dp-check-res { font-weight: 500; color: var(--dp-fg); }
.dp-check-cmd { font-family: var(--dp-mono); font-size: 11.5px; color: var(--dp-muted); display: block; overflow-wrap: anywhere; }
.dp-finding { padding: 9px 11px; border-radius: calc(var(--dp-radius) - 3px); background: var(--dp-subtle); border-left: 3px solid var(--dp-warn); display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; }
.dp-finding-p3 { border-left-color: var(--dp-border); }
.dp-finding-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-weight: 600; }
.dp-findings-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }

/* Merge Danger */
.dp-danger-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.dp-list { margin: 6px 0 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.dp-list li { line-height: 1.5; }
.dp-subhead { font-size: 12px; font-weight: 700; color: var(--dp-muted); text-transform: uppercase; letter-spacing: 0.03em; display: flex; align-items: center; gap: 6px; }

/* Table */
.dp-scroll { overflow-x: auto; border: 1px solid var(--dp-border); border-radius: var(--dp-radius); background: var(--dp-card); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { font-size: 11.5px; font-weight: 700; color: var(--dp-muted); text-transform: uppercase; letter-spacing: 0.03em; background: var(--dp-subtle); border-bottom: 1px solid var(--dp-border); padding: 9px 12px; text-align: left; white-space: nowrap; }
td { border-bottom: 1px solid var(--dp-border); padding: 11px 12px; vertical-align: top; text-align: left; }
tr:last-child td { border-bottom: 0; }
.dp-ticket-title { font-weight: 600; line-height: 1.4; }
.dp-ticket-sub { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; margin-top: 5px; }
.dp-delivery-cell { display: flex; flex-direction: column; gap: 6px; min-width: 155px; }
.dp-slice { padding: 8px 10px; border-radius: calc(var(--dp-radius) - 3px); background: var(--dp-subtle); font-size: 12px; line-height: 1.45; }

/* Strategy KV grid */
.dp-kv { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 8px 14px; font-size: 13px; margin-top: 10px; }
.dp-kv dt { font-weight: 600; color: var(--dp-muted); font-size: 12px; }
.dp-kv dd { margin: 0; line-height: 1.5; }

/* Details & Footer */
details { margin-top: 8px; }
summary { cursor: pointer; font-size: 12.5px; font-weight: 600; color: var(--dp-muted); user-select: none; }
summary:hover { color: var(--dp-fg); }
.dp-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; background: color-mix(in srgb, var(--dp-primary) 9%, var(--dp-card)); border: 1px solid color-mix(in srgb, var(--dp-primary) 30%, var(--dp-border)); border-radius: var(--dp-radius); padding: 12px 16px; font-size: 13px; font-weight: 500; }

@media (max-width: 640px) {
  .dp-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dp-kv { grid-template-columns: 1fr; gap: 3px; }
  .dp-kv dt { margin-top: 6px; }
  .dp-tree-row { grid-template-columns: minmax(0, 1fr) auto; }
  .dp-bar { display: none; }
}
"""


def coordinate(value) -> str:
    label = ESC(value)
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return f'<a href="{label}">{label}</a>'
    return f"<code>{label}</code>"


def short_link(url: str | None, fallback: str = "Unknown") -> str:
    if not url:
        return f"<code>{ESC(fallback)}</code>"
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        return f"<code>{ESC(url)}</code>"
    m = re.search(r"/issue/([A-Z]+-\d+)(?:/([^/?#]+))?", url)
    if m:
        text = f"{m.group(1)} ↗"
    else:
        m_gh = re.search(r"github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)", url)
        text = f"{m_gh.group(1)}#{m_gh.group(2)} ↗" if m_gh else url
    return f'<a href="{ESC(url)}" title="{ESC(url)}">{ESC(text)}</a>'


def short_sha(sha: str | None) -> str:
    if not sha:
        return "Unknown"
    s = str(sha).strip()
    return s[:8] if re.fullmatch(r"[a-f0-9]{10,64}", s) else s


def pill(text: str, tone: str = "neutral", large: bool = False) -> str:
    cls = f"dp-pill dp-{tone}" + (" dp-pill-lg" if large else "")
    return f'<span class="{cls}">{ESC(text)}</span>'


def verdict_tone(verdict: str | None) -> str:
    v = str(verdict or "").upper()
    if v in ("PASS", "CLOSED", "CONSUMED", "INTEGRATED", "OK", "TRUE"):
        return "ok"
    if v in ("FIX", "WARN", "CLOSE_PENDING", "PENDING"):
        return "warn"
    if v in ("REVIEW_BLOCKED", "REVIEW_EXHAUSTED", "BLOCKED", "FAIL", "FAILED", "FALSE"):
        return "danger"
    return "neutral"


def read_json_if_file(path_value) -> dict | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    p = Path(path_value.strip())
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _git_out(wt: str, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", wt, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def read_diff_files(state: dict) -> list[dict]:
    """返回 [{"path", "added", "deleted"}]；优先读 state['diff_files']，否则只读 git numstat。"""
    if state.get("diff_files") is not None:
        return list(state["diff_files"])
    lanes = state.get("lanes") or {}
    mrow = next((r for r in lanes.values() if r.get("role") == "map"), None)
    if not mrow:
        return []
    wt = mrow.get("integration_worktree_path") or mrow.get("worktree")
    base = mrow.get("base_commit") or (state.get("driver") or {}).get("plan", {}).get("base_commit")
    head = state.get("integration_head")
    if not wt or not head or not Path(wt).is_dir():
        return []
    # 分支 rebase 到更新后的默认分支时，取所有远端/本地默认分支 merge-base 中最新者，避免混入主干无关文件。
    effective_base = base
    refs_raw = _git_out(
        str(wt), "for-each-ref", "--format=%(refname)",
        "refs/remotes/*/main", "refs/remotes/*/master", "refs/heads/main", "refs/heads/master",
    ) or ""
    for ref in refs_raw.splitlines():
        mb = _git_out(str(wt), "merge-base", ref, head)
        if not mb or mb == head:
            continue
        if not effective_base or _git_out(str(wt), "merge-base", "--is-ancestor", effective_base, mb) is not None:
            effective_base = mb
    if not effective_base:
        return []
    raw = _git_out(str(wt), "diff", "--numstat", f"{effective_base}..{head}")
    if raw is None:
        return []
    files = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        add_s, del_s, path = parts
        added = int(add_s) if add_s.isdigit() else 0
        deleted = int(del_s) if del_s.isdigit() else 0
        files.append({"path": path, "added": added, "deleted": deleted, "binary": add_s == "-"})
    return files


def _lane_summary(rows: list[dict]) -> dict:
    """把同一张票的 1..N 条 lane 归纳成可读交付状态、最终提交和精简轨迹。"""
    if not rows:
        return {"label": "未派发", "tone": "neutral", "commit": None, "model": None, "trace": "", "drift": ""}
    ordered = sorted(rows, key=lambda r: r.get("lane_id", ""))
    done_states = {"closed", "integrated", "consumed"}
    winner = next((r for r in reversed(ordered) if r.get("state") in done_states), ordered[-1])
    repairs = sum(int(r.get("repairs") or 0) for r in ordered)
    had_merger = any(r.get("role") == "integration" or r.get("merges") for r in ordered)
    had_conflict = any(r.get("state") == "integration_conflict" for r in ordered)
    st = winner.get("state") or "Unknown"
    if st in done_states:
        if had_merger or had_conflict:
            label = "冲突经 merger 合入"
            tone = "ok"
        elif repairs:
            label = f"修复 {repairs} 轮后合入"
            tone = "ok"
        else:
            label = "已合入" if winner.get("output_mode") == "commit" or winner.get("integrated_commit") else "已完成"
            tone = "ok"
    elif st in ("running", "created", "awaiting_human", "terminal"):
        label, tone = st, "info"
    elif st in ("blocked", "integration_conflict", "integration_checks_failed"):
        label, tone = st, "danger"
    else:
        label, tone = st, "warn"
    commit = winner.get("integrated_commit") or winner.get("head_commit")
    model = winner.get("model")
    effort = winner.get("effort")
    model_str = f"{model} ({effort})" if model and effort else (model or "")
    trace = " → ".join(f"{r['lane_id']}:{r.get('state')}" for r in ordered) if len(ordered) > 1 else ""
    return {"label": label, "tone": tone, "commit": commit, "model": model_str, "trace": trace,
            "drift": winner.get("scope_drift") or ""}


def _render_diff_tree(files: list[dict]) -> str:
    if not files:
        return ""
    total_add = sum(f["added"] for f in files)
    total_del = sum(f["deleted"] for f in files)
    max_lines = max((f["added"] + f["deleted"] for f in files), default=1) or 1
    groups: dict[str, list[dict]] = {}
    for item in files:
        parts = item["path"].split("/")
        group = "/".join(parts[:2]) + "/" if len(parts) > 2 else (parts[0] + "/" if len(parts) > 1 else "./")
        groups.setdefault(group, []).append(item)

    def render_group(group: str, items: list[dict]) -> str:
        g_add = sum(x["added"] for x in items)
        g_del = sum(x["deleted"] for x in items)
        rows = []
        for x in items:
            name = x["path"][len(group):] if group != "./" and x["path"].startswith(group) else x["path"]
            total = x["added"] + x["deleted"]
            if x.get("binary"):
                stat = '<span class="dp-muted">binary</span>'
                bar = '<div class="dp-bar"></div>'
            else:
                add_w = round((x["added"] / max_lines) * 100) if total else 0
                del_w = round((x["deleted"] / max_lines) * 100) if total else 0
                stat = (
                    f'<span class="dp-stat-num">'
                    f'<span class="dp-add">+{x["added"]}</span>'
                    f'<span class="dp-del">-{x["deleted"]}</span>'
                    f"</span>"
                )
                bar = (
                    f'<div class="dp-bar" aria-hidden="true">'
                    f'<span class="dp-bar-add" style="width:{add_w}%"></span>'
                    f'<span class="dp-bar-del" style="width:{del_w}%"></span>'
                    f"</div>"
                )
            rows.append(f'<div class="dp-tree-row"><span class="dp-tree-path">{ESC(name)}</span>{stat}{bar}</div>')
        return (
            f'<div class="dp-tree-group">'
            f'<div class="dp-tree-dir"><span class="dp-mono">{ESC(group)}</span>'
            f'<span class="dp-stat-num"><span>{len(items)} 文件</span>'
            f'<span class="dp-add">+{g_add}</span><span class="dp-del">-{g_del}</span></span></div>'
            f'{"".join(rows)}</div>'
        )

    body = "".join(render_group(g, items) for g, items in sorted(groups.items()))
    summary_line = (
        f'<span class="dp-stat-num"><span>{len(files)} 个文件</span>'
        f'<span class="dp-add">+{total_add}</span>'
        f'<span class="dp-del">-{total_del}</span></span>'
    )
    if len(files) > 10:
        dir_max = max((sum(x["added"] + x["deleted"] for x in items) for items in groups.values()), default=1) or 1
        dir_rows = []
        for g, items in sorted(groups.items()):
            ga = sum(x["added"] for x in items)
            gd = sum(x["deleted"] for x in items)
            aw = round((ga / dir_max) * 100) if (ga + gd) else 0
            dw = round((gd / dir_max) * 100) if (ga + gd) else 0
            dir_rows.append(
                f'<div class="dp-tree-row">'
                f'<span class="dp-tree-path">{ESC(g)} <span class="dp-muted">({len(items)} 文件)</span></span>'
                f'<span class="dp-stat-num"><span class="dp-add">+{ga}</span><span class="dp-del">-{gd}</span></span>'
                f'<div class="dp-bar" aria-hidden="true">'
                f'<span class="dp-bar-add" style="width:{aw}%"></span>'
                f'<span class="dp-bar-del" style="width:{dw}%"></span></div></div>'
            )
        return (
            f'<div class="dp-card">'
            f'<div class="dp-ev-head"><span class="dp-ev-title">变更目录树</span>{summary_line}</div>'
            f'<div class="dp-tree">{"".join(dir_rows)}</div>'
            f'<details><summary>展开逐文件明细（{len(files)} 个文件）</summary>'
            f'<div class="dp-tree" style="margin-top:10px">{body}</div></details></div>'
        )
    return (
        f'<div class="dp-card">'
        f'<div class="dp-ev-head"><span class="dp-ev-title">变更文件树</span>{summary_line}</div>'
        f'<div class="dp-tree">{body}</div></div>'
    )


def _render_waves(tickets: list[dict], critical: set[str], by_item: dict, kind: str) -> str:
    grouped: dict[int, list[dict]] = {}
    for t in tickets:
        grouped.setdefault(int(t.get("wave") or 1), []).append(t)
    cols = []
    for wave in sorted(grouped):
        nodes = []
        for t in grouped[wave]:
            tid = str(t["id"])
            is_crit = tid in critical
            cls = "dp-node dp-node-crit" if is_crit else "dp-node"
            badges = []
            if t.get("kind"):
                badges.append(pill(str(t["kind"]), "info" if t["kind"] == "contract" else "neutral"))
            if is_crit:
                badges.append(pill("关键路径", "info"))
            if kind == "merge":
                ds = _lane_summary(by_item.get(tid, []))
                status_html = pill(ds["label"], ds["tone"])
            else:
                status_html = pill("HITL" if t.get("hitl") else "AFK", "warn" if t.get("hitl") else "neutral")
            tags = [f'<span class="dp-tag">{ESC(m)}</span>' for m in (t.get("modules") or ())[:3]]
            if t.get("deps"):
                tags.append(f'<span class="dp-tag">← {ESC(", ".join(str(x) for x in t["deps"]))}</span>')
            tags_html = f'<div class="dp-tags">{"".join(tags)}</div>' if tags else ""
            nodes.append(
                f'<div class="{cls}">'
                f'<div class="dp-node-top"><span class="dp-node-id">#{ESC(tid)}</span>{status_html}</div>'
                f'<div class="dp-node-title">{ESC(t.get("title") or tid)}</div>'
                f'<div class="dp-tags">{"".join(badges)}</div>'
                f"{tags_html}</div>"
            )
        cols.append(
            f'<div class="dp-wave-col">'
            f'<div class="dp-wave-head"><span>Wave {wave}</span><span>{len(grouped[wave])} 票</span></div>'
            f'{"".join(nodes)}</div>'
        )
    return f'<div class="dp-waves">{"".join(cols)}</div>'


def _parse_review_card(row: dict) -> tuple[str, list[dict], list[str], dict]:
    """解析整体审查 lane；返回 (HTML, non_blocking_findings, verification_gaps, metrics)。"""
    outcome = row.get("verdict") or row.get("state") or "Unknown"
    artifact = row.get("verdict_path") or row.get("delivery")
    data = read_json_if_file(artifact)
    findings: list[dict] = []
    gaps: list[str] = []
    totals = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    if not data:
        body = (
            f'<div class="dp-card">'
            f'<div class="dp-ev-head"><span class="dp-ev-title">整体审查</span>{pill(str(outcome), verdict_tone(outcome))}</div>'
            f'<p class="dp-muted">证据坐标：{coordinate(artifact)}</p></div>'
        )
        return body, findings, gaps, {"verdict": str(outcome), "counts": None}

    axes_html = []
    axes = data.get("axes") or {}
    for axis_name, axis in axes.items():
        if not isinstance(axis, dict):
            continue
        av = str(axis.get("verdict") or "Unknown")
        counts = axis.get("counts") or {}
        count_pills = []
        for sev in ("P0", "P1", "P2", "P3"):
            n = int(counts.get(sev) or 0)
            totals[sev] += n
            tone = "danger" if (sev in ("P0", "P1") and n) else ("warn" if (sev == "P2" and n) else "neutral")
            count_pills.append(pill(f"{sev}:{n}", tone))
        axes_html.append(
            f'<div class="dp-axis">'
            f'<span class="dp-axis-name">{ESC(axis_name.capitalize())} {pill(av, verdict_tone(av))}</span>'
            f'<span class="dp-counts">{"".join(count_pills)}</span></div>'
        )
        for f in axis.get("findings") or ():
            if isinstance(f, dict):
                findings.append({"axis": axis_name, **f})
        for g in axis.get("verification_gaps") or ():
            if g:
                gaps.append(f"[{axis_name}] {g}")
        for g in axis.get("spec_gaps") or ():
            if g:
                gaps.append(f"[spec gap] {g}")

    ocr = data.get("ocr") or {}
    cov_note = ""
    if ocr.get("reviewable_count") is not None:
        cov_note = f"审查覆盖 {ocr['reviewable_count']} 个可审文件（排除 {ocr.get('excluded_count', 0)} 个）"

    findings_html = ""
    if findings:
        rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        ordered = sorted(findings, key=lambda f: (rank.get(str(f.get("severity") or "P3").upper(), 4), str(f.get("file") or "")))

        def fmt_finding(f: dict) -> str:
            sev = str(f.get("severity") or "P3").upper()
            cls = "dp-finding" if sev in ("P0", "P1", "P2") else "dp-finding dp-finding-p3"
            tone = "danger" if sev in ("P0", "P1") else ("warn" if sev == "P2" else "neutral")
            loc = f'<code>{ESC(f["file"])}</code>' if f.get("file") else ""
            impact = f'<div class="dp-muted">{ESC(f.get("trigger_and_impact"))}</div>' if f.get("trigger_and_impact") else ""
            return (
                f'<div class="{cls}">'
                f'<div class="dp-finding-head">{pill(sev, tone)}<span>{ESC(f.get("title") or "Finding")}</span>{loc}</div>'
                f"{impact}</div>"
            )

        major = [f for f in ordered if str(f.get("severity") or "P3").upper() in ("P0", "P1", "P2")]
        minor = [f for f in ordered if str(f.get("severity") or "P3").upper() not in ("P0", "P1", "P2")]
        parts_f = []
        if major:
            parts_f.append(f'<div class="dp-findings-list">{"".join(fmt_finding(f) for f in major)}</div>')
        if minor:
            parts_f.append(
                f"<details><summary>另有 {len(minor)} 条 P3 提示</summary>"
                f'<div class="dp-findings-list">{"".join(fmt_finding(f) for f in minor)}</div></details>'
            )
        findings_html = "".join(parts_f)

    card = (
        f'<div class="dp-card">'
        f'<div class="dp-ev-head"><span class="dp-ev-title">整体审查</span>{pill(str(outcome), verdict_tone(outcome))}</div>'
        f'<div class="dp-axes">{"".join(axes_html)}</div>'
        + (f'<p class="dp-muted">{ESC(cov_note)}</p>' if cov_note else "")
        + findings_html
        + f'<details><summary>原始审查证据</summary><p class="dp-muted" style="margin-top:6px">{coordinate(artifact)}</p></details>'
        + "</div>"
    )
    return card, findings, gaps, {"verdict": str(outcome), "counts": totals}


def _parse_testing_card(row: dict) -> tuple[str, list[str], dict]:
    """解析整体检查 lane；返回 (HTML, gaps, metrics)。"""
    outcome = row.get("checks") or row.get("state") or "Unknown"
    artifact = row.get("delivery") or row.get("verdict_path")
    data = read_json_if_file(artifact)
    gaps: list[str] = []
    if not data:
        card = (
            f'<div class="dp-card">'
            f'<div class="dp-ev-head"><span class="dp-ev-title">整体检查</span>{pill(str(outcome), verdict_tone(outcome))}</div>'
            f'<p class="dp-muted">证据坐标：{coordinate(artifact)}</p></div>'
        )
        return card, gaps, {"status": str(outcome), "count": None}

    observed_lines = [line.strip() for line in str(data.get("observed") or "").splitlines() if line.strip()]
    checks = list(data.get("check") or ())
    gaps = [str(g) for g in (data.get("gaps") or ()) if g]
    rows_html = []
    if observed_lines:
        for line in observed_lines:
            log_ref = ""
            m_log = re.search(r"（(/[^）]+\.log)）\s*$", line)
            if m_log:
                log_name = Path(m_log.group(1)).name
                log_ref = f' <span class="dp-tag" title="{ESC(m_log.group(1))}">{ESC(log_name)}</span>'
                line = line[:m_log.start()].strip()
            if "→" in line:
                cmd, _, res = line.partition("→")
                cmd_s = cmd.strip()
                cmd_short = (cmd_s[:86] + "…") if len(cmd_s) > 88 else cmd_s
                rows_html.append(
                    f'<li class="dp-check-item">'
                    f'<span class="dp-check-res">{ESC(res.strip())}{log_ref}</span>'
                    f'<span class="dp-check-cmd" title="{ESC(cmd_s)}">{ESC(cmd_short)}</span></li>'
                )
            else:
                rows_html.append(f'<li class="dp-check-item"><span class="dp-check-res">{ESC(line)}{log_ref}</span></li>')
    elif checks:
        for cmd in checks:
            rows_html.append(f'<li class="dp-check-item"><span class="dp-check-cmd">{ESC(cmd)}</span></li>')

    repair_note = ""
    if int(row.get("repairs") or 0):
        repair_note = f'<p class="dp-muted" style="margin-bottom:8px">经 {ESC(row["repairs"])} 轮修复后通过（{ESC(row.get("repair_lane") or "repair")}）</p>'

    count = len(observed_lines) or len(checks)
    badge_text = f"{count} 项通过" if verdict_tone(outcome) == "ok" and count else str(outcome)
    card = (
        f'<div class="dp-card">'
        f'<div class="dp-ev-head"><span class="dp-ev-title">整体检查</span>{pill(badge_text, verdict_tone(outcome))}</div>'
        + repair_note
        + (f'<ul class="dp-checklist">{"".join(rows_html)}</ul>' if rows_html else '<p class="dp-muted">无明细</p>')
        + f'<details><summary>原始检查证据</summary><p class="dp-muted" style="margin-top:6px">{coordinate(artifact)}</p></details>'
        + "</div>"
    )
    return card, gaps, {"status": badge_text, "count": count}


def _render_test_strategy(strategy) -> str:
    if not strategy:
        return ""
    if isinstance(strategy, dict):
        labels = [
            ("level", "策略级别"),
            ("unit", "单元测试"),
            ("integration", "集成测试"),
            ("regression", "回归测试"),
            ("e2e", "端到端"),
        ]
        seen = set()
        items = []
        for k, label in labels:
            if k in strategy and strategy[k] not in (None, ""):
                seen.add(k)
                items.append(f"<dt>{ESC(label)}</dt><dd>{ESC(strategy[k])}</dd>")
        for k, v in strategy.items():
            if k not in seen and v not in (None, ""):
                val = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                items.append(f"<dt>{ESC(k)}</dt><dd>{ESC(val)}</dd>")
        inner = f'<dl class="dp-kv">{"".join(items)}</dl>' if items else '<p class="dp-muted">无</p>'
    else:
        inner = f"<p style='margin-top:8px'>{ESC(strategy)}</p>"
    level = strategy.get("level") if isinstance(strategy, dict) else None
    suffix = f" · {ESC(level)}" if level else ""
    return f'<div class="dp-card"><details><summary>测试策略{suffix}</summary>{inner}</details></div>'


def preflight_html(rows: list[dict]) -> str:
    if not rows:
        return ""
    items = []
    for r in rows:
        if r.get("ok"):
            items.append(
                f'<li class="dp-check-item"><strong>{ESC(r["task"])}</strong> · '
                f'{ESC(r["agent"])} / {ESC(r["model"])} / {ESC(r["effort"])}，'
                f'每片 ≤{ESC(r["max_turns"])} 轮，并发 ≤{ESC(r["parallel"])}</li>'
            )
        else:
            items.append(
                f'<li class="dp-check-item" style="border-left:3px solid var(--dp-danger)">'
                f'<strong>{ESC(r["task"])}</strong> · <strong>无法执行</strong>：{ESC(r.get("error"))}</li>'
            )
    return (
        '<section class="dp-section">'
        '<div class="dp-section-head"><h2 class="dp-section-title">蜂巢执行预检</h2></div>'
        f'<div class="dp-card"><ul class="dp-checklist">{"".join(items)}</ul></div></section>'
    )


def render(
    state: dict,
    kind: str,
    preflight: str = "",
    *,
    deviations_fn: Callable[[dict], list[str]],
    evidence_fn: Callable[[dict], dict],
    plan_sha_fn: Callable[[dict], str],
    has_briefs_fn: Callable[[dict], bool],
) -> str:
    d = state["driver"]
    plan = d["plan"]
    lanes = state.get("lanes") or {}
    title = "Plan Review" if kind == "plan" else "Merge Review"
    tickets = sorted(plan["tickets"], key=lambda t: (t.get("wave", 1), str(t["id"])))
    critical = {str(x) for x in (plan.get("critical_path") or ())}
    by_item: dict[str, list[dict]] = {}
    if kind == "merge":
        for row in lanes.values():
            if row.get("role") != "map" and row.get("work_item"):
                by_item.setdefault(str(row["work_item"]), []).append(row)
    brief_evidence = evidence_fn(state) if kind == "merge" else {}
    reviewed_routes = {r["task"]: r for r in d.get("reviews", {}).get("plan", {}).get("preflight", [])}
    mrow = next((r for r in lanes.values() if r.get("role") == "map"), {})
    fp = plan_sha_fn(plan)
    spec_url = (d.get("gates") or {}).get("spec") or plan.get("spec")

    # Merge-only parsed evidence & diff
    review_cards, testing_cards = [], []
    review_findings, all_gaps = [], []
    review_metrics: dict = {"verdict": "Unknown", "counts": None}
    testing_metrics: dict = {"status": "Unknown", "count": None}
    diff_files = read_diff_files(state) if kind == "merge" else []

    if kind == "merge":
        for row in sorted(lanes.values(), key=lambda r: r["lane_id"]):
            if row.get("role") == "review":
                c, fs, gs, m = _parse_review_card(row)
                review_cards.append(c)
                review_findings.extend(fs)
                all_gaps.extend(gs)
                review_metrics = m
            elif row.get("role") == "testing":
                c, gs, m = _parse_testing_card(row)
                testing_cards.append(c)
                all_gaps.extend(gs)
                testing_metrics = m

    devs = deviations_fn(state) if kind == "merge" else []

    # Header verdict pill
    if kind == "merge":
        overall_text = review_metrics["verdict"] if review_metrics["verdict"] != "Unknown" else "待验收"
        overall_badge = pill(overall_text, verdict_tone(overall_text), large=True)
    else:
        overall_badge = pill("计划待确认" if d.get("planning_mode") != "auto" else "自动冻结快照", "info", large=True)

    eyebrow_parts = [pill(title, "info")]
    if plan.get("repo"):
        eyebrow_parts.append(pill(str(plan["repo"]), "neutral"))
    if plan.get("mmf"):
        eyebrow_parts.append(pill(str(plan["mmf"]), "neutral"))

    meta_items = [
        f'<span class="dp-meta-item">Spec {short_link(spec_url)}</span>',
        f'<span class="dp-meta-item">计划指纹 <code>{ESC(fp)}</code></span>',
    ]
    if mrow.get("branch"):
        meta_items.append(f'<span class="dp-meta-item">分支 <code>{ESC(mrow["branch"])}</code></span>')
    if kind == "merge" and state.get("integration_head"):
        meta_items.append(
            f'<span class="dp-meta-item">集成 HEAD <code title="{ESC(state["integration_head"])}">'
            f'{ESC(short_sha(state["integration_head"]))}</code></span>'
        )

    # KPI strip
    wave_count = len({int(t.get("wave") or 1) for t in tickets})
    crit_str = " → ".join(str(x) for x in (plan.get("critical_path") or ())) or "Unknown"
    if kind == "merge":
        done_count = sum(1 for t in tickets if _lane_summary(by_item.get(str(t["id"]), []))["tone"] == "ok")
        counts = review_metrics.get("counts")
        rev_sub = (
            f'P0:{counts["P0"]} P1:{counts["P1"]} P2:{counts["P2"]} P3:{counts["P3"]}'
            if counts else "查看审查证据"
        )
        if diff_files:
            tot_a = sum(f["added"] for f in diff_files)
            tot_d = sum(f["deleted"] for f in diff_files)
            scope_kpi = (
                f'<div class="dp-kpi"><span class="dp-kpi-label">变更范围</span>'
                f'<span class="dp-kpi-val">{len(diff_files)} 文件</span>'
                f'<span class="dp-kpi-sub dp-mono"><span class="dp-add">+{tot_a}</span> '
                f'<span class="dp-del">-{tot_d}</span></span></div>'
            )
        else:
            scope_kpi = (
                f'<div class="dp-kpi"><span class="dp-kpi-label">自动偏差</span>'
                f'<span class="dp-kpi-val">{len(devs)} 项</span>'
                f'<span class="dp-kpi-sub">关键路径 {ESC(crit_str)}</span></div>'
            )
        kpis_html = (
            '<div class="dp-kpis">'
            f'<div class="dp-kpi"><span class="dp-kpi-label">计划交付</span>'
            f'<span class="dp-kpi-val">{done_count}/{len(tickets)} 票</span>'
            f'<span class="dp-kpi-sub">{wave_count} 波 · {ESC(crit_str)}</span></div>'
            f'<div class="dp-kpi"><span class="dp-kpi-label">整体审查</span>'
            f'<span class="dp-kpi-val">{ESC(review_metrics["verdict"])}</span>'
            f'<span class="dp-kpi-sub dp-mono">{ESC(rev_sub)}</span></div>'
            f'<div class="dp-kpi"><span class="dp-kpi-label">整体检查</span>'
            f'<span class="dp-kpi-val">{ESC(testing_metrics["status"])}</span>'
            f'<span class="dp-kpi-sub">缺口 {len(all_gaps)} 项</span></div>'
            f"{scope_kpi}</div>"
        )
    else:
        strat_level = (plan.get("test_strategy") or {}).get("level") if isinstance(plan.get("test_strategy"), dict) else None
        raw_risk = plan.get("risk")
        risk_val = f"{len(raw_risk)} 项" if isinstance(raw_risk, list) else str(raw_risk or "Unknown")
        kpis_html = (
            '<div class="dp-kpis">'
            f'<div class="dp-kpi"><span class="dp-kpi-label">计划票数</span>'
            f'<span class="dp-kpi-val">{len(tickets)} 张</span>'
            f'<span class="dp-kpi-sub">{wave_count} 个波次</span></div>'
            f'<div class="dp-kpi"><span class="dp-kpi-label">关键路径</span>'
            f'<span class="dp-kpi-val dp-mono">{ESC(crit_str)}</span>'
            f'<span class="dp-kpi-sub">依赖主链</span></div>'
            f'<div class="dp-kpi"><span class="dp-kpi-label">测试级别</span>'
            f'<span class="dp-kpi-val">{ESC(strat_level or "Unknown")}</span>'
            f'<span class="dp-kpi-sub">随计划冻结</span></div>'
            f'<div class="dp-kpi"><span class="dp-kpi-label">已知风险</span>'
            f'<span class="dp-kpi-val">{ESC(risk_val)}</span>'
            f'<span class="dp-kpi-sub">合并前关注</span></div>'
            "</div>"
        )

    # Plan vs Delivery table rows
    table_rows = []
    for t in tickets:
        tid = str(t["id"])
        acc = t.get("acceptance") or t.get("check_result") or "Unknown"
        sub_pills = [f'<span class="dp-tag">{ESC(t.get("task", "backend"))}</span>']
        sub_pills.append(f'<span class="dp-tag">{"HITL" if t.get("hitl") else "AFK"}</span>')
        if t.get("kind"):
            sub_pills.append(f'<span class="dp-tag">{ESC(t["kind"])}</span>')
        for sc in (t.get("scenarios") or ())[:6]:
            sub_pills.append(f'<span class="dp-tag">{ESC(sc)}</span>')

        contract_html = ""
        if has_briefs_fn(t):
            details = json.dumps({"briefs": t["briefs"], "scenario_check": t.get("scenario_check")}, ensure_ascii=False, indent=2)
            contract_html = f"<details><summary>派发合同与整票场景</summary><pre>{ESC(details)}</pre></details>"

        actual_td = ""
        if kind == "merge":
            ds = _lane_summary(by_item.get(tid, []))
            cell_parts = [pill(ds["label"], ds["tone"])]
            if ds["commit"]:
                cell_parts.append(
                    f'<span class="dp-muted">提交 <code title="{ESC(ds["commit"])}">{ESC(short_sha(ds["commit"]))}</code></span>'
                )
            if ds["model"]:
                cell_parts.append(f'<span class="dp-muted dp-mono">{ESC(ds["model"])}</span>')
            if ds["trace"]:
                cell_parts.append(f'<span class="dp-muted dp-mono">{ESC(ds["trace"])}</span>')
            if ds["drift"]:  # ADR-0028：越出合同可写范围的文件，人审时看一眼
                cell_parts.append(f'<div class="dp-slice">{pill("超出合同范围", "warn")} {ESC(ds["drift"])}</div>')
            if tid in brief_evidence:
                route = reviewed_routes.get(t.get("task", "backend"), {})
                cell_parts.append(
                    f'<div class="dp-slice">审核时的路由：{ESC(route.get("model"))} / {ESC(route.get("effort"))}</div>'
                )
                for srow in brief_evidence[tid]["slices"]:
                    runs = srow["worker_reports"]
                    reported = sorted({model for run in runs for model in run.get("models", [])})
                    meta_run = ""
                    if runs:
                        elapsed = sum(r["elapsed_ms"] for r in runs) / 1000
                        outputs = [r["usage"].get("output_tokens") for r in runs]
                        tokens = sum(outputs) if all(n is not None for n in outputs) else "Unknown"
                        meta_run = f"<br><span class='dp-muted'>{len(runs)} 次执行 · {elapsed:.1f} 秒 · 输出 {tokens} token</span>"
                    cell_parts.append(
                        f'<div class="dp-slice">'
                        f'执行片 <strong>{ESC(srow["slice_id"])}</strong> · 提交 <code>{ESC(short_sha(srow["head_commit"]))}</code><br>'
                        f'启动路由：{ESC(srow["model"])} / {ESC(srow["effort"])}<br>'
                        f'Worker 回报模型：{ESC(", ".join(reported) or "Unknown")}'
                        f"{meta_run}</div>"
                    )
                proof = brief_evidence[tid]["scenario"] or {}
                status = {True: "通过", False: "失败"}.get(proof.get("ok"), "Unknown")
                cell_parts.append(
                    f"<details><summary>整票场景 · {status}</summary>"
                    f'<p class="dp-muted" style="margin-top:6px">集成 HEAD <code>{ESC(state.get("integration_head"))}</code></p>'
                    f"<pre>{ESC(proof.get('observed'))}</pre></details>"
                )
            actual_td = f'<td><div class="dp-delivery-cell">{"".join(cell_parts)}</div></td>'

        deps = ", ".join(str(x) for x in (t.get("deps") or ())) or "—"
        table_rows.append(
            f"<tr>"
            f'<td><div class="dp-ticket-title"><span class="dp-mono">#{ESC(tid)}</span> {ESC(t.get("title", ""))}</div>'
            f'<div class="dp-ticket-sub">{"".join(sub_pills)}</div>{contract_html}</td>'
            f'<td class="dp-mono">W{ESC(t.get("wave", 1))}<br><span class="dp-muted">依赖 {ESC(deps)}</span></td>'
            f"<td>{ESC(acc)}</td>"
            f"{actual_td}</tr>"
        )

    # Sections assembly
    sections: list[str] = [
        f'<header class="dp-head">'
        f'<div class="dp-head-main"><div class="dp-eyebrow">{"".join(eyebrow_parts)}</div>'
        f'<h1 class="dp-title">{ESC(d.get("map"))}</h1>'
        f'<div class="dp-meta">{"".join(meta_items)}</div></div>'
        f'<div class="dp-head-badge">{overall_badge}</div></header>',
        kpis_html,
    ]

    # 1. Summary
    summary_parts = []
    if plan.get("recommendation"):
        summary_parts.append(f'<div class="dp-callout">{ESC(plan["recommendation"])}</div>')
    summary_parts.append(_render_waves(tickets, critical, by_item, kind))
    if kind == "merge" and diff_files:
        summary_parts.append(_render_diff_tree(diff_files))
    sections.append(
        '<section class="dp-section">'
        f'<div class="dp-section-head"><h2 class="dp-section-title">Summary · 执行蓝图与变更</h2>'
        f'<span class="dp-muted">关键路径 {ESC(crit_str)}</span></div>'
        f'{"".join(summary_parts)}</section>'
    )

    # 2. Evidence (Merge Review)
    if kind == "merge":
        ev_cards = [*review_cards, *testing_cards]
        if not ev_cards:
            ev_cards = ['<div class="dp-card"><p class="dp-muted">暂无整体验收证据（Unknown）</p></div>']
        sections.append(
            '<section class="dp-section">'
            '<div class="dp-section-head"><h2 class="dp-section-title">Evidence · 验收证据</h2></div>'
            f'<div class="dp-ev-grid">{"".join(ev_cards)}</div></section>'
        )

    # 3. Merge Danger (Risks, Gaps, Deviations)
    danger_cards = []
    raw_risk = plan.get("risk")
    risk_list = raw_risk if isinstance(raw_risk, list) else ([raw_risk] if isinstance(raw_risk, str) and raw_risk not in ("low", "medium", "high") else [])
    unknowns = plan.get("production_unknowns") if isinstance(plan.get("production_unknowns"), list) else []
    if risk_list or unknowns or all_gaps:
        items = []
        for g in all_gaps:
            items.append(f"<li>{pill('验证缺口', 'warn')} {ESC(g)}</li>")
        for r in risk_list:
            items.append(f"<li>{ESC(r)}</li>")
        for u in unknowns:
            items.append(f"<li>{pill('生产未知', 'neutral')} {ESC(u)}</li>")
        risk_heading = "风险与验证缺口" if all_gaps else "已知风险"
        danger_cards.append(
            f'<div class="dp-card"><div class="dp-subhead">{risk_heading}</div>'
            f'<ul class="dp-list">{"".join(items)}</ul></div>'
        )
    if kind == "merge":
        dev_body = (
            f'<ul class="dp-list">{"".join(f"<li>{ESC(x)}</li>" for x in devs)}</ul>'
            if devs else '<p class="dp-muted" style="margin-top:6px">无自动偏差</p>'
        )
        danger_cards.append(
            f'<div class="dp-card"><div class="dp-subhead">自动处理的偏差 {pill(str(len(devs)), "warn" if devs else "ok")}</div>'
            f"{dev_body}</div>"
        )
    if danger_cards:
        sections.append(
            '<section class="dp-section">'
            f'<div class="dp-section-head"><h2 class="dp-section-title">{"Merge Danger · 风险与偏差" if kind == "merge" else "风险提示"}</h2></div>'
            f'<div class="dp-danger-grid">{"".join(danger_cards)}</div></section>'
        )

    # 4. Plan Decisions
    decisions = [*plan.get("decisions", []), *d.get("planning_decisions", [])]
    if decisions:
        dec_items = [
            f'<li><strong>{ESC(item["change"])}</strong><div class="dp-muted">{ESC(item["reason"])}</div>'
            f'<div class="dp-muted">{" · ".join(coordinate(ref) for ref in item["evidence"])}</div></li>'
            for item in decisions
        ]
        sections.append(
            '<section class="dp-section">'
            '<div class="dp-section-head"><h2 class="dp-section-title">计划调整记录</h2></div>'
            f'<div class="dp-card"><ol class="dp-list">{"".join(dec_items)}</ol></div></section>'
        )

    # 5. Plan vs Delivery
    thead = "<thead><tr><th>票</th><th>波次 / 依赖</th><th>计划验收</th>" + ("<th>实际交付</th>" if kind == "merge" else "") + "</tr></thead>"
    sections.append(
        '<section class="dp-section">'
        '<div class="dp-section-head"><h2 class="dp-section-title">计划与交付</h2></div>'
        f'<div class="dp-scroll"><table>{thead}<tbody>{"".join(table_rows)}</tbody></table></div></section>'
    )

    # 6. Test Strategy & Preflight
    strat_html = _render_test_strategy(plan.get("test_strategy"))
    if strat_html:
        sections.append(strat_html)
    if kind != "merge" and preflight:
        sections.append(preflight)

    # 7. Decision footer
    if kind == "merge":
        footer_text = "回复“通过”授权 push、建 PR、等 CI 并按分支合同合入收尾。"
    elif d.get("planning_mode") == "auto":
        footer_text = "计划检查与蜂巢预检通过后自动冻结。合入授权在最终验收时确认。"
    else:
        footer_text = "回复“通过”授予 Autonomy Grant。"
    sections.append(f'<footer class="dp-footer"><span>{ESC(footer_text)}</span></footer>')

    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{title} · {ESC(d.get('map'))}</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{CSS}</style></head><body>"
        f'<main class="dp-page">{"".join(sections)}</main>'
        "</body></html>\n"
    )

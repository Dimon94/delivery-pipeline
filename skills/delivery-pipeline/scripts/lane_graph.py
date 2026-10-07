#!/usr/bin/env python3
"""渲染全局 lane 静态页（ADR-0014 修订版）。

只读：递归扫描一个或多个 registry root 下的 registry-*.md / lane-registry.md
（transport-neutral 共享 lane registry；lane-registry.md 为单文件多块），
按 项目 → 地图 → lane 三级聚合。依赖边：tracker work item 取 `Blocked by`（GitHub 走 gh，
一次一仓；GitLab 认 ~/.config/lane-graph/gitlab.json（私有文件，不入库）声明的 keychain 服务、
环境变量 GITLAB_TOKEN/GITLAB_PRIVATE_TOKEN、host 直连/本地隧道双路由，再退 glab 与匿名 API）；
本地 .scratch work item 直接读文件（无需网络）。tracker 不可用或 --no-tracker 时标 Unknown。
输出单一自包含 HTML（无外部资源，file:// 可开，收藏一个 URL 即可；重新生成覆盖同一路径即刷新）。
渲染是派生物，不是状态。

用法：
  lane_graph.py --registry-root DIR [DIR...] [--out PATH] [--no-tracker] [--edges-json FILE]
                [--gitlab-config PATH]
  lane_graph.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

STATE_GROUP = {
    "integrated": "done", "consumed": "done", "closed": "done",
    "created": "active", "running": "active", "awaiting_human": "active",
    "cleanup_in_progress": "active", "rebase_in_progress": "active",
    "terminal": "review",
    "blocked": "problem", "setup_blocked": "problem",
    "integration_conflict": "problem", "integration_checks_failed": "problem",
    "path_conflict": "problem", "close_pending": "problem",
    "push_failed": "problem", "test_decision_paused": "problem",
    "stale": "void", "superseded": "void",
}
GROUP_LABEL = {"done": "已完成", "active": "进行中", "review": "待 fan-in",
               "problem": "受阻", "void": "作废/过期", "unknown": "Unknown"}

GH_ISSUE_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)/issues/(\d+)")
GITLAB_ISSUE_RE = re.compile(r"https?://([^/]+)/(.+?)/-/(?:issues|work_items)/(\d+)")
MAP_BRANCH_RE = re.compile(r"feature/map-(\d+)")
BLOCKED_BY_RE = re.compile(r"Blocked by:\s*((?:#?\d+[\s,]*)+)")
KEY_RE = re.compile(r"^([a-z_]+):\s*(.*)$")


BLOCK_RE = re.compile(r"<!-- wayfinder-lane-registry:v2 -->\s*```yaml\n(.*?)```", re.DOTALL)
REGISTRY_GLOBS = ("registry-*.md", "lane-registry.md")


def parse_registry_file(path: Path) -> list[dict]:
    """提取一个文件里的全部 lane yaml 块（lane-registry.md 单文件多块，registry-*.md 单块）。
    跳过合同文档里的占位示例块（work_item 含 <placeholder>）。"""
    text = path.read_text(encoding="utf-8")
    rows: list[dict] = []
    for m in BLOCK_RE.finditer(text):
        row: dict = {"_file": str(path)}
        for line in m.group(1).splitlines():
            if line[:1] in (" ", "\t"):
                continue
            km = KEY_RE.match(line)
            if km:
                v = km.group(2).strip()
                row[km.group(1)] = None if v in ("", "none") else v
        if row.get("lane_id") and "<" not in (row.get("work_item") or "<"):
            rows.append(row)
    return rows


def local_ref(work_item: str | None):
    """本地 .scratch work_item 路径 → (project, map_dir, stem, Path)；非本地路径返回 None。"""
    if not work_item or not work_item.startswith("/"):
        return None
    p = Path(work_item)
    parts = p.parts
    if ".scratch" in parts:
        i = parts.index(".scratch")
        project = parts[i - 1] if i else p.parent.name
        map_dir = parts[i + 1] if i + 1 < len(parts) else "ungrouped"
    else:
        project, map_dir = p.parent.name, "ungrouped"
    return project, map_dir, p.stem, p


STATUS_RE = re.compile(r"^Status:\s*(.+)$", re.MULTILINE)
LABEL_RE = re.compile(r"^Label:\s*(.+)$", re.MULTILINE)


def read_local_issue(path: Path) -> dict | None:
    """本地 .scratch issue 文件 → 与 tracker info 同构（标题/正文/状态/Blocked by），读不到 None。
    deps 保留原文写法（如 '01'），由 build 归一成同项目 lane 的完整 stem。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^# (.+)$", text, re.MULTILINE)
    sm = STATUS_RE.search(text)
    lm = LABEL_RE.search(text)
    bm = BLOCKED_BY_RE.search(text)
    try:
        updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        updated = "Unknown"
    info = _info(path.stem, m.group(1).strip() if m else None, text,
                 sm.group(1).strip() if sm else None,
                 [x.strip() for x in lm.group(1).split(",") if x.strip()] if lm else [],
                 f"file://{path}", updated)
    info["deps"] = [d.strip() for d in bm.group(1).split(",") if d.strip()] if bm else []
    return info


def issue_ref(url: str | None) -> tuple[str, str, str] | None:
    """work_item URL -> (kind, project_key, number)。
    GitHub: ("gh", "owner/repo", n)；GitLab(含自建): ("gl", "host:group/proj", n)。"""
    if not url:
        return None
    m = GH_ISSUE_RE.search(url)
    if m:
        return "gh", m.group(1), m.group(2)
    m = GITLAB_ISSUE_RE.search(url)
    if m:
        return "gl", f"{m.group(1)}:{m.group(2)}", m.group(3)
    return None


def _info(number: str, title, body, state, labels, url, updated_at, comments=None) -> dict:
    m = BLOCKED_BY_RE.search(body or "")
    return {"title": title, "body": body or "", "state": state,
            "labels": labels or [], "url": url,
            "updated_at": (updated_at or "")[:19],
            "comments": comments or [],
            "deps": re.findall(r"#?(\d+)", m.group(1)) if m else []}


def fetch_github_issues(repo: str) -> dict[str, dict] | None:
    """一仓一次 gh 调用，拿全部 issue 的正文/评论与 Blocked by 边；失败返回 None（Unknown）。"""
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--repo", repo, "--state", "all",
             "--limit", "1000", "--json", "number,title,body,state,labels,url,updatedAt,comments"],
            check=True, capture_output=True, text=True, timeout=90)
        raw = json.loads(out.stdout)
    except Exception:
        return None
    return {str(i["number"]): _info(
                str(i["number"]), i.get("title"), i.get("body"), i.get("state"),
                [l.get("name") for l in i.get("labels") or []], i.get("url"), i.get("updatedAt"),
                [{"author": (c.get("author") or {}).get("login"),
                  "body": c.get("body") or "",
                  "updated_at": (c.get("updatedAt") or "")[:19]}
                 for c in i.get("comments") or []])
            for i in raw}


def fetch_gitlab_issues(key: str, detail_numbers: set[str] | None = None,
                        cfg: dict | None = None) -> dict[str, dict] | None:
    """key = host:group/proj。凭证链：环境变量 GITLAB_TOKEN/GITLAB_PRIVATE_TOKEN →
    私有 config 声明的 keychain 服务记录 → glab → 匿名 API；host 直连 + config 声明的
    本地隧道双路由（CA 由 config ca_file 指定，默认 -k）。失败 None（Unknown）。
    评论按 lane 实际出现的 issue 逐个补拉，不拉全仓。"""
    cfg = cfg or {}
    host, path = key.split(":", 1)
    enc = urllib.parse.quote(path, safe="")
    base = f"projects/{enc}/issues"
    endpoint = f"{base}?state=all&per_page=100"
    out = _gitlab_list(endpoint, host, cfg)
    if out is None:
        return None
    info = {str(i["iid"]): _info(str(i["iid"]), i.get("title"), i.get("description"),
                                  i.get("state"), i.get("labels"), i.get("web_url"),
                                  i.get("updated_at"))
            for i in out}
    for num in detail_numbers or set():
        if num in info:
            continue  # 列表分页未覆盖的老 issue 单独补拉
        one = _gitlab_list(f"{base}/{num}", host, cfg, single=True)
        if isinstance(one, dict) and one.get("iid"):
            info[num] = _info(str(one["iid"]), one.get("title"), one.get("description"),
                              one.get("state"), one.get("labels"), one.get("web_url"),
                              one.get("updated_at"))
    for num in detail_numbers or set():
        if num not in info:
            continue
        notes = _gitlab_list(f"{base}/{num}/notes", host, cfg)
        if isinstance(notes, list):
            info[num]["comments"] = [
                {"author": (n.get("author") or {}).get("username"),
                 "body": n.get("body") or "",
                 "updated_at": (n.get("updated_at") or "")[:19]}
                for n in notes if not n.get("system")]
    return info


def _keychain_token(cfg: dict) -> str | None:
    """macOS keychain 读取配置声明的服务记录；服务名/账号只来自私有 config，不硬编码。"""
    kc = cfg.get("keychain") or {}
    if sys.platform != "darwin" or not kc.get("service"):
        return None
    for account in kc.get("accounts") or []:
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-a", account,
                 "-s", kc["service"], "-w"],
                check=True, capture_output=True, text=True, timeout=15)
            token = r.stdout.strip()
            if token:
                return token
        except Exception:
            continue
    return None


def _gitlab_list(endpoint: str, host: str, cfg: dict, single: bool = False):
    """认证拉取 GitLab endpoint，按私有 config 声明的 host 规则访问。
    single=False 返回分页合并的 list；single=True 返回单个 dict。失败 None。
    config 结构（不入库，见 ADR-0014 凭据注）：
      {"hosts": {host: {"ca_file": p, "stcp_port": n}},
       "keychain": {"service": name, "accounts": [...]}}"""
    hc = (cfg.get("hosts") or {}).get(host) or {}
    token = (os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_PRIVATE_TOKEN")
             or _keychain_token(cfg))
    ca_file = hc.get("ca_file") or os.environ.get("GITLAB_CA_FILE")
    ca_args = ["--cacert", os.path.expanduser(ca_file)] if ca_file and os.path.isfile(
        os.path.expanduser(ca_file)) else ["-k"]
    headers = ["-H", f"PRIVATE-TOKEN: {token}"] if token else []
    merged: list = []
    if token:
        routes = [([], f"https://{host}/api/v4")]
        if hc.get("stcp_port"):
            routes.append(
                (["--resolve", f"{host}:{hc['stcp_port']}:127.0.0.1"],
                 f"https://{host}:{hc['stcp_port']}/api/v4"))
        for base_args, url_base in routes:
            if single:
                try:
                    r = subprocess.run(
                        ["curl", "-sf", "--noproxy", "*", "--max-time", "30",
                         *ca_args, *headers, f"{url_base}/{endpoint}"],
                        check=True, capture_output=True, text=True)
                    obj = json.loads(r.stdout)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    continue
            ok, page, route_items = True, 1, []
            while ok and page <= 5:
                try:
                    r = subprocess.run(
                        ["curl", "-sf", "--noproxy", "*", "--max-time", "30",
                         *ca_args, *headers,
                         f"{url_base}/{endpoint}&page={page}" if "?" in endpoint
                         else f"{url_base}/{endpoint}?page={page}"],
                        check=True, capture_output=True, text=True)
                    items = json.loads(r.stdout)
                    if not isinstance(items, list):
                        break
                    route_items.extend(items)
                    page += 1 if items else 99
                except Exception:
                    ok = False
            if route_items:
                merged.extend(route_items)
                break
        if merged:
            return merged
    # glab 或匿名 fallback
    for cmd in (
        ["glab", "api", "--hostname", host, "--paginate", endpoint],
        ["curl", "-sf", "--max-time", "30", f"https://{host}/api/v4/{endpoint}"],
    ):
        try:
            r = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=90)
            raw = json.loads(r.stdout)
            if isinstance(raw, list):
                return raw
        except Exception:
            continue
    return None


def fetch_issues(kind: str, key: str, detail_numbers: set[str],
                 cfg: dict | None = None) -> dict[str, dict] | None:
    if kind == "gh":
        return fetch_github_issues(key)
    return fetch_gitlab_issues(key, detail_numbers, cfg)


def normalize_override(raw: dict) -> dict[str, dict[str, dict]]:
    """--edges-json 两种形态兼容：{repo: {n: [deps...]}} 或 {repo: {n: {deps,title,body,...}}}。"""
    out: dict[str, dict[str, dict]] = {}
    for key, issues in raw.items():
        out[key] = {}
        for num, val in issues.items():
            if isinstance(val, list):
                out[key][str(num)] = _info(str(num), None, "", None, [], None, "") | {
                    "deps": [str(d) for d in val]}
            else:
                v = _info(str(num), val.get("title"), val.get("body"), val.get("state"),
                          val.get("labels"), val.get("url"), val.get("updated_at"),
                          val.get("comments"))
                v["deps"] = [str(d) for d in val.get("deps", [])]
                out[key][str(num)] = v
    return out


def topo_layers(lanes: list[dict], edges: dict[str, list[str]]) -> tuple[list[list[dict]], list[dict]]:
    """按 in-map 依赖边分层（Kahn）；环上节点进 Unknown 层放最后。
    返回 (connected_layers, isolated)：无任何依赖关系的 lane 不参与 DAG 布局，单列返回。"""
    by_issue = {l["issue"]: l for l in lanes if l.get("issue")}
    deps = {n: [d for d in edges.get(n, []) if d in by_issue] for n in by_issue}
    referenced = {d for ds in deps.values() for d in ds}
    connected = {n for n in by_issue if deps[n] or n in referenced}
    layers: list[list[dict]] = []
    placed: set[str] = set()
    remaining = set(connected)
    while remaining:
        ready = [n for n in sorted(remaining) if all(d in placed for d in deps[n])]
        if not ready:
            layers.append([by_issue[n] | {"lane_id": f"{by_issue[n]['lane_id']} (环/Unknown)"}
                           for n in sorted(remaining)])
            break
        layers.append([by_issue[n] for n in ready])
        placed.update(ready)
        remaining -= set(ready)
    isolated = [l for l in lanes if not l.get("issue") or l["issue"] not in connected]
    return layers, isolated


def build(roots: list[Path], edges_override: dict[str, dict[str, dict]] | None,
          no_tracker: bool, cfg: dict | None = None) -> dict:
    projects: dict[str, dict] = {}
    files = {p for root in roots for g in REGISTRY_GLOBS for p in root.rglob(g)}
    rows = [row for p in sorted(files) for row in parse_registry_file(p)]
    seen: dict[str, str] = {}  # project_key -> kind
    for row in rows:
        ref = issue_ref(row.get("work_item"))
        if ref:
            seen[ref[1]] = ref[0]

    maps_by_key: dict[tuple[str, str], dict] = {}
    lanes: list[dict] = []
    for row in rows:
        ref = issue_ref(row.get("work_item"))
        lref = None if ref else local_ref(row.get("work_item"))
        if not ref and not lref:
            continue
        if ref:
            project, issue_id = ref[1], ref[2]
        else:
            project, issue_id = lref[0], lref[2]
        branch_m = MAP_BRANCH_RE.search(row.get("integration_branch") or "")
        if lref:
            map_key = lref[1]
        elif branch_m:
            map_key = branch_m.group(1)
        else:
            map_key = issue_id if row.get("role") == "map" else None
        proj = projects.setdefault(project, {"name": project, "maps": {}})
        if row.get("role") == "map":
            key = map_key or row.get("lane_id") or "unknown-map"
            mp = proj["maps"].setdefault(key, {"key": key, "lanes": []})
            mp.update({"title": key if lref else f"map #{issue_id}",
                       "url": row.get("work_item"), "state": row.get("state") or "Unknown"})
            maps_by_key[(project, key)] = mp
            continue
        lane = {"lane_id": row.get("lane_id") or "Unknown",
                "issue": issue_id,
                "url": f"file://{lref[3]}" if lref else row.get("work_item"),
                "role": row.get("role") or "Unknown",
                "state": row.get("state") or "Unknown",
                "group": STATE_GROUP.get(row.get("state") or "Unknown", "unknown"),
                "agent": row.get("agent"), "model": row.get("model"),
                "effort": row.get("effort"), "runtime": row.get("runtime"),
                "updated_at": (row.get("updated_at") or "")[:19],
                "_project": project, "_map": map_key,
                "_local": str(lref[3]) if lref else None}
        lanes.append(lane)
        mp = proj["maps"].setdefault(map_key or "ungrouped",
                                     {"key": map_key or "ungrouped",
                                      "title": f"map #{map_key}" if map_key else "未分组",
                                      "url": None, "state": None, "lanes": []})
        maps_by_key[(project, map_key or "ungrouped")] = mp

    for lane in lanes:
        mp = maps_by_key.get((lane.pop("_project"), lane.pop("_map") or "ungrouped"))
        if mp:
            mp["lanes"].append(lane)

    lane_issues: dict[str, set[str]] = defaultdict(set)
    for proj in projects.values():
        for mp in proj["maps"].values():
            for lane in mp["lanes"]:
                if lane.get("issue"):
                    lane_issues[proj["name"]].add(lane["issue"])
    issues_by_project: dict[str, dict[str, dict] | None] = {}
    for key, kind in seen.items():
        if edges_override and key in edges_override:
            issues_by_project[key] = edges_override[key]
        elif no_tracker:
            issues_by_project[key] = None
        else:
            issues_by_project[key] = fetch_issues(kind, key, lane_issues.get(key, set()), cfg)

    out_projects = []
    for proj in sorted(projects.values(), key=lambda p: p["name"]):
        info = issues_by_project.get(proj["name"])
        nums = {l["issue"] for mp in proj["maps"].values() for l in mp["lanes"] if l.get("issue")}

        def norm(deps):  # 本地简写 "01" → "01-foo" 全 stem；tracker 精确号原样通过
            return [n for d in deps for n in sorted(nums) if n == d or n.startswith(d + "-")]

        maps = []
        for mp in sorted(proj["maps"].values(), key=lambda m: m["key"]):
            local_any = False
            for lane in mp["lanes"]:
                lp = lane.pop("_local", None)
                if lp:
                    local_any = True
                    lane["info"] = read_local_issue(Path(lp))
                elif info and lane.get("issue") in info:
                    src = info[lane["issue"]]
                    lane["info"] = {k: src.get(k) for k in
                                    ("title", "body", "state", "labels", "url", "updated_at",
                                     "comments")}
            deps_map = {k: norm(v["deps"]) for k, v in info.items()} if info else {}
            for lane in mp["lanes"]:
                li = lane.get("info")
                if lane.get("issue") and li and li.get("deps"):
                    deps_map[lane["issue"]] = norm(li["deps"])
            layers, isolated = topo_layers(mp["lanes"], deps_map)
            counts: dict[str, int] = defaultdict(int)
            for l in mp["lanes"]:
                counts[STATE_GROUP.get(l["state"], "unknown")] += 1
            has_edges = info is not None or local_any
            maps.append({**mp, "lanes": mp["lanes"], "layers": layers,
                         "isolated": isolated,
                         "counts": dict(counts), "edges": deps_map if has_edges else None,
                         "edges_unknown": not has_edges})
        out_projects.append({"name": proj["name"], "maps": maps})
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "registry_root": ", ".join(str(r) for r in roots), "projects": out_projects}


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Delivery Pipeline Lane Graph</title>
<style>
:root{--done:#2da44e;--active:#bf8700;--review:#0969da;--problem:#cf222e;--void:#6e7781;--unknown:#8c959f}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,"PingFang SC",sans-serif;background:#f6f8fa;color:#1f2328;overflow:hidden}
header{padding:8px 16px;background:#0d1117;color:#e6edf3;font-size:13px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
header b{font-size:15px;margin-right:6px}
header button{background:#21262d;color:#e6edf3;border:1px solid #444c56;border-radius:6px;padding:3px 10px;cursor:pointer;font-size:12px}
header button:hover{background:#30363d}
header button.off{opacity:.45}
#meta{margin-left:auto;color:#8b949e}
.wrap{display:flex;height:calc(100vh - 40px)}
.col{overflow-y:auto;background:#fff;flex-shrink:0}
.projects{width:230px;border-right:1px solid #d0d7de}
.maps{width:290px;border-right:1px solid #d0d7de}
.col.hidden{display:none}
h3{margin:0;padding:10px 12px;font-size:12px;color:#57606a;letter-spacing:.05em}
.item{padding:8px 12px;cursor:pointer;border-left:3px solid transparent}
.item:hover{background:#f0f3f6}.item.sel{border-left-color:#0969da;background:#ddf4ff}
.item .sub{font-size:12px;color:#57606a}
.badge{display:inline-block;min-width:18px;padding:0 5px;margin-left:4px;border-radius:9px;color:#fff;font-size:11px;text-align:center}
.detail{flex:1;position:relative;overflow:hidden;background:#f6f8fa;cursor:grab;touch-action:none}
.detail.grabbing{cursor:grabbing}
.panel{position:fixed;top:40px;right:0;bottom:0;width:min(460px,94vw);background:#fff;
box-shadow:-6px 0 20px rgba(0,0,0,.18);transform:translateX(105%);transition:transform .18s ease;
z-index:50;overflow-y:auto;padding:14px 16px}
.panel.open{transform:none}
.panel h3{padding:6px 0;font-size:15px;text-transform:none;letter-spacing:0}
.panel .sub{font-size:12px;color:#57606a}
.ibody{white-space:pre-wrap;font-size:13px;margin-top:8px;word-break:break-word}
.cmt{border-top:1px solid #eaecef;margin-top:10px;padding-top:8px}
.world{position:absolute;top:0;left:0;transform-origin:0 0}
.card{position:absolute;width:230px;background:#fff;border:1px solid #d0d7de;border-left:4px solid var(--unknown);border-radius:6px;padding:8px 10px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card.done{border-left-color:var(--done)}.card.active{border-left-color:var(--active)}
.card.review{border-left-color:var(--review)}.card.problem{border-left-color:var(--problem)}
.card.void{border-left-color:var(--void);opacity:.75}
.card a{font-weight:600;color:#0969da;text-decoration:none}
.card a.ino{border-bottom:1px dashed #0969da;cursor:pointer}
.card .meta{font-size:12px;color:#57606a;margin-top:4px}
.card .deps{font-size:12px;color:#8250df;margin-top:2px}
.state{float:right;font-size:11px;padding:1px 7px;border-radius:9px;color:#fff;background:var(--unknown)}
.state.done{background:var(--done)}.state.active{background:var(--active)}
.state.review{background:var(--review)}.state.problem{background:var(--problem)}
.state.void{background:var(--void)}
.warn{position:absolute;top:10px;left:10px;z-index:10;background:#fff8c5;border:1px solid #d4a72c;padding:6px 10px;border-radius:6px;font-size:12px}
.isobox{background:rgba(255,255,255,.92);border:1px dashed #d0d7de;border-radius:8px;padding:8px 10px}
.isohead{cursor:pointer;font-size:12px;color:#57606a;user-select:none}
.isohead:before{content:"▸ "}
.isobox:not(.collapsed) .isohead:before{content:"▾ "}
.isogrid{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.isogrid .card{position:static}
.isobox.collapsed .isogrid{display:none}
.mtitle{position:absolute;bottom:10px;left:10px;z-index:10;background:rgba(255,255,255,.92);border:1px solid #d0d7de;padding:6px 10px;border-radius:6px;font-size:12px}
.empty{padding:20px}
</style></head><body>
<header><b>Lane Graph</b>
<button id="btnP" title="收起/展开项目栏">项目</button>
<button id="btnM" title="收起/展开地图栏">地图</button>
<button id="btnFit" title="缩放平移到完整图">适应视图</button>
<span id="meta"></span></header>
<div class="wrap">
  <div class="col projects" id="colP"><h3>项目</h3><div id="plist"></div></div>
  <div class="col maps" id="colM"><h3>地图</h3><div id="mlist"></div></div>
  <div class="detail" id="detail"><div class="empty"><h3>选择左侧地图</h3></div></div>
</div>
<div class="panel" id="panel">
  <button id="btnI" style="float:right;border:1px solid #d0d7de;background:#fff;border-radius:6px;cursor:pointer">关闭 Esc</button>
  <div id="icontent"></div>
</div>
<script>
const DATA = __DATA__;
const GL = {done:"已完成",active:"进行中",review:"待 fan-in",problem:"受阻",void:"作废/过期",unknown:"Unknown"};
const esc = s => String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
document.getElementById("meta").textContent =
  `生成于 ${DATA.generated_at} · registry: ${DATA.registry_root} · 重新生成此文件即刷新`;
const plist = document.getElementById("plist"), mlist = document.getElementById("mlist"),
      detail = document.getElementById("detail");
const NW=230, NH=110, GX=300, GY=170;
let selP=-1, selM=-1, scale=1, tx=0, ty=0, bbox=null;
function countsBadges(c){return Object.entries(c||{}).map(([g,n])=>
  `<span class="badge" style="background:var(--${g})" title="${GL[g]}">${n}</span>`).join("");}
function applyView(){const w=document.getElementById("world");if(w)w.style.transform=`translate(${tx}px,${ty}px) scale(${scale})`;}
function fitView(){
  if(!bbox)return;
  const dw=detail.clientWidth, dh=detail.clientHeight;
  scale=Math.min(1.5,Math.max(.15,Math.min(dw/(bbox.w+60),dh/(bbox.h+60))));
  tx=(dw-bbox.w*scale)/2-bbox.x*scale; ty=(dh-bbox.h*scale)/2-bbox.y*scale;
  applyView();
}
function renderProjects(){
  plist.innerHTML = DATA.projects.map((p,i)=>{
    const n = p.maps.reduce((a,m)=>a+m.lanes.length,0);
    return `<div class="item ${i===selP?"sel":""}" onclick="pickP(${i})">
      <div>${esc(p.name)}</div><div class="sub">${p.maps.length} 地图 · ${n} lanes</div></div>`;
  }).join("") || `<div class="item sub">registry root 下没有 registry-*.md</div>`;
}
function renderMaps(){
  if(selP<0){mlist.innerHTML="";return;}
  mlist.innerHTML = DATA.projects[selP].maps.map((m,i)=>
    `<div class="item ${i===selM?"sel":""}" onclick="pickM(${i})">
      <div>${m.url?`<a href="${esc(m.url)}" target="_blank">${esc(m.title)}</a>`:esc(m.title)}
      ${countsBadges(m.counts)}</div>
      <div class="sub">${m.state?`map 状态: ${esc(m.state)} · `:""}${m.lanes.length} lanes</div></div>`).join("");
}
function renderDetail(){
  bbox=null;
  if(selP<0||selM<0){detail.innerHTML=`<div class="empty"><h3>选择左侧地图</h3></div>`;return;}
  const m = DATA.projects[selP].maps[selM];
  const pos = {}; let maxX=0, maxY=0;
  const maxLen = Math.max(1,...m.layers.map(l=>l.length));
  m.layers.forEach((layer,li)=>{
    const off = (maxLen-layer.length)*GX/2;  // 每层水平居中，呈树形
    layer.forEach((l,ni)=>{
      const x=off+ni*GX+30, y=li*GY+30;
      pos[l.issue||l.lane_id]={x,y,l}; maxX=Math.max(maxX,x+NW); maxY=Math.max(maxY,y+NH);
    });
  });
  bbox={x:0,y:0,w:maxX,h:maxY};
  const inMap = issue => issue && pos[issue];
  let paths="";
  Object.values(pos).forEach(({x,y,l})=>{
    const deps=((l.issue&&m.edges&&m.edges[l.issue])||[]).filter(d=>inMap(d));
    deps.forEach(d=>{
      const s=pos[d], sx=s.x+NW/2, sy=s.y+NH, ex=x+NW/2, ey=y, c=Math.max(50,Math.abs(ey-sy)/2);
      paths+=`<path d="M${sx},${sy} C${sx},${sy+c} ${ex},${ey-c} ${ex},${ey}" fill="none" stroke="#8250df" stroke-width="1.5" marker-end="url(#arr)"/>`;
    });
  });
  const nodes=Object.values(pos).map(({x,y,l})=>{
    const deps=(l.issue&&m.edges&&m.edges[l.issue])||[];
    return `<div class="card ${l.group}" style="left:${x}px;top:${y}px"
      onclick="cardClick(event,'${esc(l.issue||'')}")">
      <span class="state ${l.group}">${esc(l.state)}</span>
      ${l.url?`<a class="ino" href="${esc(l.url)}" target="_blank" title="点击查看 issue 详情（中键新标签打开）"
        onclick="event.stopPropagation();cardClick(event,'${esc(l.issue)}');return false">#${esc(l.issue)}</a>`:esc(l.lane_id)}
      <span class="meta"> ${esc(l.role)}</span>
      <div class="meta">${esc(l.lane_id)} · ${esc(l.agent||"")}/${esc(l.model||"")} · ${esc(l.runtime||"")}</div>
      ${l.updated_at?`<div class="meta">${esc(l.updated_at)}</div>`:""}
      ${deps.length?`<div class="deps">⤷ Blocked by ${deps.map(d=>"#"+d).join(" ")}</div>`:""}
    </div>`;}).join("");
  // 无关联 lane 不进 DAG，收进地图底部默认收起的格子区
  const iso=(m.isolated||[]);
  const isoCards=iso.map(l=>
    `<div class="card ${l.group}"
      onclick="cardClick(event,'${esc(l.issue||'')}')">
      <span class="state ${l.group}">${esc(l.state)}</span>
      ${l.url?`<a class="ino" href="${esc(l.url)}" target="_blank" title="点击查看 issue 详情（中键新标签打开）"
        onclick="event.stopPropagation();cardClick(event,'${esc(l.issue)}');return false">#${esc(l.issue)}</a>`:esc(l.lane_id)}
      <span class="meta"> ${esc(l.role)}</span>
      <div class="meta">${esc(l.lane_id)} · ${esc(l.agent||"")}/${esc(l.model||"")} · ${esc(l.runtime||"")}</div>
    </div>`).join("");
  const isoHtml=iso.length?`<div class="isobox collapsed" id="isobox"
      style="position:absolute;top:${maxY+90}px;left:30px;max-width:${Math.max(600,maxX)}px">
    <div class="isohead" onclick="document.getElementById('isobox').classList.toggle('collapsed')">无关联 lane × ${iso.length}（不参与依赖布局，点击展开/收起）</div>
    <div class="isogrid">${isoCards}</div></div>`:"";
  detail.innerHTML =
    (m.edges_unknown?`<div class="warn">依赖边 Unknown（gh 不可用或 --no-tracker）：布局不代表真实拓扑。</div>`:"")+
    `<div class="mtitle">${esc(m.title)} ${countsBadges(m.counts)} · 点 #编号 看 issue · 拖拽平移 / 滚轮缩放</div>
     <div class="world" id="world" style="width:${maxX+60}px;height:${maxY+60+(iso.length?110:0)}px">
       <svg width="${maxX+60}" height="${maxY+60}" style="position:absolute;top:0;left:0">
         <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
           <path d="M0,0L10,5L0,10z" fill="#8250df"/></marker></defs>
         ${paths}</svg>${nodes}${isoHtml}</div>`;
  fitView();
}
let dragging=false,sx=0,sy=0,dragDist=0;
detail.addEventListener("pointerdown",e=>{
  if(e.target.closest("a"))return;
  dragging=true;dragDist=0;sx=e.clientX-tx;sy=e.clientY-ty;
  detail.classList.add("grabbing");});
// 不用 setPointerCapture：它会把 pointerup 重定向到容器，吞掉卡片的 click。
// 拖动监听挂 window，移出画布也能继续拖，click 事件不受影响。
window.addEventListener("pointermove",e=>{if(dragging){
  dragDist+=Math.abs(e.movementX)+Math.abs(e.movementY);
  tx=e.clientX-sx;ty=e.clientY-sy;applyView();}});
window.addEventListener("pointerup",()=>{dragging=false;detail.classList.remove("grabbing");});
detail.addEventListener("wheel",e=>{
  if(!document.getElementById("world"))return; e.preventDefault();
  const r=detail.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const ns=Math.min(3,Math.max(.15,scale*Math.exp(-e.deltaY*0.0012)));
  tx=mx-(mx-tx)*ns/scale; ty=my-(my-ty)*ns/scale; scale=ns; applyView();
},{passive:false});
function toggleCol(id,btn){const c=document.getElementById(id);c.classList.toggle("hidden");
  document.getElementById(btn).classList.toggle("off");}
document.getElementById("btnP").onclick=()=>toggleCol("colP","btnP");
document.getElementById("btnM").onclick=()=>toggleCol("colM","btnM");
document.getElementById("btnFit").onclick=fitView;
window.cardClick=(e,num)=>{
  if(dragDist>6)return;  // 拖拽结束落在卡片上不算点击
  if(!num||selP<0||selM<0)return;
  const m=DATA.projects[selP].maps[selM];
  const lane=m.lanes.find(l=>l.issue===num);
  const bar=document.getElementById("panel");
  bar.classList.add("open");
  const info=lane&&lane.info;
  const cmts=(info&&info.comments||[]).map(c=>`
    <div class="cmt"><div class="sub">${esc(c.author||"unknown")} · ${esc(c.updated_at||"")}</div>
    <div class="ibody">${esc(c.body||"")}</div></div>`).join("");
  document.getElementById("icontent").innerHTML = info?`
    <h3><a href="${esc(info.url||lane.url)}" target="_blank">#${esc(num)} ${esc(info.title||"")}</a></h3>
    <div class="sub">tracker 状态: ${esc(info.state||"Unknown")} · ${esc(info.updated_at||"")} · 内容在生成时快照
    · <a href="${esc(info.url||lane.url)}" target="_blank">浏览器打开</a></div>
    <div style="margin:6px 0">${(info.labels||[]).map(x=>`<span class="badge" style="background:#6e7781">${esc(x)}</span>`).join("")}</div>
    <div class="ibody">${esc(info.body||"(无正文)")}</div>${cmts}`
   :`<h3>#${esc(num)}</h3><div class="sub">内容未嵌入（生成时 tracker 不可用或已变更）。
     ${lane&&lane.url?`<a href="${esc(lane.url)}" target="_blank">浏览器打开</a>`:""}</div>`;
};
function closePanel(){document.getElementById("panel").classList.remove("open");}
document.getElementById("btnI").onclick=closePanel;
document.addEventListener("keydown",e=>{if(e.key==="Escape")closePanel();});
window.pickP=i=>{selP=i;selM=-1;closePanel();renderProjects();renderMaps();renderDetail();};
window.pickM=i=>{selM=i;closePanel();renderMaps();renderDetail();};
renderProjects();
</script></body></html>"""


def render_html(data: dict) -> str:
    # 卡片 deps 从 per-repo edges 摊到 map 上，模板零计算
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return HTML_TEMPLATE.replace("__DATA__", payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry-root", nargs="+", help="一个或多个 registry 根目录（递归扫描）")
    ap.add_argument("--out")
    ap.add_argument("--no-tracker", action="store_true")
    ap.add_argument("--edges-json", help="测试/离线注入 {repo: {issue: [dep...]}}")
    ap.add_argument("--gitlab-config",
                    help="私有 GitLab 访问配置（JSON，不入库，默认 ~/.config/lane-graph/gitlab.json）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.registry_root:
        ap.error("--registry-root 必填")
    roots = [Path(r).expanduser() for r in args.registry_root]
    cfg_path = (Path(args.gitlab_config).expanduser() if args.gitlab_config
                else Path.home() / ".config" / "lane-graph" / "gitlab.json")
    cfg = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    edges_override = normalize_override(json.loads(Path(args.edges_json).read_text())) if args.edges_json else None
    data = build(roots, edges_override, args.no_tracker, cfg)
    out = Path(args.out) if args.out else roots[0] / "lane-graph.html"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(render_html(data), encoding="utf-8")
    tmp.replace(out)
    print(f"lane graph: {out}")
    return 0


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "proj-a").mkdir()
        tpl = """<!-- wayfinder-lane-registry:v2 -->

```yaml
work_item: {work_item}
role: {role}
lane_id: {lane_id}
state: {state}
integration_branch: {branch}
agent: pi
model: test-model
effort: high
runtime: herdr-pi-pane
updated_at: 2026-09-28T10:00:00
```
"""
        # 真实格式：一个 lane-registry.md 含多个 yaml 块
        blocks = [
            tpl.format(
                work_item="https://github.com/acme/app/issues/100", role="map",
                lane_id="map-100", state="running", branch="feature/map-100"),
            tpl.format(
                work_item="https://github.com/acme/app/issues/101", role="backend",
                lane_id="lane-101", state="closed", branch="feature/map-100"),
            tpl.format(
                work_item="https://github.com/acme/app/issues/102", role="frontend",
                lane_id="lane-102", state="running", branch="feature/map-100"),
            tpl.format(
                work_item="https://github.com/acme/app/issues/103", role="backend",
                lane_id="lane-103", state="superseded", branch="feature/map-100"),
        ]
        (root / "proj-a" / "lane-registry.md").write_text("\n".join(blocks), encoding="utf-8")
        # GitLab work_items URL（自建实例）
        (root / "proj-b").mkdir()
        (root / "proj-b" / "lane-registry.md").write_text(tpl.format(
            work_item="https://gitlab.example.local/team/product/studio/-/work_items/669",
            role="backend", lane_id="map-631-issue-669", state="closed",
            branch="feature/map-631"), encoding="utf-8")
        # 本地 .scratch work_item（无 tracker，正文/Blocked by 直接读文件）
        issues_dir = root / "proj-c" / ".scratch" / "mymap" / "issues"
        issues_dir.mkdir(parents=True)
        (issues_dir / "01-foo.md").write_text(
            "# Foo 任务\nStatus: closed\nLabel: wayfinder:coding\n", encoding="utf-8")
        (issues_dir / "02-bar.md").write_text(
            "# Bar 任务\nStatus: running\nBlocked by: 01\n", encoding="utf-8")
        (issues_dir / "03-baz.md").write_text(
            "# Baz 任务\nStatus: running\n", encoding="utf-8")
        (root / "proj-c" / "lane-registry.md").write_text(
            tpl.format(work_item=str(issues_dir / "01-foo.md"), role="coding",
                       lane_id="mymap-issue-01", state="closed", branch="main") +
            tpl.format(work_item=str(issues_dir / "02-bar.md"), role="coding",
                       lane_id="mymap-issue-02", state="running", branch="main") +
            tpl.format(work_item=str(issues_dir / "03-baz.md"), role="coding",
                       lane_id="mymap-issue-03", state="running", branch="main"),
            encoding="utf-8")
        edges = normalize_override({"acme/app": {
            "102": ["101"],
            "103": {"deps": ["102"], "title": "恢复实现", "body": "正文-kill-probe",
                    "state": "closed", "labels": ["p0"],
                    "comments": [{"author": "reviewer", "body": "复审确认通过",
                                  "updated_at": "2026-09-28T11:00:00"}]}}})
        data = build([root], edges, no_tracker=True)
        assert len(data["projects"]) == 3, [p["name"] for p in data["projects"]]
        by_name = {p["name"]: p for p in data["projects"]}
        proj = by_name["acme/app"]
        glab = by_name["gitlab.example.local:team/product/studio"]
        assert glab["maps"][0]["lanes"][0]["issue"] == "669"
        lc = by_name["proj-c"]
        assert lc["maps"][0]["key"] == "mymap"
        bar = next(l for l in lc["maps"][0]["lanes"] if l["issue"] == "02-bar")
        assert bar["info"]["title"] == "Bar 任务"
        assert lc["maps"][0]["edges"] == {"02-bar": ["01-foo"]}, lc["maps"][0]["edges"]
        # 无依赖的 03-baz 收进 isolated，不进 DAG 层
        assert [len(layer) for layer in lc["maps"][0]["layers"]] == [1, 1]
        assert [l["issue"] for l in lc["maps"][0]["isolated"]] == ["03-baz"]
        mp = proj["maps"][0]
        assert mp["title"] == "map #100", mp
        assert [len(layer) for layer in mp["layers"]] == [1, 1, 1], mp["layers"]
        assert mp["counts"] == {"done": 1, "active": 1, "void": 1}, mp["counts"]
        lane103 = next(l for l in mp["lanes"] if l["issue"] == "103")
        assert lane103["info"]["body"] == "正文-kill-probe", lane103
        html = render_html(data)
        for needle in ("acme/app", "map #100", '"issue": "101"', "superseded", "lane-102",
                       "正文-kill-probe", "恢复实现", "复审确认通过", "Bar 任务", "mymap"):
            assert needle in html, needle
        # node 冒烟：DOM 桩下对全部项目/地图跑 renderDetail，防模板运行时回归
        # （曾出现声明块丢失导致 ReferenceError 而页面静默空白）。无 node 则跳过。
        node = shutil.which("node")
        if node:
            smoke = (
                'const fs=require("fs");'
                'const html=fs.readFileSync(process.argv[1],"utf8");'
                'const js=html.match(/<script>([\\s\\S]*)<\\/script>/)[1];'
                'const mkEl=()=>({innerHTML:"",classList:{add(){},remove(){},toggle(){}},'
                'style:{},addEventListener(){},set onclick(v){},get onclick(){return null},'
                'getBoundingClientRect:()=>({left:0,top:0,width:1200,height:800}),'
                'closest:()=>null});'
                'global.document={getElementById:()=>mkEl(),addEventListener(){},createElement:mkEl};'
                'global.window=global;global.addEventListener=()=>{};'
                'const test=`;let fails=0;'
                'for(let p=0;p<DATA.projects.length;p++)for(let m=0;m<DATA.projects[p].maps.length;m++){'
                'try{selP=p;selM=m;renderDetail();}catch(e){fails++;console.log("FAIL",e.message);}}'
                'console.log("fails:",fails);`;'
                'eval(js+test);')
            smoke_html = root / "smoke.html"
            smoke_html.write_text(html, encoding="utf-8")
            r = subprocess.run([node, "-e", smoke, str(smoke_html)],
                               capture_output=True, text=True, timeout=30)
            assert "fails: 0" in r.stdout, f"node smoke: {r.stdout}{r.stderr}"
        out = root / "lane-graph.html"
        out.write_text(html, encoding="utf-8")
        assert "Blocked by" in html
    print("lane_graph self-test: pass (parse, group, topo layers, counts, issue info, html)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

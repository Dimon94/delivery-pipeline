#!/usr/bin/env python3
"""编排回归指标：coordinator 会话的上下文峰值、轮询占比与亲手改代码检测。

用法：
  orchestration_metrics.py [--limit N] [--since-days D] [--json] [session.jsonl ...]
  orchestration_metrics.py self-test

不给文件时，从 pi（~/.pi/agent/sessions）、Claude Code（~/.claude/projects）与 Codex
（~/.codex/sessions）发现最近的 coordinator 会话：首条用户消息以 delivery-pipeline 壳调用开头，
且不是 lane packet。只读会话日志，不写任何文件。
"""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

ENTRY = re.compile(r'^\s*\[?(?:\$|/|/skill:)delivery-pipeline'
                   r'(?:-herdr|-orca|-codex-app|-t3code|-lody)?(?![\w-])')
PACKET = re.compile(r'Dispatch Packet|Execution Task Packet|Lane ID[:：]|LANE_DONE|你是.*(worker|lane)', re.I)
POLL_CMD = re.compile(r'herdr (agent (get|read)|pane (read|get|process)|wait)|lane-watch|lane_watch'
                      r'|(^|[\s;&|(])sleep\s|process-info|ps -axo|gh (run|pr) (watch|checks)')
POLL_TOOL = re.compile(r'^(Monitor|TaskOutput|ScheduleWakeup|BashOutput|write_stdin)$'
                       r'|t3_thread_wait|t3_background_wait|task_status|wait_agent', re.I)
EDIT_TOOL = re.compile(r'^(edit|write|multiedit|notebookedit|apply_patch|str_replace_based_edit_tool)$', re.I)
CONTROL_PATH = re.compile(r'/\.tmp/|/\.scratch/|registry|/packets?/|^/tmp/|^/private/|/\.(claude|codex|pi|t3|config)/'
                          r'|skills/delivery-pipeline')
FANIN_CMD = re.compile(r'\bgit\b[^|;&\n]*?[\s\'",](cherry-pick|am|apply|merge)(?![\w-])')
PATCH_PATH = re.compile(r'^\*\*\* (?:Add|Update|Delete) File: (.+)$', re.M)


def _text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(_text(x) for x in c)
    if isinstance(c, dict):
        return str(c.get('text') or '')
    return ''


def _ctx(input_=0, cache_read=0, cache_write=0):
    return (input_ or 0) + (cache_read or 0) + (cache_write or 0)


def parse(path):
    """归一成 {runtime, prompt, contexts[], calls[(tool, args_dict_or_str)]}。"""
    s = {'runtime': None, 'prompt': '', 'contexts': [], 'calls': []}
    with open(path, errors='replace') as h:
        for line in h:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get('type')
            if t == 'session' or (t == 'message' and isinstance(d.get('message'), dict)):
                s['runtime'] = s['runtime'] or 'pi'
                m = d.get('message') or {}
                if m.get('role') == 'user' and not s['prompt']:
                    s['prompt'] = _text(m.get('content'))
                if m.get('role') == 'assistant':
                    u = m.get('usage') or {}
                    s['contexts'].append(_ctx(u.get('input'), u.get('cacheRead'), u.get('cacheWrite')))
                    for c in m.get('content') or []:
                        if isinstance(c, dict) and c.get('type') == 'toolCall':
                            s['calls'].append((c.get('name') or '', c.get('arguments') or {}))
            elif t in ('user', 'assistant') and isinstance(d.get('message'), dict):
                s['runtime'] = s['runtime'] or 'claude'
                m = d['message']
                if t == 'user' and not s['prompt'] and not d.get('isMeta'):
                    txt = _text(m.get('content'))
                    if txt and not txt.lstrip().startswith('<'):
                        s['prompt'] = txt
                if t == 'assistant':
                    u = m.get('usage') or {}
                    if u:
                        s['contexts'].append(_ctx(u.get('input_tokens'), u.get('cache_read_input_tokens'),
                                                  u.get('cache_creation_input_tokens')))
                    for c in m.get('content') or []:
                        if isinstance(c, dict) and c.get('type') == 'tool_use':
                            s['calls'].append((c.get('name') or '', c.get('input') or {}))
            elif t in ('session_meta', 'response_item', 'event_msg'):
                s['runtime'] = s['runtime'] or 'codex'
                p = d.get('payload') or {}
                pt = p.get('type')
                if pt == 'message' and p.get('role') == 'user' and not s['prompt']:
                    txt = _text(p.get('content'))
                    if txt and not txt.lstrip().startswith('<') and not txt.startswith('# AGENTS'):
                        s['prompt'] = txt
                elif pt == 'token_count' and (p.get('info') or {}).get('last_token_usage'):
                    u = p['info']['last_token_usage']
                    # Codex 的 input_tokens 已含 cached_input_tokens。
                    s['contexts'].append(_ctx(u.get('input_tokens'), 0, u.get('cache_write_input_tokens')))
                elif pt == 'function_call':
                    try:
                        a = json.loads(p.get('arguments') or '{}')
                    except ValueError:
                        a = p.get('arguments') or ''
                    s['calls'].append((p.get('name') or '', a))
                elif pt == 'custom_tool_call':
                    s['calls'].append((p.get('name') or '', p.get('input') or ''))
    return s


def _command(args):
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        c = args.get('command') or args.get('cmd') or ''
        return ' '.join(c) if isinstance(c, list) else str(c)
    return ''


def _edit_paths(tool, args):
    if tool.lower() == 'apply_patch':
        src = args if isinstance(args, str) else (args.get('input') or args.get('patch') or '') if isinstance(args, dict) else ''
        return PATCH_PATH.findall(src)
    if isinstance(args, dict):
        p = args.get('file_path') or args.get('path') or args.get('notebook_path') or ''
        return [p] if p else []
    return []


def is_coordinator(s):
    return bool(ENTRY.search(s['prompt'])) and not PACKET.search(s['prompt'][:2000])


def measure(s):
    """返回单会话两项指标。"""
    polls = 0
    hands_on = []
    for tool, args in s['calls']:
        cmd = _command(args)
        if POLL_TOOL.search(tool) or POLL_CMD.search(cmd):
            polls += 1
        if EDIT_TOOL.match(tool):
            for p in _edit_paths(tool, args):
                if not CONTROL_PATH.search(p):
                    hands_on.append(('edit', p))
        m = FANIN_CMD.search(cmd)
        if m:
            hands_on.append(('cherry-pick' if m.group(1) == 'cherry-pick' else 'fan-in', cmd[:160]))
    n = len(s['calls'])
    return {
        'runtime': s['runtime'],
        'turns': len(s['contexts']),
        'peak_context': max(s['contexts'] or [0]),
        'tool_calls': n,
        'poll_calls': polls,
        'poll_ratio': round(polls / n, 4) if n else 0.0,
        'hands_on': len(hands_on) > 0,
        'hands_on_events': hands_on[:20],
        'hands_on_count': len(hands_on),
        'hands_on_by_kind': {k: sum(1 for x, _ in hands_on if x == k) for k in ('edit', 'cherry-pick', 'fan-in')},
    }


def discover(since_days):
    cutoff = time.time() - since_days * 86400
    home = Path.home()
    roots = [home / '.pi/agent/sessions', home / '.claude/projects', home / '.codex/sessions']
    out = []
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.rglob('*.jsonl'):
            if 'subagent' in str(f) or f.stat().st_mtime < cutoff:
                continue
            out.append(f)
    return sorted(out, key=lambda f: -f.stat().st_mtime)


def summarize(rows):
    peaks = sorted(r['peak_context'] for r in rows)
    ratios = sorted(r['poll_ratio'] for r in rows)
    calls = sum(r['tool_calls'] for r in rows)

    def pct(xs, q):
        return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else 0
    return {
        'sessions': len(rows),
        'peak_context_median': pct(peaks, 0.5),
        'peak_context_p90': pct(peaks, 0.9),
        'peak_context_max': peaks[-1] if peaks else 0,
        'poll_ratio_median': pct(ratios, 0.5),
        'poll_ratio_pooled': round(sum(r['poll_calls'] for r in rows) / calls, 4) if calls else 0.0,
        'hands_on_sessions': sum(1 for r in rows if r['hands_on']),
        'hands_on_events': sum(r['hands_on_count'] for r in rows),
        'hands_on_by_kind': {k: sum(r['hands_on_by_kind'][k] for r in rows) for k in ('edit', 'cherry-pick', 'fan-in')},
    }


def run(argv):
    limit, since, as_json, files = 30, 30, False, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--limit':
            limit = int(argv[i + 1]); i += 2; continue
        if a == '--since-days':
            since = float(argv[i + 1]); i += 2; continue
        if a == '--json':
            as_json = True; i += 1; continue
        files.append(Path(a)); i += 1
    rows = []
    for f in (files or discover(since)):
        s = parse(f)
        if files or is_coordinator(s):
            rows.append({'path': str(f), 'prompt': s['prompt'][:80].replace('\n', ' '), **measure(s)})
        if len(rows) >= limit:
            break
    result = {'summary': summarize(rows), 'sessions': rows}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    print(json.dumps(result['summary'], ensure_ascii=False))
    for r in rows:
        print(f"{r['runtime']:6s} peak={r['peak_context']:>8d} poll={r['poll_calls']:>4d}/{r['tool_calls']:<5d}"
              f" hands_on={r['hands_on_count']:<3d} {r['prompt'][:60]}")
    return 0


def self_test():
    def w(d, name, lines):
        p = Path(d) / name
        p.write_text('\n'.join(json.dumps(x) for x in lines))
        return p
    with tempfile.TemporaryDirectory() as d:
        pi = w(d, 'pi.jsonl', [
            {'type': 'session', 'cwd': '/r'},
            {'type': 'message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '$delivery-pipeline-herdr DD-1'}]}},
            {'type': 'message', 'message': {'role': 'assistant', 'usage': {'input': 10, 'cacheRead': 90, 'cacheWrite': 0}, 'content': [
                {'type': 'toolCall', 'name': 'bash', 'arguments': {'command': 'herdr agent read p1'}},
                {'type': 'toolCall', 'name': 'bash', 'arguments': {'command': 'sleep 30'}},
                {'type': 'toolCall', 'name': 'edit', 'arguments': {'path': '/r/.tmp/x/registry.md'}}]}},
            {'type': 'message', 'message': {'role': 'assistant', 'usage': {'input': 5, 'cacheRead': 300, 'cacheWrite': 5}, 'content': [
                {'type': 'toolCall', 'name': 'edit', 'arguments': {'path': '/r/src/app.ts'}},
                {'type': 'toolCall', 'name': 'bash', 'arguments': {'command': 'git -C /r/.worktrees/int cherry-pick abc'}}]}},
        ])
        s = parse(pi)
        m = measure(s)
        assert s['runtime'] == 'pi' and is_coordinator(s), s
        assert m['peak_context'] == 310 and m['tool_calls'] == 5 and m['poll_calls'] == 2, m
        assert m['hands_on_count'] == 2 and {k for k, _ in m['hands_on_events']} == {'edit', 'cherry-pick'}, m
        claude = w(d, 'claude.jsonl', [
            {'type': 'user', 'message': {'role': 'user', 'content': '/delivery-pipeline-t3code map-7'}},
            {'type': 'assistant', 'message': {'role': 'assistant', 'usage': {'input_tokens': 3, 'cache_read_input_tokens': 1000, 'cache_creation_input_tokens': 7}, 'content': [
                {'type': 'tool_use', 'name': 'Monitor', 'input': {}},
                {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'git merge-base main HEAD'}},
                {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'git status\npython3 -c "x.apply()"'}},
                {'type': 'tool_use', 'name': 'Write', 'input': {'file_path': '/r/.scratch/note.md'}}]}},
        ])
        s = parse(claude)
        m = measure(s)
        assert s['runtime'] == 'claude' and is_coordinator(s), s
        assert m['peak_context'] == 1010 and m['poll_calls'] == 1 and not m['hands_on'], m
        assert measure({'runtime': 'pi', 'contexts': [], 'calls': [('bash', {'command': "subprocess.run(['git','-C',w,'cherry-pick',c])"})]})['hands_on_count'] == 1
        codex = w(d, 'codex.jsonl', [
            {'type': 'session_meta', 'payload': {}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '<environment_context/>'}]}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '$delivery-pipeline-codex-app spec'}]}},
            {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'last_token_usage': {'input_tokens': 500, 'cached_input_tokens': 400}}}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'apply_patch', 'input': '*** Begin Patch\n*** Update File: /r/lib/a.py\n*** End Patch'}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec_command', 'arguments': json.dumps({'cmd': 'git status'})}},
        ])
        s = parse(codex)
        m = measure(s)
        assert s['runtime'] == 'codex' and is_coordinator(s), s
        assert m['peak_context'] == 500 and m['poll_calls'] == 0 and m['hands_on_events'] == [('edit', '/r/lib/a.py')], m
        setup = w(d, 'setup.jsonl', [
            {'type': 'user', 'message': {'role': 'user', 'content': '$delivery-pipeline-setup 看看配置'}},
        ])
        assert not is_coordinator(parse(setup))
        worker = w(d, 'worker.jsonl', [
            {'type': 'user', 'message': {'role': 'user', 'content': '$delivery-pipeline-herdr\nLane ID：L1\n'}},
        ])
        assert not is_coordinator(parse(worker))
        summ = summarize([measure(parse(p)) for p in (pi, claude, codex)])
        assert summ['sessions'] == 3 and summ['hands_on_sessions'] == 2 and summ['peak_context_max'] == 1010, summ
        assert summ['poll_ratio_pooled'] == round(3 / 11, 4), summ
    print('orchestration_metrics self-test: pass')
    return 0


if __name__ == '__main__':
    if sys.argv[1:] == ['self-test']:
        sys.exit(self_test())
    sys.exit(run(sys.argv[1:]))

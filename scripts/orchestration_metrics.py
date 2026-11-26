#!/usr/bin/env python3
"""编排回归指标：协调者与总控会话的上下文峰值、轮询占比、亲手改代码和唤醒来源。

用法：
  orchestration_metrics.py [--limit N] [--since-days D] [--json] [session.jsonl ...]
  orchestration_metrics.py self-test

不给文件时，从 pi（~/.pi/agent/sessions）、Claude Code（~/.claude/projects）与 Codex
（~/.codex/sessions）发现最近的会话，按行为认角色：真跑过 Driver 的 run/record 是 coordinator，
真跑过 autopilot.js poll 是 autopilot。首条消息不参与判断，T3 派发、上下文接力和定时任务
开头的会话同样计入。角色按整个会话认：同一会话既协调又亲手开发时，它的改码全部计入，
逐会话行里能看到。只读会话日志，不写任何文件。
"""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

SEP = r'[\s,\'"]+'  # shell 空白，或 argv 列表里的引号和逗号
ROLE_CMD = {'coordinator': re.compile(r'driver(?:_run)?\.py[\'"]?' + SEP + r'(?:run|record)\b'),
            'autopilot': re.compile(r'autopilot\.js[\'"]?' + SEP + r'poll\b')}
MIN_ACTS = 3  # 主循环会反复跑；少于三次多半是开发或调试时顺手跑的
EVENT = re.compile(r'herdr-autopilot WAKE|^\s*\[T3 Code|^\s*Note: the T3 server')
POLL_CMD = re.compile(r'herdr (agent (get|read)|pane (read|get|process)|wait)|lane-watch|lane_watch'
                      r'|(^|[\s;&|(])sleep\s|process-info|ps -axo|gh (run|pr) (watch|checks)')
POLL_TOOL = re.compile(r'^(Monitor|TaskOutput|ScheduleWakeup|BashOutput|write_stdin)$'
                       r'|t3_thread_wait|t3_background_wait|task_status|wait_agent', re.I)
EDIT_TOOL = re.compile(r'^(edit|write|multiedit|notebookedit|apply_patch|str_replace_based_edit_tool)$', re.I)
CONTROL_PATH = re.compile(r'/\.tmp/|/\.scratch/|registry|/packets?/|^/tmp/|^/private/|/\.(claude|codex|pi|t3|config)/'
                          r'|skills/delivery-pipeline')
# 只认 git 的子命令位：git 后面跳过全局选项，紧跟的那个词才算。
GIT_OP = re.compile(r'\bgit[\'"]?(?:' + SEP + r'-[Cc]' + SEP + r'[^\s,\'"]+|' + SEP + r'--[\w-]+(?:=[^\s,\'"]+)?)*'
                    + SEP + r'(cherry-pick|am|apply|merge)(?![\w-])([^|;&\n]*)')
HANDS_ON = ('edit', 'cherry-pick', 'merge')  # 协调者不该亲手做的
BOOKKEEPING = ('doc', 'land')  # 文档记账；--ff-only 只移动分支指针，是授权收尾
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


def _wake(s, txt):
    """一条真实用户消息开启一次唤醒；来源只看消息开头。"""
    s['prompt'] = s['prompt'] or txt
    src = 'sched' if 'scheduled task' in txt[:200] else 'event' if EVENT.search(txt[:600]) else 'human'
    s['wakes'].append([src, 0])


def _spend(s, ctx):
    s['contexts'].append(ctx)
    if s['wakes']:
        s['wakes'][-1][1] += ctx


def parse(path):
    """归一成 {runtime, prompt, contexts[], calls[(tool, args_dict_or_str)], wakes[[来源, 输入 token]]}。"""
    s = {'runtime': None, 'prompt': '', 'contexts': [], 'calls': [], 'wakes': []}
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
                if m.get('role') == 'user':
                    _wake(s, _text(m.get('content')))
                if m.get('role') == 'assistant':
                    u = m.get('usage') or {}
                    _spend(s, _ctx(u.get('input'), u.get('cacheRead'), u.get('cacheWrite')))
                    for c in m.get('content') or []:
                        if isinstance(c, dict) and c.get('type') == 'toolCall':
                            s['calls'].append((c.get('name') or '', c.get('arguments') or {}))
            elif t in ('user', 'assistant') and isinstance(d.get('message'), dict):
                s['runtime'] = s['runtime'] or 'claude'
                m = d['message']
                if t == 'user' and not d.get('isMeta'):
                    txt = _text(m.get('content')).strip()  # 工具结果没有 text，自然为空
                    if txt and not txt.startswith('<'):
                        _wake(s, txt)
                if t == 'assistant':
                    u = m.get('usage') or {}
                    if u:
                        _spend(s, _ctx(u.get('input_tokens'), u.get('cache_read_input_tokens'),
                                       u.get('cache_creation_input_tokens')))
                    for c in m.get('content') or []:
                        if isinstance(c, dict) and c.get('type') == 'tool_use':
                            s['calls'].append((c.get('name') or '', c.get('input') or {}))
            elif t in ('session_meta', 'response_item', 'event_msg'):
                s['runtime'] = s['runtime'] or 'codex'
                p = d.get('payload') or {}
                pt = p.get('type')
                if pt == 'message' and p.get('role') == 'user':
                    txt = _text(p.get('content')).strip()
                    if txt and not txt.startswith('<') and not txt.startswith('# AGENTS'):
                        _wake(s, txt)
                elif pt == 'token_count' and (p.get('info') or {}).get('last_token_usage'):
                    u = p['info']['last_token_usage']
                    # Codex 的 input_tokens 已含 cached_input_tokens。
                    _spend(s, _ctx(u.get('input_tokens'), 0, u.get('cache_write_input_tokens')))
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


def role(s):
    """按真跑过的命令认角色；两种都跑过时取次数多的。"""
    acts = {r: sum(len(rx.findall(_command(a))) for _, a in s['calls']) for r, rx in ROLE_CMD.items()}
    best = max(acts, key=acts.get)
    return best if acts[best] >= MIN_ACTS else None


def _git_kind(op, rest):
    if op == 'cherry-pick':
        return op
    return 'land' if op == 'merge' and '--ff-only' in rest else 'merge'


def _wakes(rows):
    out = {}
    for src, tokens in rows:
        w = out.setdefault(src, {'count': 0, 'input_tokens': 0})
        w['count'] += 1
        w['input_tokens'] += tokens
    return out


def measure(s):
    """返回单会话指标。"""
    polls = 0
    events = []
    for tool, args in s['calls']:
        cmd = _command(args)
        if POLL_TOOL.search(tool) or POLL_CMD.search(cmd):
            polls += 1
        if EDIT_TOOL.match(tool):
            for p in _edit_paths(tool, args):
                if not CONTROL_PATH.search(p):
                    events.append(('doc' if p.endswith('.md') else 'edit', p))
        for m in GIT_OP.finditer(cmd):
            events.append((_git_kind(m.group(1), m.group(2)), m.group(0)[:160]))
    hands_on = [e for e in events if e[0] in HANDS_ON]
    n = len(s['calls'])
    return {
        'runtime': s['runtime'],
        'role': role(s),
        'turns': len(s['contexts']),
        'peak_context': max(s['contexts'] or [0]),
        'tool_calls': n,
        'poll_calls': polls,
        'poll_ratio': round(polls / n, 4) if n else 0.0,
        'hands_on': len(hands_on) > 0,
        'hands_on_events': hands_on[:20],
        'hands_on_count': len(hands_on),
        'hands_on_by_kind': {k: sum(1 for x, _ in events if x == k) for k in HANDS_ON},
        'bookkeeping_by_kind': {k: sum(1 for x, _ in events if x == k) for k in BOOKKEEPING},
        'wakes': _wakes(s['wakes']),
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
        'hands_on_by_kind': {k: sum(r['hands_on_by_kind'][k] for r in rows) for k in HANDS_ON},
        'bookkeeping_by_kind': {k: sum(r['bookkeeping_by_kind'][k] for r in rows) for k in BOOKKEEPING},
        'wakes': {src: {k: sum(r['wakes'].get(src, {}).get(k, 0) for r in rows) for k in ('count', 'input_tokens')}
                  for src in sorted({src for r in rows for src in r['wakes']})},
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
        if files or role(s):
            rows.append({'path': str(f), 'prompt': s['prompt'][:80].replace('\n', ' '), **measure(s)})
        if len(rows) >= limit:
            break
    # 两种角色的上下文和唤醒模式不同，分开汇总才可比。
    result = {'summary': {(k or 'other'): summarize([r for r in rows if r['role'] == k])
                          for k in sorted({r['role'] for r in rows}, key=str)},
              'sessions': rows}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    for k, v in result['summary'].items():
        print(k, json.dumps(v, ensure_ascii=False))
    for r in rows:
        wakes = ' '.join(f"{src}={w['count']}/{w['input_tokens'] / 1e6:.1f}M" for src, w in sorted(r['wakes'].items()))
        print(f"{r['runtime']:6s} {r['role'] or 'other':11s} peak={r['peak_context']:>8d} poll={r['poll_calls']:>4d}/{r['tool_calls']:<5d}"
              f" hands_on={r['hands_on_count']:<3d} wakes[{wakes}] {r['prompt'][:50]}")
    return 0


def self_test():
    def w(d, name, lines):
        p = Path(d) / name
        p.write_text('\n'.join(json.dumps(x) for x in lines))
        return p

    def pi_calls(*cmds):
        return [{'type': 'toolCall', 'name': 'bash', 'arguments': {'command': c}} for c in cmds]
    loop = ['python3 skills/delivery-pipeline/scripts/driver.py run /m', 'python3 driver.py record /m r.json',
            'python3 /x/driver_run.py run /m']
    with tempfile.TemporaryDirectory() as d:
        # 首条消息是 T3 派发的接力摘要，不是壳调用：仍按行为认作协调者。
        pi = w(d, 'pi.jsonl', [
            {'type': 'session', 'cwd': '/r'},
            {'type': 'message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'Context handoff (full_thread_summary)'}]}},
            {'type': 'message', 'message': {'role': 'assistant', 'usage': {'input': 10, 'cacheRead': 90, 'cacheWrite': 0}, 'content': pi_calls(*loop) + [
                {'type': 'toolCall', 'name': 'bash', 'arguments': {'command': 'herdr agent read p1'}},
                {'type': 'toolCall', 'name': 'bash', 'arguments': {'command': 'sleep 30'}},
                {'type': 'toolCall', 'name': 'edit', 'arguments': {'path': '/r/.tmp/x/registry.md'}}]}},
            {'type': 'message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '[T3 Code agent message] lane done'}]}},
            {'type': 'message', 'message': {'role': 'assistant', 'usage': {'input': 5, 'cacheRead': 300, 'cacheWrite': 5}, 'content': [
                {'type': 'toolCall', 'name': 'edit', 'arguments': {'path': '/r/src/app.ts'}},
                {'type': 'toolCall', 'name': 'edit', 'arguments': {'path': '/r/docs/progress.md'}},
                {'type': 'toolCall', 'name': 'bash', 'arguments': {'command': 'git -C /r/.worktrees/int cherry-pick abc'}},
                {'type': 'toolCall', 'name': 'bash', 'arguments': {'command': 'git -C ../cand merge --no-edit abc && git -C ../main merge --ff-only cand'}}]}},
        ])
        s = parse(pi)
        m = measure(s)
        assert s['runtime'] == 'pi' and m['role'] == 'coordinator', m
        assert m['peak_context'] == 310 and m['tool_calls'] == 10 and m['poll_calls'] == 2, m
        assert m['hands_on_by_kind'] == {'edit': 1, 'cherry-pick': 1, 'merge': 1}, m
        assert m['bookkeeping_by_kind'] == {'doc': 1, 'land': 1} and m['hands_on_count'] == 3, m
        assert m['wakes'] == {'human': {'count': 1, 'input_tokens': 100}, 'event': {'count': 1, 'input_tokens': 310}}, m
        # 只有 git 的子命令位算数：merge-base、脚本里的 .apply()、diff 后面的词都不算。
        claude = w(d, 'claude.jsonl', [
            {'type': 'user', 'message': {'role': 'user', 'content': '/delivery-pipeline-t3code map-7'}},
            {'type': 'assistant', 'message': {'role': 'assistant', 'usage': {'input_tokens': 3, 'cache_read_input_tokens': 1000, 'cache_creation_input_tokens': 7}, 'content': [
                {'type': 'tool_use', 'name': 'Monitor', 'input': {}},
                {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'git merge-base main HEAD'}},
                {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'git status\npython3 -c "x.apply()"'}},
                {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'git diff a b -- merge apply'}},
                {'type': 'tool_use', 'name': 'Write', 'input': {'file_path': '/r/.scratch/note.md'}}]}},
            {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'ok'}]}},
        ])
        s = parse(claude)
        m = measure(s)
        assert s['runtime'] == 'claude' and m['role'] is None, m  # 壳调用开头但没跑过 Driver：不是协调者
        assert m['peak_context'] == 1010 and m['poll_calls'] == 1 and not m['hands_on'], m
        assert m['wakes'] == {'human': {'count': 1, 'input_tokens': 1010}}, m
        assert measure({'runtime': 'pi', 'contexts': [], 'wakes': [], 'calls': [
            ('bash', {'command': "subprocess.run(['git','-C',w,'cherry-pick',c])"})]})['hands_on_count'] == 1
        # 总控：定时唤醒与事件唤醒分开记账。
        usage = lambda n: {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'last_token_usage': {'input_tokens': n, 'cached_input_tokens': n - 1}}}}
        user = lambda t: {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': t}]}}
        poll = {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'input': 'tools.exec_command({cmd:"node scripts/autopilot.js poll"})'}}
        codex = w(d, 'codex.jsonl', [
            {'type': 'session_meta', 'payload': {}},
            user('<environment_context/>'),
            user('$herdr-autopilot JB-1'), usage(500), poll,
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'apply_patch', 'input': '*** Begin Patch\n*** Update File: /r/lib/a.py\n*** End Patch'}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec_command', 'arguments': json.dumps({'cmd': 'git status'})}},
            user('This is a scheduled task run.\n$herdr-autopilot'), usage(600), poll,
            user('This is a scheduled task run.\n$herdr-autopilot'), usage(700), poll,
            user('[herdr-autopilot WAKE] lane a (JB-1, agent=a, stage=pipeline) 状态变为 done。'), usage(800),
        ])
        s = parse(codex)
        m = measure(s)
        assert s['runtime'] == 'codex' and m['role'] == 'autopilot', m
        assert m['peak_context'] == 800 and m['hands_on_events'] == [('edit', '/r/lib/a.py')], m
        assert m['wakes'] == {'human': {'count': 1, 'input_tokens': 500}, 'sched': {'count': 2, 'input_tokens': 1300},
                              'event': {'count': 1, 'input_tokens': 800}}, m
        # 开发会话里顺手跑一次 Driver，或命令文本里只是提到它：不算协调者。
        dev = w(d, 'dev.jsonl', [
            {'type': 'session', 'cwd': '/r'},
            {'type': 'message', 'message': {'role': 'user', 'content': '$delivery-pipeline-herdr 看看'}},
            {'type': 'message', 'message': {'role': 'assistant', 'usage': {'input': 1}, 'content': pi_calls(
                'python3 driver.py self-test', 'python3 driver.py run /tmp/m', 'grep -n has_briefs driver.py')}},
        ])
        assert role(parse(dev)) is None
        rows = [measure(parse(p)) for p in (pi, claude, codex)]
        summ = summarize(rows)
        assert summ['sessions'] == 3 and summ['hands_on_sessions'] == 2 and summ['peak_context_max'] == 1010, summ
        assert summ['poll_ratio_pooled'] == round(3 / 20, 4), summ
        assert summ['wakes']['sched'] == {'count': 2, 'input_tokens': 1300} and summ['wakes']['human']['count'] == 3, summ
        assert summ['bookkeeping_by_kind'] == {'doc': 1, 'land': 1}, summ
    print('orchestration_metrics self-test: pass')
    return 0


if __name__ == '__main__':
    if sys.argv[1:] == ['self-test']:
        sys.exit(self_test())
    sys.exit(run(sys.argv[1:]))

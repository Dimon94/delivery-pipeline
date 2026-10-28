#!/usr/bin/env python3
"""用 fake Herdr 复跑阶段唤醒、去重和终态监听，不等待真实轮询间隔。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SCRIPT = Path(__file__).with_name('lane-watch.sh')

FAKE_HERDR = '''import json
from pathlib import Path
import sys
root = Path(__file__).parent
args = sys.argv[1:]
if args[:2] == ['pane', 'read']:
    count = int((root / 'count').read_text())
    frames = json.loads((root / 'frames.json').read_text())
    (root / 'count').write_text(str(count + 1))
    # jsonl 场景：按轮询次数重生成 session.jsonl，前 K 轮 1 条 marker，之后 2 条
    if (root / 'jsonl_after').exists():
        k = int((root / 'jsonl_after').read_text())
        markers = 1 if count < k else 2
        lines = [
            json.dumps({'type': 'message', 'timestamp': '2026-01-01T00:00:0%dZ' % i,
                        'message': {'role': 'assistant',
                                    'content': [{'type': 'text', 'text': 'LANE_DONE lane'}]}})
            for i in range(markers)
        ]
        (root / 'session.jsonl').write_text('\\n'.join(lines) + '\\n')
    print(frames[min(count, len(frames) - 1)])
elif args[:2] == ['pane', 'get']:
    if (root / 'session.jsonl').exists():
        print(json.dumps({'result': {'pane': {'agent_session': {'value': str(root / 'session.jsonl')}}}}))
elif args[:2] == ['agent', 'prompt']:
    assert args[2] == 'coordinator'
    if '/tmp/a.json' in args[3]:
        attempts = int((root / 'a-attempts').read_text())
        (root / 'a-attempts').write_text(str(attempts + 1))
        if attempts == 0:
            raise SystemExit(1)
    with (root / 'prompts.jsonl').open('a') as stream:
        stream.write(json.dumps([int((root / 'count').read_text()), args[3]]) + '\\n')
else:
    raise SystemExit(2)
'''


def setup_case(root: Path, frames, jsonl_after=None):
    (root / 'frames.json').write_text(json.dumps(frames))
    (root / 'count').write_text('0')
    (root / 'a-attempts').write_text('0')
    if jsonl_after is not None:
        (root / 'jsonl_after').write_text(str(jsonl_after))
        (root / 'session.jsonl').write_text('')
    (root / 'herdr').write_text(f'#!{sys.executable}\n' + FAKE_HERDR)
    (root / 'sleep').write_text('#!/bin/sh\nexit 0\n')
    for name in ('herdr', 'sleep'):
        (root / name).chmod(0o755)


def prompts_of(root: Path):
    p = root / 'prompts.jsonl'
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines()]


def run(root: Path):
    return subprocess.run(
        ['bash', str(SCRIPT), 'worker', 'coordinator', 'lane', '测试 lane'],
        env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
             'LANE_WATCH_STATE_DIR': str(root)},
        capture_output=True, text=True, timeout=10,
    )


def case_prewalk_and_done(root: Path):
    frames = [
        ' 说明 PREWALK_READY lane /tmp/a.json\n PREWALK_READY lane-other /tmp/a.json\n'
        ' PREWALK_READY lane relative.json\n PREWALK_READY lane\n'
        ' `PREWALK_READY lane /tmp/a.json`',
        ' PREWALK_READY lane /tmp/a.json',
        'worker idle',
        '\t  PREWALK_READY lane /tmp/a.json',
        '  PREWALK_READY lane /tmp/b checkpoint.json',
        'PREWALK_READY lane /tmp/b checkpoint.json',
        'worker idle',
        'LANE_DONE lane',
    ]
    setup_case(root, frames)
    result = run(root)
    assert result.returncode == 0, (result.returncode, result.stderr)
    prompts = prompts_of(root)
    assert int((root / 'a-attempts').read_text()) == 2, 'failed PREWALK_READY must be retried'
    assert sum('/tmp/a.json' in item[1] for item in prompts) == 1, f'a callbacks: {prompts}'
    assert sum('/tmp/b checkpoint.json' in item[1] for item in prompts) == 1, f'b callbacks: {prompts}'
    for (_, message), path in zip(prompts[:2], ('/tmp/a.json', '/tmp/b checkpoint.json')):
        assert f'PREWALK_READY lane {path}' in message, message
        assert 'checkpoint' in message and '停止证据' in message, message
        assert 'terminal fan-in:' not in message, message
    assert 'terminal fan-in:' in prompts[-1][1], prompts
    assert int((root / 'count').read_text()) == len(frames)
    print('lane watcher: pass (exact marker, once per marker, continued LANE_DONE)')


def case_stale_visible_no_false_wake(root: Path):
    """map#765 回归：重挂 watcher 时屏上残留上一轮 LANE_DONE，数量不增则永不唤醒。"""
    setup_case(root, ['LANE_DONE lane\nworker 上轮报告残留…'])
    proc = subprocess.Popen(
        ['bash', str(SCRIPT), 'worker', 'coordinator', 'lane', '测试 lane'],
        env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
             'LANE_WATCH_STATE_DIR': str(root)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    proc.terminate()
    proc.wait(timeout=5)
    assert prompts_of(root) == [], f'stale marker must not wake: {prompts_of(root)}'
    print('lane watcher: pass (stale visible marker, no false wake)')


def case_second_round_visible_wakes(root: Path):
    """map#765 回归：陈旧标记已在屏上，新一轮 LANE_DONE 出现（数量增）仍须唤醒一次。"""
    setup_case(root, ['LANE_DONE lane\n上轮残留', 'worker idle', 'LANE_DONE lane\nLANE_DONE lane'])
    result = run(root)
    assert result.returncode == 0, (result.returncode, result.stderr)
    prompts = prompts_of(root)
    assert len(prompts) == 1 and 'terminal fan-in:' in prompts[0][1], prompts
    print('lane watcher: pass (second-round visible marker wakes once)')


def case_jsonl_count_increase_wakes(root: Path):
    """jsonl 通道计数去重：建档轮已有 1 条不唤醒，第 3 轮询起增至 2 条才唤醒一次。"""
    setup_case(root, ['worker idle'] * 6, jsonl_after=3)
    result = run(root)
    assert result.returncode == 0, (result.returncode, result.stderr)
    prompts = prompts_of(root)
    assert len(prompts) == 1 and 'session jsonl 实证' in prompts[0][1], prompts
    print('lane watcher: pass (jsonl count increase wakes once, replay silent)')


def main():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        for i, case in enumerate((
            case_prewalk_and_done,
            case_stale_visible_no_false_wake,
            case_second_round_visible_wakes,
            case_jsonl_count_increase_wakes,
        )):
            root = base / f'case{i}'
            root.mkdir()
            case(root)


if __name__ == '__main__':
    main()

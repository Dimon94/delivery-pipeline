#!/usr/bin/env python3
"""用 fake Herdr 复跑终态监听与去重，不等待真实轮询间隔。"""
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
        marker = (root / 'marker').read_text() if (root / 'marker').exists() else 'LANE_DONE lane'
        lines = [
            json.dumps({'type': 'message', 'timestamp': '2026-01-01T00:00:0%dZ' % i,
                        'message': {'role': 'assistant',
                                    'content': [{'type': 'text', 'text': marker}]}})
            for i in range(markers)
        ]
        (root / 'session.jsonl').write_text('\\n'.join(lines) + '\\n')
    print(frames[min(count, len(frames) - 1)])
elif args[:2] == ['pane', 'get']:
    pane = {}
    if (root / 'session.jsonl').exists():
        pane['agent_session'] = {'value': str(root / 'session.jsonl')}
    if (root / 'statuses.json').exists():
        count = int((root / 'count').read_text())
        statuses = json.loads((root / 'statuses.json').read_text())
        pane['agent_status'] = statuses[min(count, len(statuses) - 1)]
    if pane:
        print(json.dumps({'result': {'pane': pane}}))
elif args[:2] == ['agent', 'prompt']:
    assert args[2] == 'coordinator'
    with (root / 'prompts.jsonl').open('a') as stream:
        stream.write(json.dumps([int((root / 'count').read_text()), args[3]]) + '\\n')
else:
    raise SystemExit(2)
'''


def setup_case(root: Path, frames, jsonl_after=None):
    (root / 'frames.json').write_text(json.dumps(frames))
    (root / 'count').write_text('0')
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
        capture_output=True, text=True, timeout=30,
    )


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


def case_jsonl_commit_suffix_wakes(root: Path):
    """终态 `LANE_DONE <lane> <commit>` 带 commit 后缀仍计数唤醒。"""
    setup_case(root, ['worker idle'] * 6, jsonl_after=3)
    (root / 'marker').write_text('LANE_DONE lane abc1234')
    result = run(root)
    assert result.returncode == 0, (result.returncode, result.stderr)
    prompts = prompts_of(root)
    assert len(prompts) == 1 and 'session jsonl 实证' in prompts[0][1], prompts
    print('lane watcher: pass (commit-suffixed marker wakes once)')


def case_jsonl_sibling_lane_silent(root: Path):
    """`LANE_DONE lane-2` 不得唤醒 lane `lane` 的 watcher。"""
    setup_case(root, ['worker idle'] * 6, jsonl_after=3)
    (root / 'marker').write_text('LANE_DONE lane-2 abc1234')
    proc = subprocess.Popen(
        ['bash', str(SCRIPT), 'worker', 'coordinator', 'lane', '测试 lane'],
        env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
             'LANE_WATCH_STATE_DIR': str(root)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.8)
    proc.terminate()
    proc.wait(timeout=5)
    assert prompts_of(root) == [], prompts_of(root)
    print('lane watcher: pass (sibling lane marker silent)')


def case_driver_quiet_and_wake(root: Path):
    """ADR-0026：有 driver.json 时终态行先交 Driver；退出 0 不唤醒，退出 10 带 Action 唤醒。"""
    for rc, expect in ((0, 0), (10, 1), (1, 1)):
        case = root / f'rc{rc}'
        case.mkdir()
        setup_case(case, ['worker idle'] * 6, jsonl_after=3)
        (case / 'marker').write_text('LANE_DONE lane abc1234')
        (case / 'driver.json').write_text('{}')
        fake = case / 'driver_run.py'
        fake.write_text(f'import sys\nopen({str(case / "driver_args")!r}, "w").write(" ".join(sys.argv[1:]))\n'
                        f'print(\'{{"action":"judge","id":"j","args":{{}}}}\')\nraise SystemExit({rc})\n')
        result = subprocess.run(
            ['bash', str(SCRIPT), 'worker', 'coordinator', 'lane', '测试 lane'],
            env={**os.environ, 'PATH': f'{case}:{os.environ["PATH"]}', 'LANE_WATCH_STATE_DIR': str(case),
                 'LANE_WATCH_MAP_DIR': str(case), 'DP_DRIVER_RUN': str(fake)},
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (result.returncode, result.stderr)
        args = (case / 'driver_args').read_text()
        assert args == f'watch {case} LANE_DONE lane abc1234', args
        prompts = prompts_of(case)
        assert len(prompts) == expect, prompts
        if rc == 10:
            assert 'Driver Action' in prompts[0][1] and '"judge"' in prompts[0][1], prompts
        if rc == 1:
            assert 'Driver 未完成回收' in prompts[0][1] and 'merger' not in prompts[0][1], prompts
    print('lane watcher: pass (driver wait silent, driver action wakes once)')


def case_blocked_wakes_once_then_resumes_for_done(root: Path):
    """worker 进入 blocked 时立刻边沿唤醒协调者一次，不重复刷屏，且继续监听直到 LANE_DONE。"""
    setup_case(root, ['running', 'approve?', 'approve?', 'resumed', 'LANE_DONE lane'])
    (root / 'statuses.json').write_text(json.dumps(['working', 'blocked', 'blocked', 'working', 'done']))
    result = run(root)
    assert result.returncode == 0, (result.returncode, result.stderr)
    prompts = prompts_of(root)
    assert len(prompts) == 2, prompts
    assert 'WAKE_BLOCKED:' in prompts[0][1], prompts[0]
    assert 'terminal fan-in:' in prompts[1][1], prompts[1]
    print('lane watcher: pass (blocked wakes once on edge, then catches LANE_DONE)')


def main():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        for i, case in enumerate((
            case_stale_visible_no_false_wake,
            case_second_round_visible_wakes,
            case_jsonl_count_increase_wakes,
            case_jsonl_commit_suffix_wakes,
            case_jsonl_sibling_lane_silent,
            case_driver_quiet_and_wake,
            case_blocked_wakes_once_then_resumes_for_done,
        )):
            root = base / f'case{i}'
            root.mkdir()
            case(root)


if __name__ == '__main__':
    main()

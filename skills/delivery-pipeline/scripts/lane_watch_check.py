#!/usr/bin/env python3
"""用 fake Herdr 复跑阶段唤醒、去重和终态监听，不等待真实轮询间隔。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        frames = [
            '说明 PREWALK_READY lane /tmp/a.json\nPREWALK_READY lane-other /tmp/a.json\n'
            'PREWALK_READY lane relative.json\nPREWALK_READY lane\n'
            '`PREWALK_READY lane /tmp/a.json`',
            'PREWALK_READY lane /tmp/a.json',
            'PREWALK_READY lane /tmp/a.json',
            'PREWALK_READY lane /tmp/b checkpoint.json',
            'PREWALK_READY lane /tmp/a.json',
            'LANE_DONE lane',
        ]
        (root / 'frames.json').write_text(json.dumps(frames))
        (root / 'count').write_text('0')
        (root / 'herdr').write_text(f'#!{sys.executable}\n' + '''import json
from pathlib import Path
import sys
root = Path(__file__).parent
args = sys.argv[1:]
if args[:2] == ['pane', 'read']:
    count = int((root / 'count').read_text())
    frames = json.loads((root / 'frames.json').read_text())
    (root / 'count').write_text(str(count + 1))
    print(frames[min(count, len(frames) - 1)])
elif args[:2] == ['pane', 'get']:
    pass
elif args[:2] == ['agent', 'prompt']:
    assert args[2] == 'coordinator'
    with (root / 'prompts.jsonl').open('a') as stream:
        stream.write(json.dumps([int((root / 'count').read_text()), args[3]]) + '\\n')
else:
    raise SystemExit(2)
''')
        (root / 'sleep').write_text('#!/bin/sh\nexit 0\n')
        for name in ('herdr', 'sleep'):
            (root / name).chmod(0o755)
        result = subprocess.run(
            ['bash', str(Path(__file__).with_name('lane-watch.sh')),
             'worker', 'coordinator', 'lane', '测试 lane'],
            env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}'},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (result.returncode, result.stderr)
        prompts = [json.loads(line) for line in (root / 'prompts.jsonl').read_text().splitlines()]
        assert [item[0] for item in prompts] == [2, 4, 6], f'callback frames: {prompts}'
        for (_, message), path in zip(prompts[:2], ('/tmp/a.json', '/tmp/b checkpoint.json')):
            assert f'PREWALK_READY lane {path}' in message, message
            assert 'checkpoint' in message and '停止证据' in message, message
            assert 'terminal fan-in:' not in message, message
        assert 'terminal fan-in:' in prompts[-1][1], prompts
        assert int((root / 'count').read_text()) == len(frames)
    print('lane watcher: pass (exact marker, once per marker, continued LANE_DONE)')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""DD-509：经生产 dispatch.py CLI 的 fake Herdr 外部 seam，非真实执行。"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from dispatch_check import run, FAKE_HERDR, GOOD_MAP


def check():
    base = {'tabs': [{'tab_id': 'w1:t1', 'label': 'coord', 'pane_count': 1, 'workspace_id': 'w1'}],
            'panes': [{'pane_id': 'w1:p1', 'tab_id': 'w1:t1', 'workspace_id': 'w1'}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root/'herdr').write_text(f'#!{sys.executable}\n'+FAKE_HERDR)
        (root/'watch').write_text('#!/bin/sh\nexit 0\n')
        for name in ['herdr', 'watch']: (root/name).chmod(0o755)
        owner = root/'owner/SKILL.md'
        owner.parent.mkdir()
        owner.write_text('---\nname: code-review\n---\nfixture owner; does not execute a model\n')
        packet = f'Owner：code-review；{owner}；fixture file invocation\n'
        flags = ('--task', 'review', '--output-mode', 'verdict', '--review-scope', 'whole-change',
                 '--required-axes', 'standards', 'spec', '--request-id', 'round-1')
        map_text = GOOD_MAP.replace('role: map', 'work_item: DD-508\nrole: map\nbase_commit: abc')
        result, path, calls = run(root, 'review-single', base, packet=packet, map_text=map_text, extra=flags)
        assert result.returncode == 0, result.stdout+result.stderr
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'delivery-pipeline/scripts'))
        import lane_registry
        row,_ = lane_registry.read(path, 'review-single')
        assert row['review_plan']['required_axes'] == ['standards', 'spec']
        assert row['review_plan']['lane']['selected']['model'] == 'provider/model'
        assert len([c for c in calls if c[:2] == ['agent', 'start']]) == 1
        delivered = (root/'packet.md').read_text()
        assert 'DP_REVIEW_PLAN' in delivered and '"execution_evidence": null' in delivered
        assert '"axis": "standards"' in delivered and '"axis": "spec"' in delivered
        assert '逐轴' in delivered and '不得重新读取配置' in delivered
        # 相同 lane 已终态也不能再创建第二个原生 pane/请求。
        row['state'] = 'terminal'
        lane_registry.write(path, row)
        result, _, calls = run(root, 'review-single', base, packet=packet, map_text=map_text, extra=flags)
        assert result.returncode != 0 and not calls, 'completed review lane redispatched'

        result, _, calls = run(root, 'bad-scope', base, packet=packet, map_text=map_text,
                               extra=(*flags, '--review-scope', 'implementation'))
        assert result.returncode != 0 and not calls
        result, _, calls = run(root, 'bad-owner', base, packet='Owner：other；/missing；fixture',
                               map_text=map_text, extra=flags)
        assert result.returncode != 0 and not calls
    print('single-model dispatch: pass (fake Herdr; native execution Unknown)')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--case', choices=['single-model'], required=True)
    p.parse_args()
    check()

#!/usr/bin/env python3
"""DD-629：预期来自 DD-628 判定表与公开命令 Ensures；全部使用临时配置。"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

TOOL = Path(__file__).resolve().parents[1] / 'skills/delivery-pipeline-setup/scripts/model_config.py'
spec = importlib.util.spec_from_file_location('model_config', TOOL)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def identity(model):
    return dict(agent='pi', model=model, effort='high')


def fixture():
    c = m.migrate_document(m.valid_fixture())[0]
    for task in c['work']:
        c['work'][task] = {**identity('gpt-6.1-sol'), 'fallbacks': []}
    for scope in c['review'].values():
        for axis in scope:
            scope[axis] = {**identity('gpt-6.1-sol'), 'candidates': []}
    c['review']['whole-change']['standards']['candidates'] = [identity('claude-opus-5-5')]
    ev = dict(request_id='fixture', observed_at='fixture', sources={'pi': {'status': 'ok'}},
              capabilities={'pi': {'binary': True, 'models': {
                  name: ['high'] for name in ['gpt-6.1-sol', 'claude-opus-5-5', 'mystery']}}})
    return c, ev


def vendors():
    cases = [('magpie/junbo/gemini-4-argon', 'google'), ('magpie/group/kimi-k3.1-pro', 'moonshot'),
             ('gpt-6.1-sol', 'openai'), ('claude-opus-5-5', 'anthropic'),
             ('route/GeMiNi-4@256k', 'google'), ('o1-pro', 'openai'), ('o3', 'openai'),
             ('o4-mini', 'openai'), ('grok-4', 'xai'), ('deepseek-v4', 'deepseek'), ('mystery', None)]
    for model, expected in cases:
        assert m.model_vendor({}, 'pi', model) == expected, (model, expected)
    c = {'model_families': {'pi': {'route/gpt-x@256k': {'family': 'custom', 'source': 'user_declared'}}}}
    assert m.model_vendor(c, 'pi', 'route/gpt-x@256k') == 'custom'
    assert m.model_vendor(c, 'codex', 'route/gpt-x@256k') == 'openai'
    print('vendor table: PASS')


def preview():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        def cli(c, ev, ok=True):
            config, evidence = path/'candidate.json', path/'evidence.json'
            config.write_text(json.dumps(c)); evidence.write_text(json.dumps(ev))
            before = (config.read_bytes(), evidence.read_bytes())
            p = subprocess.run([sys.executable, str(TOOL), 'preview-review', '--candidate', str(config),
                                '--evidence', str(evidence)], capture_output=True, text=True)
            assert (config.read_bytes(), evidence.read_bytes()) == before
            assert (p.returncode == 0) == ok, p.stdout+p.stderr
            value = json.loads(p.stdout)
            if not ok:
                assert value['valid'] is False and value['errors']
            return value
        c, ev = fixture()
        original = copy.deepcopy(c)
        result = cli(c, ev)
        assert set(result) == {'standards'}
        assert result['standards'] == dict(selected=identity('claude-opus-5-5'), selected_index=1,
                                            outcome='different', unrecognized=[])
        pool = [identity('gpt-6.1-sol'), identity('claude-opus-5-5')]
        native = {'standards': [dict(identity=x, status='runnable', evidence_id=str(i)) for i,x in enumerate(pool)]}
        implementations = [dict(lane_id='backend', requested=identity('gpt-6.1-sol'), executed=None)]
        plan = m.resolve_review_plan(c, required_axes=['standards'], implementations=implementations,
                                    evidence=ev, native_capabilities=native, request_id='fixture')
        assert plan['lane']['selected'] == result['standards']['selected']
        assert set(plan) == {'scope','required_axes','config_hash','request_id','implementations','lane','axes','family_evidence','implementation_evidence'}
        assert set(plan['lane']) == {'selected','selected_index','comparison','comparison_basis','fallback','attempts','probe_evidence_id','native_evidence_ids'}
        assert all(x['vendor_source'] == 'vendor_table' for x in plan['family_evidence'])
        # planning/testing 和备用不属于界面当前写代码身份。
        c['work']['planning']['model'] = c['work']['testing']['model'] = 'claude-opus-5-5'
        c['work']['backend']['fallbacks'] = [identity('claude-opus-5-5')]
        assert cli(c, ev) == result
        c['work']['design']['model'] = 'claude-opus-5-5'
        assert cli(c, ev)['standards']['outcome'] == 'no_different_family'
        c, ev = fixture()
        c['model_families'] = {'pi': {'claude-opus-5-5': {'family': 'openai', 'source': 'user_declared'}}}
        assert cli(c, ev)['standards']['selected_index'] == 0
        c, ev = fixture()
        c['review']['whole-change']['standards']['candidates'] = [identity('mystery')]
        value = cli(c, ev)['standards']
        assert value == dict(selected=identity('gpt-6.1-sol'), selected_index=0, outcome='unrecognized', unrecognized=[identity('mystery')])
        ev['capabilities']['pi']['models'] = {}
        assert cli(c, ev)['standards'] == dict(selected=None, selected_index=None, outcome='none_runnable', unrecognized=[identity('mystery')])
        c, ev = fixture()
        ev['capabilities']['pi']['models'].pop('gpt-6.1-sol')
        assert cli(c, ev)['standards']['selected_index'] == 1
        for key in ['sources', 'capabilities', 'request_id', 'observed_at']:
            bad = copy.deepcopy(ev); bad.pop(key)
            cli(c, bad, False)
        bad = copy.deepcopy(ev); bad['sources']['pi']['status'] = 'unknown'; cli(c, bad, False)
        bad = copy.deepcopy(ev); del bad['capabilities']['pi']['models']; cli(c, bad, False)
        bad = copy.deepcopy(c); bad['version'] = 99; cli(bad, ev, False)
        assert c == original
        c['review']['whole-change']['standards']['candidates'] = []
        assert cli(c, ev) == {}
    print('preview-review: four outcomes, scope, runtime parity, invalid evidence, read-only PASS')


if __name__ == '__main__':
    if '--vendors' in sys.argv:
        vendors()
    else:
        preview()
        vendors()

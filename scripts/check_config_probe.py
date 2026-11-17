#!/usr/bin/env python3
"""通过公开 probe 命令核验来源隔离与精确身份；外部来源受控。"""
import copy, importlib.util, json, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
tool = root / 'skills/delivery-pipeline-setup/scripts/model_config.py'
spec = importlib.util.spec_from_file_location('model_config', tool)
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)
assert callable(getattr(mc, 'codex_route', None)), '缺少 Codex 三态路由识别'
route_cases = [
    ({}, {}, 'direct'),
    ({'model_provider': 'openai'}, {'OPENAI_BASE_URL': 'http://127.0.0.1:3425/v1'}, 'gateway'),
    ({'model_provider': 'magpie', 'model_providers': {'magpie': {'base_url': 'http://127.0.0.1:3425/backend-api/codex/'}}}, {}, 'gateway'),
    ({'model_provider': 'openai', 'openai_base_url': 'https://proxy.example/v1'}, {}, None),
    ({'model_provider': 'custom', 'model_providers': {'custom': {'base_url': 'https://proxy.example/v1'}}}, {}, None),
    ({'openai_base_url': 'https://proxy.example/v1'}, {'OPENAI_BASE_URL': 'http://127.0.0.1:3425/v1/'}, 'gateway'),
    ({}, {'OPENAI_BASE_URL': 'https://proxy.example/v1'}, None),
]
for config, env, expected in route_cases:
    before = copy.deepcopy((config, env))
    assert mc.codex_route(config, env) == expected, (config, env, expected)
    assert (config, env) == before, '路由识别不能修改输入'
print('Codex route table: pass')
raw = {'gateway': {'status':'ok','data':[{'id':'vendor/model@large','supported_reasoning_levels':[{'effort':'low'},{'effort':'high'},{'effort':'max'}]}]},
       'harnesses': {'pi': {'binary':True,'route':'gateway','models':[{'native_id':'magpie/vendor/model@large','gateway_id':'vendor/model@large','efforts':['low','high']}]},
                     'codex': {'binary':True,'route':'gateway','models':[{'native_id':'vendor/model@large','gateway_id':'vendor/model@large','efforts':['high','xhigh']}]},
                     'claude': {'binary':False,'route':None,'models':[]}}}
def probe(value):
    p = subprocess.run([sys.executable,str(tool),'probe','--request-id','acceptance'],input=json.dumps(value),text=True,capture_output=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)
p = probe(raw)
assert p['request_id'] == 'acceptance' and p['observed_at']
assert p['gateway'] == {'status':'ok'}, 'Host 传入 ok 时证据必须声明网关可达'
assert p['capabilities']['pi']['models'] == {'magpie/vendor/model@large':['low','high']}
assert p['capabilities']['codex']['models'] == {'vendor/model@large':['high']}
assert p['sources']['pi']['status'] == 'ok' and p['sources']['claude']['status'] == 'unknown'
unmapped = json.loads(json.dumps(raw))
unmapped['harnesses']['codex']['models'] = [{'native_id':'gpt-native-only','efforts':['high']}]
p = probe(unmapped)
assert p['capabilities']['codex']['models'] == {}, '原生 catalog 不能绕过 magpie 来源边界'
assert p['sources']['codex']['status'] == 'unknown'
raw['harnesses']['codex']['route'] = None
p = probe(raw)
assert p['capabilities']['codex']['models'] == {} and p['sources']['pi']['status'] == 'ok'
raw['gateway'] = {'status':'unknown'}
p = probe(raw)
assert p['capabilities']['pi']['models'] == {}
assert p['gateway'] == {'status':'unreachable'}, '网关未知必须区分为 unreachable'
for odd in ({'status':'OK'}, {'status':'error','data':[]}, {}):
    raw['gateway'] = odd
    assert probe(raw)['gateway'] == {'status':'unreachable'}, '只有精确的 ok 才算可达'
del raw['gateway']
assert probe(raw)['gateway'] == {'status':'unreachable'}, 'Host 未传 gateway 时不能当作可达'
direct = copy.deepcopy(raw)
direct['harnesses']['codex'] = {'binary': True, 'route': 'direct',
    'models': [{'native_id': 'gpt-6.1-sol', 'efforts': ['low', 'high', 'xhigh', 'max']}]}
for gateway in ({'status': 'ok', 'data': []}, {'status': 'unknown'}):
    direct['gateway'] = gateway
    p = probe(direct)
    assert p['capabilities']['codex']['models'] == {'gpt-6.1-sol': ['low', 'high', 'xhigh', 'max']}
    assert p['sources']['codex']['status'] == 'ok' and p['sources']['codex']['route'] == 'direct'
    assert p['capabilities']['pi']['models'] == {}
    assert p['gateway']['status'] == ('ok' if gateway['status'] == 'ok' else 'unreachable')
assert mc.capability_errors('codex', 'gpt-6.1-sol', 'high', p['capabilities']) == []
config = mc.valid_fixture()
config['work']['backend'] = {'agent': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high', 'fallbacks': []}
plan = mc.resolve_plan(config, 'backend', evidence=p['capabilities'], output_mode='commit')
argv = mc.startup_request(plan, worker_name='worker', pane_id='pane')
assert argv[argv.index('--model') + 1] == 'gpt-6.1-sol'
assert 'model_reasoning_effort="high"' in argv
for binary, route in ((True, None), (False, 'direct')):
    direct['harnesses']['codex'].update(binary=binary, route=route)
    p = probe(direct)
    assert p['capabilities']['codex']['models'] == {}
    assert p['sources']['codex']['status'] == 'unknown'
    assert p['sources']['codex']['reason']
    assert p['sources']['codex']['route'] == route
    if binary:
        assert '既不是本机网关也不是 OpenAI 官方' in p['sources']['codex']['reason']
print('probe contract and direct dispatch: pass')

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
# DD-616 R1–R4：预期来自 Spec；凭据为合成哨兵。
assert callable(getattr(mc, 'claude_endpoint', None)), '缺少 Claude 地址与凭据解析'
secret = 'fixture-oauth-secret'
oauth = {'accessToken': secret, 'expiresAt': 200000}
login_reason = '请先打开 Claude Code 完成登录后重新核对'
cases = [
    ({}, {}, oauth, 'official', 'https://api.anthropic.com', 'oauth'),
    ({'env': {'ANTHROPIC_BASE_URL': 'https://proxy.example'}}, {}, oauth, 'official', 'https://proxy.example', 'oauth'),
    ({'env': {'ANTHROPIC_BASE_URL': 'https://settings.example'}}, {'ANTHROPIC_BASE_URL': 'https://env.example'}, oauth, 'official', 'https://env.example', 'oauth'),
    ({}, {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:3425/v1'}, oauth, None, 'http://127.0.0.1:3425/v1', None),
    ({}, {}, {'accessToken': secret, 'expiresAt': 99999}, None, 'https://api.anthropic.com', None),
    ({}, {}, {'expiresAt': 200000}, None, 'https://api.anthropic.com', None),
    ({}, {}, None, None, 'https://api.anthropic.com', None),
    ({'env': {'ANTHROPIC_API_KEY': 'fixture-settings-key'}}, {'ANTHROPIC_AUTH_TOKEN': 'fixture-token'}, oauth, 'official', 'https://api.anthropic.com', 'api_key'),
    ({'env': {'ANTHROPIC_API_KEY': 'fixture-settings-key'}}, {'ANTHROPIC_API_KEY': 'fixture-env-key'}, oauth, 'official', 'https://api.anthropic.com', 'api_key'),
    ({'env': {'ANTHROPIC_AUTH_TOKEN': 'fixture-token'}}, {}, oauth, 'official', 'https://api.anthropic.com', 'auth_token'),
    ({'apiKeyHelper': 'do-not-execute'}, {}, oauth, None, 'https://api.anthropic.com', None),
]
for settings, env, credential, route, base, kind in cases:
    before = copy.deepcopy((settings, env, credential))
    endpoint = mc.claude_endpoint(settings, env, credential, 100)
    assert (endpoint['route'], endpoint['base_url'], endpoint['credential_kind']) == (route, base, kind)
    assert (settings, env, credential) == before
    serialized = json.dumps(endpoint)
    assert all(value not in serialized for value in (secret, 'fixture-settings-key', 'fixture-env-key', 'fixture-token'))
    if route is None:
        assert endpoint['reason']
        if not settings.get('apiKeyHelper') and not env.get('ANTHROPIC_BASE_URL'):
            assert endpoint['reason'] == login_reason
print('Claude endpoint table: pass')
# 2026-11-17 本机当前地址 /v1/models 实测裁剪，仅保留 id 与 effort。
assert callable(getattr(mc, 'claude_models', None)), '缺少 Claude 官方模型清单归一化'
claude_catalog = json.loads((root/'scripts/fixtures/claude-models.json').read_text())
expected_claude = {
    'claude-opus-5-5': ['low', 'medium', 'high', 'xhigh', 'max'],
    'claude-sonnet-4-6': ['low', 'medium', 'high', 'max'],
    'claude-opus-4-5-20251101': ['low', 'medium', 'high'],
}
assert mc.claude_models(claude_catalog) == [
    {'native_id': native, 'gateway_id': native, 'efforts': efforts}
    for native, efforts in expected_claude.items()]
for malformed in ({}, {'data': [{}]}, {'data': 'bad'}, {'data': [{'id': 'm', 'capabilities': []}]}):
    try:
        mc.claude_models(malformed)
    except ValueError as error:
        assert secret not in str(error)
    else:
        raise AssertionError('结构不符必须拒绝')
print('Claude official catalog: pass')
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
official = copy.deepcopy(raw)
official['harnesses']['claude'] = {'binary': True, 'route': 'official', 'models': mc.claude_models(claude_catalog)}
for gateway in ({'status': 'ok', 'data': []}, {'status': 'unknown'}):
    official['gateway'] = gateway
    p = probe(official)
    assert p['capabilities']['claude']['models'] == expected_claude
    assert p['sources']['claude']['status'] == 'ok' and p['sources']['claude']['route'] == 'official'
    assert p['gateway']['status'] == ('ok' if gateway['status'] == 'ok' else 'unreachable')
assert mc.capability_errors('claude', 'claude-opus-5-5', 'high', p['capabilities']) == []
assert mc.capability_errors('claude', 'claude-sonnet-4-6', 'xhigh', p['capabilities'])
config = mc.valid_fixture()
config['work']['backend'] = {'agent': 'claude', 'model': 'claude-opus-5-5', 'effort': 'high', 'fallbacks': []}
plan = mc.resolve_plan(config, 'backend', evidence=p['capabilities'], output_mode='commit')
argv = mc.startup_request(plan, worker_name='worker', pane_id='pane')
assert argv[argv.index('--model') + 1] == 'claude-opus-5-5'
assert argv[argv.index('--effort') + 1] == 'high'
for reason in (login_reason, 'Claude Code 指向本机网关，暂不支持通过网关核对 Claude 模型', '无法读取 Claude 官方模型清单'):
    official['harnesses']['claude'].update(route=None, reason=reason)
    p = probe(official)
    assert p['capabilities']['claude']['models'] == {}
    assert p['sources']['claude']['status'] == 'unknown' and p['sources']['claude']['reason'] == reason
print('Claude official probe and dispatch: pass')
# 外部系统边界替身：读文件/钥匙串与 HTTP；不执行 apiKeyHelper，不请求推理。
import io, os, tempfile, urllib.request
from types import SimpleNamespace
from unittest.mock import patch
with tempfile.TemporaryDirectory() as directory:
    home = Path(directory)
    (home/'.claude').mkdir()
    settings_path = home/'.claude/settings.json'
    settings_path.write_text('{}')
    calls = []
    requests = []
    def command(args, **kwargs):
        calls.append(args)
        if args[0] == 'security':
            return SimpleNamespace(returncode=0, stdout=json.dumps({'claudeAiOauth': {'accessToken': secret, 'expiresAt': 9999999999999}}))
        return SimpleNamespace(returncode=0, stdout='2.1.326' if '--version' in args else '')
    def request(req, **kwargs):
        requests.append((req, kwargs))
        return io.BytesIO(json.dumps(claude_catalog).encode())
    with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {}, clear=True), patch('sys.platform', 'darwin'), patch('shutil.which', side_effect=lambda name: '/fake/'+name), patch('subprocess.run', side_effect=command), patch('urllib.request.urlopen', side_effect=request):
        collected = mc.collect_harnesses()
        assert collected['claude']['route'] == 'official'
        assert collected['claude']['models'] == mc.claude_models(claude_catalog)
        assert len(requests) == 1 and requests[0][0].full_url == 'https://api.anthropic.com/v1/models?limit=1000'
        assert requests[0][0].get_method() == 'GET' and requests[0][1]['timeout'] == 15
        assert requests[0][0].get_header('Authorization') == 'Bearer '+secret
        assert requests[0][0].get_header('Anthropic-beta') == 'oauth-2025-04-20'
        assert secret not in json.dumps(mc.probe({'harnesses': collected}, 'safe'))
        for name, kind in (('ANTHROPIC_API_KEY', 'X-api-key'), ('ANTHROPIC_AUTH_TOKEN', 'Authorization')):
            requests.clear()
            with patch.dict(os.environ, {name: secret}):
                result = mc.collect_harnesses()['claude']
            assert result['route'] == 'official' and len(requests) == 1
            assert requests[0][0].get_header(kind) == (secret if name.endswith('API_KEY') else 'Bearer '+secret)
            assert secret not in json.dumps(result)
        with patch('urllib.request.urlopen', side_effect=OSError(secret)):
            result = mc.collect_harnesses()['claude']
            assert result['route'] is None and '无法读取' in result['reason']
            assert secret not in json.dumps(result)
        import urllib.error
        with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('https://example.invalid', 401, secret, {}, None)):
            result = mc.collect_harnesses()['claude']
            assert result['route'] is None and result['reason'] == login_reason
            assert secret not in json.dumps(result)
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='')):
            requests.clear()
            result = mc.collect_harnesses()['claude']
            assert result['route'] is None and result['reason'] == login_reason and not requests
        (home/'.claude/.credentials.json').write_text(json.dumps({'claudeAiOauth': {'accessToken': secret, 'expiresAt': 9999999999999}}))
        with patch('sys.platform', 'linux'):
            requests.clear()
            result = mc.collect_harnesses()['claude']
            assert result['route'] == 'official' and len(requests) == 1
        for settings in ({'apiKeyHelper': 'never-run'}, {'env': {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:3425/v1'}}):
            settings_path.write_text(json.dumps(settings))
            requests.clear()
            assert mc.collect_harnesses()['claude']['route'] is None
            assert not requests
print('Claude collection request and credential isolation: pass')

assert callable(getattr(mc, 'antigravity_cli_models', None)), '缺少 Antigravity CLI 模型清单归一化'
assert callable(getattr(mc, 'antigravity_models', None)), '缺少 Antigravity 本地缓存模型清单归一化'
assert callable(getattr(mc, 'antigravity_source', None)), '缺少 Antigravity 提供方来源解析'
ag_cli_output = '\n'.join([
    'gemini-4-neon-high\tGemini 4 Neon (High)',
    'gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)',
    'gemini-4-neon-medium\tGemini 4 Neon (Medium)',
    'gemini-4-neon-low\tGemini 4 Neon (Low)',
    'gemini-4-carbon-high\tGemini 4 Carbon (High)',
    'gemini-4-carbon-low\tGemini 4 Carbon (Low)',
    'gemini-4-carbon-medium\tGemini 4 Carbon (Medium)',
    'gemini-pro-orchestrator-neon\tOrchestrator (Neon)',
    'claude-opus-5-5-low\tClaude Opus 5.5 (Low)',
    'claude-opus-5-5-medium\tClaude Opus 5.5 (Medium)',
    'claude-opus-5-5-high\tClaude Opus 5.5 (High)',
    'gpt-oss-120b-medium\tGPT-OSS 120B (Medium)',
])
expected_ag_cli = {
    'gemini-4-neon': ['low', 'medium', 'high', 'xhigh'],
    'gemini-4-carbon': ['low', 'medium', 'high'],
    'claude-opus-5-5': ['low', 'medium', 'high'],
    'gpt-oss-120b': ['medium'],
}
assert mc.antigravity_cli_models(ag_cli_output) == [
    {'native_id': native, 'gateway_id': native, 'efforts': efforts}
    for native, efforts in expected_ag_cli.items()]
ag_cache = json.loads((root/'scripts/fixtures/antigravity-cache.json').read_text())
expected_ag = {
    'gemini-4-neon': ['low', 'medium', 'high', 'xhigh'],
    'gemini-4-carbon': ['low', 'medium', 'high'],
    'gemini-pro-orchestrator-neon': ['low', 'medium', 'high', 'xhigh'],
    'claude-opus-5-5': ['low', 'medium', 'high'],
    'gpt-oss-120b-medium': ['low', 'medium', 'high'],
}
assert mc.antigravity_models(ag_cache) == [
    {'native_id': native, 'gateway_id': native, 'efforts': efforts}
    for native, efforts in expected_ag.items()]
for malformed in ({}, {'models': 'bad'}, {'models': [{}]}, {'models': [{'slug': 'm', 'capabilities': []}]}):
    try:
        mc.antigravity_models(malformed)
    except ValueError:
        pass
    else:
        raise AssertionError('Antigravity 非法结构必须拒绝')
for ag_route, harness_data, expected_map in (
    ('cli', {'binary': True, 'route': 'cli', 'models': mc.antigravity_cli_models(ag_cli_output)}, expected_ag_cli),
    ('cache', mc.antigravity_source(ag_cache), expected_ag),
):
    ag_probe = copy.deepcopy(raw)
    ag_probe['harnesses']['antigravity'] = harness_data
    for gateway in ({'status': 'ok', 'data': []}, {'status': 'unknown'}):
        ag_probe['gateway'] = gateway
        p = probe(ag_probe)
        assert p['capabilities']['antigravity']['models'] == expected_map
        assert p['sources']['antigravity']['status'] == 'ok' and p['sources']['antigravity']['route'] == ag_route
        assert p['gateway']['status'] == ('ok' if gateway['status'] == 'ok' else 'unreachable')
assert mc.capability_errors('antigravity', 'gemini-4-neon', 'xhigh', p['capabilities']) == []
assert mc.capability_errors('antigravity', 'gemini-4-carbon', 'xhigh', p['capabilities'])
ag_config = mc.valid_fixture()
ag_config['work']['backend'] = {'agent': 'antigravity', 'model': 'gemini-4-neon', 'effort': 'xhigh', 'fallbacks': []}
ag_plan = mc.resolve_plan(ag_config, 'backend', evidence=p['capabilities'], output_mode='commit')
assert (ag_plan['agent'], ag_plan['model'], ag_plan['effort']) == ('antigravity', 'gemini-4-neon', 'xhigh')
ag_argv = mc.startup_request(ag_plan, worker_name='worker', pane_id='pane')
assert ag_argv == [
    'herdr', 'agent', 'start', 'worker', '--kind', 'agy', '--pane', 'pane', '--',
    '--model', 'gemini-4-neon', '--effort', 'xhigh', '--dangerously-skip-permissions',
], ag_argv
assert mc.antigravity_source(ag_cache, {'providerInstances': {'antigravity': {'enabled': False}}})['route'] is None
for mutate in (
    lambda c: c.update(enabled=False),
    lambda c: c.update(installed=False),
    lambda c: c.update(status='disabled'),
    lambda c: c.update(auth={'status': 'unauthenticated'}),
    lambda c: c.update(driver='other'),
):
    mutated = copy.deepcopy(ag_cache)
    mutate(mutated)
    state = mc.antigravity_source(mutated)
    assert state['route'] is None and state['models'] == [] and state['reason']
with tempfile.TemporaryDirectory() as directory:
    home = Path(directory)
    (home/'.t3/caches').mkdir(parents=True)
    (home/'.t3/userdata').mkdir(parents=True)
    cache_with_secret = {**ag_cache, 'usageLimits': {'credentialFingerprint': secret}}
    (home/'.t3/caches/antigravity.json').write_text(json.dumps(cache_with_secret))
    (home/'.t3/userdata/settings.json').write_text(json.dumps({'providerInstances': {'antigravity': {'enabled': True}}}))
    def fake_agy(args, **kwargs):
        if Path(args[0]).name in ('agy', 'antigravity') and args[1:] == ['models']:
            return SimpleNamespace(returncode=0, stdout=ag_cli_output)
        return SimpleNamespace(returncode=1, stdout='')
    with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {}, clear=True), patch('shutil.which', side_effect=lambda name: '/fake/agy' if name == 'agy' else None), patch('subprocess.run', side_effect=fake_agy):
        cli_collected = mc.collect_harnesses()['antigravity']
        assert cli_collected['route'] == 'cli' and cli_collected['binary'] is True
        assert cli_collected['models'] == mc.antigravity_cli_models(ag_cli_output)
    with patch.object(Path, 'home', return_value=home), patch.dict(os.environ, {}, clear=True), patch('shutil.which', return_value=None):
        collected = mc.collect_harnesses()['antigravity']
        assert collected['route'] == 'cache' and collected['binary'] is True
        assert collected['models'] == mc.antigravity_models(ag_cache)
        assert secret not in json.dumps(mc.probe({'harnesses': {'antigravity': collected}}, 'ag-safe'))
        (home/'.t3/userdata/settings.json').write_text(json.dumps({'providerInstances': {'antigravity': {'enabled': False}}}))
        disabled = mc.collect_harnesses()['antigravity']
        assert disabled['route'] is None and disabled['binary'] is True and '启用' in disabled['reason']
        (home/'.t3/caches/antigravity.json').unlink()
        missing = mc.collect_harnesses()['antigravity']
        assert missing['route'] is None and missing['binary'] is False and missing['reason']
print('Antigravity probe and isolation: pass')

#!/usr/bin/env python3
"""Herdr Adapter 逐身份只读 Native Preflight。仅进程 I/O 为外部边界。"""
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _command(argv, *, payload=None):
    try:
        p = subprocess.run(argv, input=payload, text=True, capture_output=True, timeout=20)
        return {'argv': argv, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'argv': argv, 'exit': None, 'stdout': '', 'stderr': type(e).__name__}


def preflight_review_candidates(ordered_pools, request_id):
    """每次从原生来源重新采集，外部自述 JSON 无授权效力。重复按位置保留。"""
    observed = datetime.now(timezone.utc).isoformat()
    sources = []
    def capture(argv, payload=None):
        raw = _command(argv, payload=payload)
        sources.append(raw)
        return raw
    herdr = shutil.which('herdr')
    version = capture([herdr, '--version']) if herdr else None
    help_ = capture([herdr, 'agent', 'start', '--help']) if herdr else None
    # 窄合同：当前已调查版本、支持 pi 与显式 AGENT_ARG 透传。
    kinds = re.search(r'\[possible values: ([^\]]+)\]', help_['stdout']) if help_ else None
    transport_ok = bool(kinds and 'pi' in [k.strip() for k in kinds[1].split(',')] and version and version['exit'] == 0 and version['stdout'].strip() == 'herdr 0.9.5'
        and help_['exit'] == 0 and '-- [AGENT_ARG]' in help_['stdout'])
    if herdr:
        sources.append({'herdr_binary':str(Path(herdr).resolve()), 'sha256':_digest(Path(herdr).read_bytes())})
    identities = [x for pool in ordered_pools.values() for x in pool]
    native = {}
    pi = shutil.which('pi')
    if pi and any(x['agent'] == 'pi' for x in identities):
        binary = Path(pi).resolve()
        package = binary.parent.parent.parent if binary.parent.name == 'bundle' else binary.parent.parent
        try:
            pi_version = capture([pi, '--version'])
            if pi_version['exit'] != 0 or pi_version['stdout'].strip() != '1.5.2':
                raise ValueError('Pi binary/source version mismatch')
            meta = json.loads((package/'package.json').read_text())
            if meta.get('name') != '@earendil-works/pi-coding-agent' or meta.get('version') != '1.5.2':
                raise ValueError('version-matched Pi source required')
            paths = [binary, Path.home()/'.pi/agent/models.json', package/'package.json', HERE/'native_review_probe.mjs',
                     *[package/p for p in ('dist/cli/args.js', 'dist/core/model-config.js',
                        'dist/core/model-resolver.js', 'node_modules/@earendil-works/pi-ai/dist/models.js')]]
            sources.append({'installed_sources': [{'path':str(p), 'sha256':_digest(p.read_bytes())} for p in paths]})
            selected = [x for x in identities if x['agent'] == 'pi']
            raw = capture([shutil.which('node') or 'node', str(HERE/'native_review_probe.mjs')],
                json.dumps({'package':str(package), 'models_path':str(Path.home()/'.pi/agent/models.json'),
                            'identities':selected}))
            if raw['exit'] == 0:
                rows = json.loads(raw['stdout'])
                if len(rows) == len(selected) and all(r.get('identity') == x for r,x in zip(rows,selected)):
                    native = {json.dumps(r['identity'],sort_keys=True):r for r in rows}
        except (OSError, ValueError, TypeError, KeyError):
            pass  # Unknown 保留，绝不合成 unavailable/runnable。
    capabilities = {}
    for axis,pool in ordered_pools.items():
        capabilities[axis] = []
        for index,identity in enumerate(pool):
            row = native.get(json.dumps(identity,sort_keys=True), {})
            status, reason = row.get('status','unknown'), row.get('reason','version-matched native parser source unavailable')
            if not transport_ok:
                status, reason = 'unknown', 'Herdr version/agent argument forwarding contract missing'
            binding = {'request_id':request_id, 'observed_at':observed, 'ordered_pools':ordered_pools,
                       'axis':axis,'index':index,'identity':identity,'sources':sources,'status':status,'reason':reason}
            capabilities[axis].append({'identity':identity,'status':status,'reason':reason,
                                      'evidence_id':_digest(json.dumps(binding,sort_keys=True).encode())})
    return {'request_id':request_id,'observed_at':observed,'ordered_pools':ordered_pools,
            'capabilities':capabilities,'sources':sources,
            'scope':'static native compatibility only; execution/auth/network/quota Unknown'}


if __name__ == '__main__':
    import argparse
    import importlib.util
    parser = argparse.ArgumentParser(description='Root 原 caller 只读采集；不创建 lane，不发推理')
    parser.add_argument('--config', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--required-axes', nargs='+', choices=['standards','spec'], required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('model_config', HERE.parents[1]/'delivery-pipeline-setup/scripts/model_config.py')
    mc = importlib.util.module_from_spec(spec); spec.loader.exec_module(mc)
    document = mc.load_document(Path(args.config))
    errors = mc.validate_document(document)
    if errors: parser.error('; '.join(errors))
    pools = {a:[mc.triple(cell), *cell['candidates']]
             for a in dict.fromkeys(['standards', *args.required_axes])
             if (cell := document['review']['whole-change'][a]).get('candidates')}
    # 空池保持旧路径，不额外读取 native 来源。
    result = preflight_review_candidates(pools,args.request_id) if pools else {'capabilities':{}, 'scope':'single-model legacy preflight'}
    print(json.dumps(result,ensure_ascii=False))

"""版本匹配的 Pi 纯 parser/model/effort 采集；不包含 transport 放行规则。"""
import hashlib
import json
import shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent

def _digest(data):
    return hashlib.sha256(data).hexdigest()

def collect_pi(identities, capture, sources):
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
            before = {str(p):_digest(p.read_bytes()) for p in paths}
            selected = [x for x in identities if x['agent'] == 'pi']
            raw = capture([shutil.which('node') or 'node', str(HERE/'native_review_probe.mjs')],
                json.dumps({'package':str(package), 'models_path':str(Path.home()/'.pi/agent/models.json'),
                            'identities':selected}))
            if raw['exit'] == 0 and all(_digest(Path(p).read_bytes())==digest for p,digest in before.items()):
                rows = json.loads(raw['stdout'])
                if len(rows) == len(selected) and all(r.get('identity') == x for r,x in zip(rows,selected)):
                    native = {json.dumps(r['identity'],sort_keys=True):r for r in rows}
        except (OSError, ValueError, TypeError, KeyError):
            pass  # Unknown 保留，绝不合成 unavailable/runnable。
    return native

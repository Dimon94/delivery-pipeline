"""Pi 纯 parser/model/effort 采集；不包含 transport 放行规则。
不按 Pi 版本号设门：Harness 会持续升级，原生接口仍能加载并给出判定即有效；接口变了探针失败才是 Unknown。"""
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
            capture([pi, '--version'])  # 版本号只作证据记录。
            meta = json.loads((package/'package.json').read_text())
            if meta.get('name') != '@earendil-works/pi-coding-agent':
                raise ValueError('Pi package source required')
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

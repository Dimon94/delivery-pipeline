"""唯一 Registry 文件上的合作写者事务；无第二份 ledger。"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from lane_graph import parse_registry_file
from replacement import decide

JSON_FIELDS = {'recovery_plan', 'recovery_progress', 'replacement_intent', 'herdr', 'orca', 't3code', 'lody'}


def rows(path):
    latest = {}
    if path.exists():
        for row in parse_registry_file(path):
            row.pop('_file', None)
            for key in JSON_FIELDS:
                if isinstance(row.get(key), str):
                    row[key] = json.loads(row[key])
            latest[row['lane_id']] = row
    return latest


def revision(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path, lane):
    row = rows(Path(path))[lane]
    return row, revision(row)


@contextmanager
def lock(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path)+'.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield path


def persist(path, updates):
    text = path.read_text() if path.exists() else ''
    for row in updates:
        lines = ['<!-- wayfinder-lane-registry:v2 -->', '```yaml']
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
            if '\n' in str(value) or '\r' in str(value):
                raise ValueError('registry values must be single-line')
            lines.append(f"{key}: {'none' if value is None else value}")
        text += '\n'+'\n'.join([*lines, '```'])+'\n'
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name+'.')
    try:
        with os.fdopen(fd,'w') as h:
            h.write(text)
            h.flush()
            os.fsync(h.fileno())
        os.replace(name,path)
        if path.read_text()!=text:
            raise ValueError('registry commit_unverified: inspect before retry')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write(path, row):
    with lock(path) as path:
        all_rows = rows(path)
        current = all_rows.get(row['lane_id'])
        if any(r['lane_id']!=row['lane_id'] and r.get('work_item')==row.get('work_item') and
               (r.get('state') in {'created','running','awaiting_human'} or
                r.get('replacement_intent',{}).get('status') in {'accepted','launching'})
               for r in all_rows.values()):
            raise ValueError('work_item already has an active writer or accepted intent')
        if any(r.get('replacement_of') == row['lane_id'] for r in all_rows.values()):
            raise ValueError('source already superseded by accepted intent')
        frozen_keys=('work_item','mode','agent','model','effort','recovery_plan','recovery_progress','replacement_of','failure_id','failure_category')
        # v2 parser 把顶层 none 规范化为 None。
        normalized={k:(None if row.get(k)=='none' else row.get(k)) for k in frozen_keys}
        if current and any(current.get(k)!=normalized[k] for k in frozen_keys):
            raise ValueError('frozen execution identity/position is immutable outside claim')
        if row.get('replacement_intent') or row.get('replacement_of') or (current and current.get('replacement_intent')):
            if not current or row.get('replacement_intent')!=current.get('replacement_intent'):
                raise ValueError('intent changes require claim/launch/recover')
        persist(path,[row])


def safe(observed):
    expected = dict(writer='exited', identity='match', capability='verified', gate='allowed')
    if any(observed.get(k)!=v for k,v in expected.items()):
        raise ValueError('inspect: writer/identity/capability/native gate unverified')


def claim(path, source_id, expected_revision, failure_id, category, observe):
    if not isinstance(failure_id,str) or not failure_id.strip():
        raise ValueError('stable failure_id required')
    with lock(path) as path:
        all_rows=rows(path)
        source=all_rows[source_id]
        successors=[r for r in all_rows.values() if r.get('replacement_of')==source_id]
        if successors:
            if len(successors)!=1 or successors[0].get('failure_id')!=failure_id or successors[0].get('failure_category')!=category:
                raise ValueError('source already claimed by another failure')
            return successors[0]
        if revision(source)!=expected_revision:
            raise ValueError('row revision conflict')
        if category in {'outcome_unknown', 'cancelled', 'context_exhausted'}:
            raise ValueError(decide(source,category,0)['action'])
        safe(observe(deepcopy(source)))
        related=[r for r in all_rows.values() if r.get('work_item')==source['work_item']]
        if sum(not r.get('replacement_of') for r in related)>1:
            raise ValueError('inspect: ambiguous work_item lineage')
        if any(r['lane_id']!=source_id and (r.get('state') in {'created','running','awaiting_human'} or
               r.get('replacement_intent',{}).get('status') in {'accepted','launching'}) for r in related):
            raise ValueError('inspect: other active writer or pending intent')
        if source.get('replacement_intent',{}).get('status') in {'accepted','launching'}:
            raise ValueError('inspect: original launch unresolved')
        if (category=='startup_failed' and source.get('replacement_intent')
                and source['replacement_intent'].get('status')!='failed'):
            raise ValueError('inspect: positive original startup rejection required')
        decision=decide(source,category,sum(bool(r.get('replacement_of')) for r in related))
        if decision['action']!='replace':
            if decision['action']=='exhausted':
                source['state']='blocked'
                persist(path,[source])
            raise ValueError(decision['action'])
        identity=hashlib.sha256((source_id+'\0'+failure_id).encode()).hexdigest()[:24]
        lane='r-'+identity
        if lane in all_rows:
            raise ValueError('successor identity conflict')
        successor=deepcopy(source)
        for key in ('herdr','orca','t3code','lody','replacement_intent','blocker','head_commit','integrated_commit'):
            successor.pop(key,None)
        successor.update({k:v for k,v in decision.items() if k!='action'})
        successor.update(lane_id=lane,replacement_of=source_id,failure_id=failure_id,failure_category=category,
                         state='created',replacement_intent=dict(request_id=lane,status='accepted'))
        source['state']='blocked'
        persist(path,[source,successor])
        actual,_=read(path,lane)
        if actual!=successor:
            raise ValueError('intent readback mismatch')
        return actual


def finish(path,row,result):
    if result.get('status')=='unknown' and result.get('receipt'):
        row['replacement_intent']['receipt']=result['receipt']
        persist(path,[row])
        return read(path,row['lane_id'])[0]
    if result.get('status') not in {'completed','failed'} or not result.get('receipt'):
        return row
    row['replacement_intent'].update(status=result['status'],receipt=result['receipt'])
    row['state']='running' if result['status']=='completed' else 'setup_blocked'
    persist(path,[row])
    return read(path,row['lane_id'])[0]


def bind_request(path,lane,request,observe,*,runtime=None):
    with lock(path) as path:
        row,_=read(path,lane)
        intent=row['replacement_intent']
        if 'native_request' in intent:
            if intent['native_request']!=request or (runtime is not None and row['runtime']!=runtime):
                raise ValueError('native request identity conflict')
            return row
        if intent['status']!='accepted':
            raise ValueError('inspect: launch already attempted')
        source,_=read(path,row['replacement_of'])
        safe(observe(deepcopy(source)))
        intent['native_request']=deepcopy(request)
        if runtime is not None:
            row['runtime']=runtime
        persist(path,[row])
        return read(path,lane)[0]


def launch(path,lane,observe,start):
    with lock(path) as path:
        row,_=read(path,lane)
        intent=row['replacement_intent']
        if intent['status']!='accepted':
            return row
        source,_=read(path,row['replacement_of'])
        safe(observe(deepcopy(source)))
        if not intent.get('native_request'):
            raise ValueError('native request must be bound before launch')
        intent['status']='launching'
        persist(path,[row])
        row,_=read(path,lane)
        return finish(path,row,start(deepcopy(row)))


def recover_launch(path,lane,reconcile):
    with lock(path) as path:
        row,_=read(path,lane)
        if row['replacement_intent']['status']!='launching':
            return row
        return finish(path,row,reconcile(deepcopy(row)))

"""已审核的父票合同、执行回执和集成场景。Driver 拥有状态迁移。"""
import re
import subprocess


SHA = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')


def has_briefs(ticket):
    # 普通票允许省略或保留空数组；其他值交给 frozen 核验。
    return ticket.get('briefs', ()) not in ((), [])


def frozen(ticket):
    briefs = ticket.get('briefs')
    if not isinstance(briefs, (list, tuple)) or not briefs or not all(hasattr(b, 'get') for b in briefs):
        raise ValueError(f"{ticket['id']} 缺少冻结合同")
    ids = [b.get('slice_id') for b in briefs if b.get('ticket') == ticket['id']]
    if not all(isinstance(s, str) and s.strip() for s in ids) or len(set(ids)) != len(briefs):
        raise ValueError(f"{ticket['id']} 合同父票或片标识错误")
    check = ticket.get('scenario_check')
    if not isinstance(check, (tuple, list)) or not check or not all(isinstance(s, str) and s for s in check):
        raise ValueError(f"{ticket['id']} 缺少整票场景命令")
    return {b['slice_id']: b for b in briefs}


def complete(ticket, rows):
    ids = frozen(ticket)
    return set(ids) == {r.get('slice_id') for r in rows if r.get('state') in ('integrated', 'closed', 'close_pending')}


def batch(tickets, by_item, done, answers):
    jobs, writes = [], set()
    role = None
    for ticket in tickets:
        if not has_briefs(ticket) or not all(done(dep) for dep in ticket.get('deps', ())):
            continue
        if ticket.get('hitl') and ticket['id'] not in answers:
            continue
        task = ticket.get('task', 'backend')
        if role is not None and task != role:
            continue
        existing = {r.get('slice_id') for r in by_item.get(ticket['id'], ())}
        for sid, brief in frozen(ticket).items():
            if sid in existing or writes.intersection(brief['writable']):
                continue
            jobs.append(brief)
            writes.update(brief['writable'])
            role = task
    return role, jobs


def git(tree, *args):
    p = subprocess.run(['git', '-C', str(tree), *args], text=True, capture_output=True)
    if p.returncode:
        raise ValueError(p.stderr.strip() or 'git ' + args[0] + ' 失败')
    return p.stdout.strip()


def verify_rows(jobs, records, owner, integration, role, map_lane):
    expected = {(b['ticket'], b['slice_id']): b for b in jobs}
    rows = []
    for r in records:
        key = (r['ticket'], r['slice_id'])
        b = expected.pop(key, None)
        head, tree = r['head'], r['worktree']
        proof = r['run']
        if (b != r['brief'] or r['owner'] != str(owner) or r['state'] != 'ready'
                or not SHA.fullmatch(head) or r['marker'] != f"LANE_DONE {r['name']} {head}"
                or r['base'] != b['base'] or head == b['base'] or proof['base'] != head
                or proof['ok'] is not True or proof['check'] != b['check'] or not proof['observed']
                or git(tree, 'rev-parse', 'HEAD') != head or git(tree, 'status', '--porcelain')
                or git(tree, 'symbolic-ref', '--short', 'HEAD') != r['branch']
                or git(integration, 'rev-parse', r['branch'] + '^{commit}') != head):
            raise ValueError(f'{key} 的回执与冻结合同或现场不符')
        git(integration, 'merge-base', '--is-ancestor', b['base'], head)
        identity = r['execution']
        rows.append(dict(agent=identity['agent'], model=identity['model'], effort=identity['effort'],
                         max_turns=identity['max_turns'], lane_id=r['name'], work_item=key[0], slice_id=key[1], role=role,
                         output_mode='commit', state='terminal', head_commit=head, base_commit=b['base'], map=map_lane,
                         branch=r['branch'], worktree=tree, attempts=r['attempts']))
    if expected:
        raise ValueError(f'缺少执行片 {list(expected)}')
    return rows


def integrate(tree, row, target):
    head = row['head_commit']
    if (git(tree, 'symbolic-ref', '--short', 'HEAD') != target or git(tree, 'status', '--porcelain')
            or git(tree, 'rev-parse', row['branch'] + '^{commit}') != head):
        raise ValueError('集成目标或已验收分支发生变化')
    git(tree, 'merge-base', '--is-ancestor', row['base_commit'], 'HEAD')
    # merge 保留完整提交链；崩溃后按祖先关系对账，已收取的片直接读回。
    git(tree, 'merge', '--no-ff', '--no-edit', head)
    git(tree, 'merge-base', '--is-ancestor', head, 'HEAD')
    return {'state': 'integrated', 'integrated_commit': git(tree, 'rev-parse', 'HEAD')}


def scenario(tree, ticket, rows, target):
    head = git(tree, 'rev-parse', 'HEAD')
    if not complete(ticket, rows) or git(tree, 'symbolic-ref', '--short', 'HEAD') != target or git(tree, 'status', '--porcelain'):
        raise ValueError('整票验收缺少已集成片或干净的集成分支')
    for r in rows:
        git(tree, 'merge-base', '--is-ancestor', r['head_commit'], head)
    check = ticket['scenario_check']
    p = subprocess.run(check, cwd=tree, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    observed = p.stdout.strip()[:4096]
    ok = p.returncode == 0 and bool(observed) and git(tree, 'rev-parse', 'HEAD') == head and not git(tree, 'status', '--porcelain')
    return dict(ok=ok, base=head, check=check, observed=observed, exit_code=p.returncode)

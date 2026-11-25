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
                         branch=r['branch'], worktree=tree, attempts=r['attempts'], worker_reports=r.get('worker_reports', [])))
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


# ---------- 派发合同：每张 commit 票一份，执行通道不变 ----------

def contract(ticket_id, briefs):
    """校验 delegate-ticket 交回的合同：恰好一份，绑定本票，范围与验收齐全。"""
    if not isinstance(briefs, list) or len(briefs) != 1 or not isinstance(briefs[0], dict):
        raise ValueError('派发合同恰好一份；要拆片回计划阶段写 briefs 与 scenario_check')
    b = briefs[0]
    paths = [b.get(k) for k in ('writable', 'read_first', 'check')]
    if (b.get('ticket') != ticket_id or not isinstance(b.get('expected'), str) or not b['expected'].strip()
            or not all(isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v) for v in paths)):
        raise ValueError('派发合同缺票号、可写文件、先读文件、验收命令或期望结果')
    return b


def packet(b):
    """合同 → 派发包的范围、验收、输入；两个壳逐字使用。"""
    return dict(scope='只改 ' + '、'.join(b['writable']),
                acceptance=f"在交付提交上运行 {' '.join(b['check'])}；期望：{b['expected']}",
                inputs='先读 ' + '、'.join(b['read_first']))


def covers(entry, path):
    """可写范围的一项是精确文件，或以 `/` 结尾的目录（与 delegate-ticket 的 prepare.js 同义）。"""
    return entry == path or (entry.endswith('/') and path.startswith(entry))


def audit(integration, row, b, commit):
    """交付提交对照合同：返回 (违约原因或 None, 越出可写范围的文件)。执行者的自述不参与判定。

    空变更与验收不过是违约，不进集成分支。越界只记偏差：新文件的名字派发前常定不准，先量再拦（ADR-0028）。"""
    tree, outside = row.get('worktree'), []
    try:
        base = git(integration, 'merge-base', 'HEAD', commit)
        changed = git(integration, 'diff', '--name-only', '--no-renames', base, commit).splitlines()
        outside = sorted(f for f in changed if not any(covers(e, f) for e in b['writable']))
        if not changed:
            return '合同违约：净变更为空', outside
        if not tree or git(tree, 'rev-parse', 'HEAD') != commit:
            return '合同违约：执行工作树的 HEAD 不是交付提交', outside
        rc = subprocess.run(b['check'], cwd=tree, stdin=subprocess.DEVNULL, capture_output=True).returncode
        if rc or git(tree, 'rev-parse', 'HEAD') != commit or git(tree, 'status', '--porcelain'):
            return f'合同违约：验收命令退出 {rc}，或验收后工作树不干净', outside
    except (ValueError, OSError) as error:
        return f'合同违约：无法核对（{error}）', outside
    return None, outside

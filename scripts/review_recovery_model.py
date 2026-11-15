"""DD515 有界模型：同一 request、两个调用者、持久启动前缀和取消。

reserve 对应唯一 Registry 锁内占位，launching 先于外部 start，恢复只读。
DD519 Orca 映射：review_dispatch freeze 复用 reserve_review（accepted），原生调用前
既有 registry_overlay.record_mutation 对应 intent/launching；recover 只返回原 orca
mutation/receipt，不执行 retry。原生操作由 Root，模型不证明其遵守调用顺序。
未扩张状态空间或原生 exactly-once 结论；真实临时 Registry 的取消/重复检查见
Orca check_review_dispatch --case native-unknown。
假设合作写者/本地 flock/原子 replace；不证明 native exactly-once 或模型身份。
"""
from collections import deque


def explore(broken=None):
    # owner, phase, attempts, cancelled, config_revision
    initial = (-1, 'empty', 0, False, 0)
    seen = {initial}
    queue = deque([initial])
    while queue:
        owner, phase, attempts, cancelled, config = queue.popleft()
        assert attempts <= 1, '第二启动副作用'
        assert not (cancelled and phase == 'replaced'), '取消后换候选'
        assert phase != 'reselected', '恢复重选'
        nxt = []
        for actor in range(2):
            if phase == 'empty':
                nxt.append((actor, 'accepted', attempts, cancelled, config))
            elif broken == 'duplicate' and owner != actor:
                nxt.append((actor, 'completed', attempts + 1, cancelled, config))
        if phase == 'accepted' and not cancelled:
            nxt.append((owner, 'launching', attempts, cancelled, config))
        if phase == 'launching' and not cancelled:
            nxt.append((owner, 'started', attempts + 1, cancelled, config))
        if phase == 'started':
            nxt.append((owner, 'completed', attempts, cancelled, config))
        # 崩溃/response lost 重入只 inspect；没有重发边。
        if phase in {'started', 'completed'} and broken == 'resend':
            nxt.append((owner, 'started', attempts + 1, cancelled, config))
        if phase != 'empty':
            nxt.append((owner, phase, attempts, True, config))
            if config == 0:
                nxt.append((owner, phase, attempts, cancelled, 1))
            if broken == 'reselect' and config:
                nxt.append((owner, 'reselected', attempts, cancelled, config))
            if broken == 'cancel' and cancelled:
                nxt.append((owner, 'replaced', attempts, cancelled, config))
        for state in nxt:
            if state not in seen:
                seen.add(state)
                queue.append(state)
    return len(seen)


def explore_rounds(broken=None):
    """原账本最多 R1–R3；同 head 复用无副作用，新 head 仅 FIX+修复者。"""
    seen=set()
    queue=deque([(1, 'FIX', 'h1')])
    while queue:
        number,outcome,head=queue.popleft()
        if (number,outcome,head) in seen: continue
        seen.add((number,outcome,head))
        for same in (False,True):
            for fixer in (False,True):
                for cancelled in (False,True):
                    allowed=(outcome=='FIX' and number<3 and fixer and not same and not cancelled)
                    actual=allowed
                    if broken=='budget' and number==3: actual=True
                    if broken=='terminal' and outcome!='FIX': actual=True
                    if broken=='fixer' and not fixer: actual=True
                    if broken=='reuse' and same: actual=True
                    if broken=='cancel-round' and cancelled: actual=True
                    assert not actual or allowed, '非法后轮启动'
                    if actual:
                        for result in ('FIX','PASS','REVIEW_BLOCKED','REVIEW_EXHAUSTED'):
                            queue.append((number+1,result,'h'+str(number+1)))
    return len(seen)


def main():
    count = explore()
    rounds=explore_rounds()
    for variant in ('budget','terminal','fixer','reuse','cancel-round'):
        try: explore_rounds(variant)
        except AssertionError: continue
        raise AssertionError('未拒绝后轮错误模型 '+variant)
    print(f'later round bounded model: pass ({rounds} states; 5 broken variants rejected)')
    for variant in ('duplicate', 'resend', 'reselect', 'cancel'):
        try:
            explore(variant)
        except AssertionError:
            continue
        raise AssertionError('未拒绝错误模型 '+variant)
    print(f'review recovery bounded model: pass ({count} states; 4 broken variants rejected)')


if __name__ == '__main__':
    main()

"""DD515 有界模型：同一 request、两个调用者、持久启动前缀和取消。

reserve 对应唯一 Registry 锁内占位，launching 先于外部 start，恢复只读。
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


def main():
    count = explore()
    for variant in ('duplicate', 'resend', 'reselect', 'cancel'):
        try:
            explore(variant)
        except AssertionError:
            continue
        raise AssertionError('未拒绝错误模型 '+variant)
    print(f'review recovery bounded model: pass ({count} states; 4 broken variants rejected)')


if __name__ == '__main__':
    main()

from itertools import combinations, permutations

from core.ovr import POSITIONS


def best_assignment(team: list) -> tuple[int, tuple] | None:
    """5명에게 5포지션을 배정해 오버롤 합이 최대가 되는 조합.
    고정 포지션 제약을 만족하는 조합이 없으면 None."""
    best_sum, best_perm = -1, None
    for perm in permutations(POSITIONS):
        if any(p["lock"] and perm[i] != p["lock"] for i, p in enumerate(team)):
            continue
        total = sum(team[i]["ovr"][perm[i]] for i in range(len(team)))
        if total > best_sum:
            best_sum, best_perm = total, perm
    return None if best_perm is None else (best_sum, best_perm)


def balance(players: list) -> tuple | None:
    """10명을 5:5로 나누고 각 팀의 최적 포지션 배정을 찾는다.
    고정 포지션이 충돌해 가능한 배치가 하나도 없으면 None."""
    idx = list(range(len(players)))
    best = None

    for rest in combinations(idx[1:], 4):
        a = (idx[0],) + rest
        b = tuple(i for i in idx if i not in a)

        ra = best_assignment([players[i] for i in a])
        if ra is None:
            continue
        rb = best_assignment([players[i] for i in b])
        if rb is None:
            continue

        (sum_a, pos_a), (sum_b, pos_b) = ra, rb
        diff = abs(sum_a - sum_b)
        if best is None or diff < best[0]:
            best = (diff, (a, pos_a, sum_a), (b, pos_b, sum_b))

    return best


def balance_all(players: list, limit: int = 20) -> list:
    """가능한 모든 분할을 전력 차 순으로 정렬해 반환한다. (다시 짜기용)"""
    idx = list(range(len(players)))
    results = []

    for rest in combinations(idx[1:], 4):
        a = (idx[0],) + rest
        b = tuple(i for i in idx if i not in a)

        ra = best_assignment([players[i] for i in a])
        if ra is None:
            continue
        rb = best_assignment([players[i] for i in b])
        if rb is None:
            continue

        (sum_a, pos_a), (sum_b, pos_b) = ra, rb
        results.append((abs(sum_a - sum_b), (a, pos_a, sum_a), (b, pos_b, sum_b)))

    results.sort(key=lambda x: x[0])
    return results[:limit]
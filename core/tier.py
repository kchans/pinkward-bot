TIER_ORDER = {
    "IRON": 0, "BRONZE": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 4,
    "EMERALD": 5, "DIAMOND": 6, "MASTER": 7, "GRANDMASTER": 8, "CHALLENGER": 9,
}
DIV_ORDER = {"IV": 0, "III": 1, "II": 2, "I": 3}
TIER_KO = {
    "IRON": "아이언", "BRONZE": "브론즈", "SILVER": "실버", "GOLD": "골드",
    "PLATINUM": "플래티넘", "EMERALD": "에메랄드", "DIAMOND": "다이아",
    "MASTER": "마스터", "GRANDMASTER": "그마", "CHALLENGER": "챌린저",
}
APEX = ("MASTER", "GRANDMASTER", "CHALLENGER")


def tier_score(tier: str | None, division: str | None, lp: int | None) -> int:
    """티어를 하나의 점수로 환산한다. 언랭은 -1."""
    if tier not in TIER_ORDER:
        return -1
    return TIER_ORDER[tier] * 400 + DIV_ORDER.get(division, 0) * 100 + (lp or 0)


def tier_label(tier: str | None, division: str | None, lp: int | None) -> str:
    if tier not in TIER_KO:
        return "언랭"
    ko = TIER_KO[tier]
    return f"{ko} {lp}LP" if tier in APEX else f"{ko} {division} {lp}LP"
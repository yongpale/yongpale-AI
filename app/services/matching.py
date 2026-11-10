"""F-003 맞춤형 정책 추천: 프로필과 정책 조건(policies.json의 match)을 규칙으로 비교한다.

판정
  ineligible  조건이 분명히 맞지 않음 (자녀 학년이 대상 밖, 한부모 전용인데 한부모 아님 등)
  check       프로필로 알 수 없는 조건이 있음 (소득, 다문화·장애 등 특정 가구, 거주 기간 등)
  eligible    알 수 있는 조건이 모두 맞음

프로필은 소득·특정 가구 정보를 받지 않는다. 그런 조건이 있는 정책은 빼지 않고
'조건 확인 필요' 라벨을 붙여 보여준다 (해당될 수 있는 정책을 놓치지 않게 알려주는 것이 목적).
특정 가구 대상 정책은 일반 가구에 해당할 가능성이 낮아 점수를 낮춰 목록 아래쪽에 둔다.

적합도 점수(0~100)는 판정 기본점에 가구 조건 일치, 지역, 돌봄 필요 여부를 더한다.
"""

import re
from collections import namedtuple

from app import data_loader

BASE_SCORE = {"eligible": 60, "check": 40, "ineligible": 0}
REGION_BONUS = {"yongin": 10, "gyeonggi": 5, "national": 0}
REGION_LABEL = {"yongin": "용인시", "gyeonggi": "경기도", "national": "중앙정부"}

HOUSEHOLD_FLAGS = [
    ("dual_income", "맞벌이"),
    ("single_parent", "한부모·조손"),
    ("multi_child", "다자녀"),
]

# 정책의 other_requirements 문구로 특정 가구 대상 정책을 알아내는 키워드
SPECIAL_KEYWORDS = {
    "multicultural": ["다문화", "이주배경", "외국인가족", "난민", "결혼이민", "중도입국"],
    "disability": ["장애", "특수교육", "발달"],
    "north_korean_defector": ["북한이탈", "탈북"],
    "veteran": ["보훈", "유공자"],
    "out_of_school": ["미취학", "학업중단", "학교 밖"],
}
# 맞벌이·한부모·다자녀, 소득 항목으로 이미 다루는 조건
RESOLVED_KEYWORDS = ["맞벌이", "한부모", "조손", "다자녀", "저소득", "수급", "차상위"]
SPECIAL_LABEL = {
    "multicultural": "다문화가족",
    "disability": "장애·특수교육",
    "north_korean_defector": "북한이탈주민",
    "veteran": "국가보훈대상자",
    "out_of_school": "학교 밖 아동(미취학·학업중단)",
}
CARE_CATEGORIES = {"돌봄", "방과후·학습"}
SPECIAL_GROUP_PENALTY = 20

Evaluation = namedtuple(
    "Evaluation",
    "status score reasons check_items notes labels condition_types target_children",
)


def special_groups(policy):
    """정책이 대상으로 하는 특정 가구 집단 (예: {'multicultural'})"""
    groups = set()
    for req in policy["match"]["other_requirements"]:
        for group, words in SPECIAL_KEYWORDS.items():
            if any(w in req for w in words):
                groups.add(group)
    return groups


def unresolved_requirements(policy):
    """특정 가구 집단으로 분류되지 않아 프로필로 확인할 수 없는 조건 (거주 기간, 수상 실적 등)"""
    known = [w for words in SPECIAL_KEYWORDS.values() for w in words] + RESOLVED_KEYWORDS
    return [req for req in policy["match"]["other_requirements"] if not any(w in req for w in known)]


def income_limit_percent(policy):
    """'기준 중위소득 200% 이하' → 200. 숫자가 없으면 None"""
    text = policy["match"].get("income_limit") or ""
    if "중위소득" not in text:
        return None
    numbers = [int(n) for n in re.findall(r"(\d{2,3})\s*%", text)]
    return max(numbers) if numbers else None


def evaluate(policy, profile):
    """정책 하나를 판정한다 (Evaluation)"""
    m = policy["match"]
    reasons, check_items, blockers, labels, condition_types = [], [], [], [], []
    notes = [m["notes"]] if m.get("notes") else []
    score_bonus = 0

    # 자녀 학년: 한 명이라도 대상이면 추천
    grade_min, grade_max = m.get("grade_min") or 1, m.get("grade_max") or 6
    targets = [c for c in profile.children if grade_min <= c.grade <= grade_max]
    if not targets:
        blockers.append(f"대상 학년이 초{grade_min}~초{grade_max}입니다")
    elif (grade_min, grade_max) != (1, 6) or len(targets) < len(profile.children):
        reasons.append(f"{', '.join(c.label for c in targets)} 대상 (초{grade_min}~초{grade_max})")

    # 맞벌이·한부모·다자녀
    for field, label in HOUSEHOLD_FLAGS:
        requirement = m.get(field, "not_mentioned")
        has = getattr(profile, field)
        if requirement == "required":
            if has:
                score_bonus += 15
                reasons.append(f"{label} 가구 대상")
            else:
                blockers.append(f"{label} 가구만 신청할 수 있습니다")
        elif requirement == "preferred" and has:
            score_bonus += 10
            reasons.append(f"{label} 가구 우대")

    # 특정 가구 (다문화, 장애, 북한이탈주민, 국가보훈대상자, 학교 밖 아동): 입력받지 않으므로 확인 필요
    groups = sorted(special_groups(policy))
    if groups:
        score_bonus -= SPECIAL_GROUP_PENALTY
        condition_types.append("special_group")
        for group in groups:
            check_items.append(f"{SPECIAL_LABEL[group]} 대상")
            labels.append(f"{SPECIAL_LABEL[group]} 대상")

    # 소득: 입력받지 않으므로 소득 조건이 있으면 확인 필요
    if m.get("low_income_only"):
        check_items.append(f"소득 기준: {m.get('income_limit') or '저소득 가구 대상'}")
        labels.append("소득 조건 확인 필요")
        condition_types.append("income")
    elif income_limit_percent(policy) is not None:
        # 저소득 전용은 아니지만 소득에 따라 지원이 달라지는 경우 (예: 아이돌봄 서비스 정부 지원)
        notes.append(f"소득 기준({m['income_limit']})에 따라 지원 수준이 달라집니다")

    # 그 밖의 조건 (거주 기간, 수상 실적, 등급 판정 등)
    others = unresolved_requirements(policy)
    if others:
        check_items += others
        labels.append("조건 확인 필요")
        condition_types.append("other")

    # 지역
    region = policy["region"]
    score_bonus += REGION_BONUS.get(region, 0)
    if region in ("yongin", "gyeonggi"):
        reasons.append(f"{REGION_LABEL[region]} 정책")

    # 돌봄 시간이 필요한 가구에 돌봄·방과후 정책
    if profile.care_time and m.get("category") in CARE_CATEGORIES:
        score_bonus += 10
        reasons.append(f"돌봄 필요 시간({profile.care_time.start}~{profile.care_time.end})에 맞는 {m['category']} 정책")

    target_names = [c.label for c in targets]
    if blockers:
        return Evaluation("ineligible", 0, blockers, check_items, notes, [], condition_types, target_names)
    status = "check" if check_items else "eligible"
    if status == "eligible":
        labels.insert(0, "해당 가능")
    score = max(0, min(100, BASE_SCORE[status] + score_bonus))
    return Evaluation(status, score, reasons, check_items, notes, labels, condition_types, target_names)


def match_policies(profile, include_ineligible=False, limit=None):
    """'총 N건' = 해당 가능 + 조건 확인 필요 (특정 가구 대상은 점수가 낮아 목록 뒤쪽)"""
    results = []
    for policy in data_loader.load_policies():
        e = evaluate(policy, profile)
        if e.status == "ineligible" and not include_ineligible:
            continue
        results.append({
            "id": policy["id"],
            "name": policy["name"],
            "agency": policy["agency"],
            "region": policy["region"],
            "category": policy["match"].get("category"),
            "summary": policy.get("summary"),
            "status": e.status,
            "score": e.score,
            "reasons": e.reasons,
            "check_items": e.check_items,
            "labels": e.labels,
            "condition_types": e.condition_types,
            "target_children": e.target_children,
            "notes": e.notes,
            "apply_period": policy["match"].get("apply_period"),
            "source": policy["source"],
        })

    order = {"eligible": 0, "check": 1, "ineligible": 2}
    results.sort(key=lambda r: (order[r["status"]], -r["score"], r["name"]))
    eligible = sum(1 for r in results if r["status"] == "eligible")
    check = sum(1 for r in results if r["status"] == "check")
    special = sum(1 for r in results if "special_group" in r["condition_types"])
    return {
        "total": eligible + check,
        "eligible_count": eligible,
        "check_count": check,
        "special_group_count": special,
        "total_without_special": eligible + check - special,
        "policies": results[:limit] if limit else results,
    }

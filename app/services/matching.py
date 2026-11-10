"""F-003 맞춤형 정책 추천: 프로필과 정책 조건(policies.json의 match)을 규칙으로 비교한다.

판정
  ineligible  조건이 분명히 맞지 않음 (학년 범위 밖, 한부모 전용인데 한부모 아님 등)
  check       프로필만으로 판단할 수 없는 조건이 있음 (소득 정보 없음, 거주 기간, 등급 판정 등)
  eligible    알 수 있는 조건이 모두 맞음

적합도 점수(0~100)는 판정 기본점에 가구 조건 일치, 지역, 돌봄 필요 여부를 더한다.
"""

import re

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
# 프로필의 맞벌이·한부모·다자녀, 소득 항목으로 이미 판단하는 조건
RESOLVED_KEYWORDS = ["맞벌이", "한부모", "조손", "다자녀", "저소득", "수급", "차상위"]
SPECIAL_LABEL = {
    "multicultural": "다문화가족",
    "disability": "장애·특수교육",
    "north_korean_defector": "북한이탈주민",
    "veteran": "국가보훈대상자",
    "out_of_school": "학교 밖 아동(미취학·학업중단)",
}
CARE_CATEGORIES = {"돌봄", "방과후·학습"}


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
    """정책 하나를 판정한다. (status, score, reasons, check_items, notes)"""
    m = policy["match"]
    reasons, check_items, blockers = [], [], []
    notes = [m["notes"]] if m.get("notes") else []
    score_bonus = 0

    # 학년
    grade_min, grade_max = m.get("grade_min") or 1, m.get("grade_max") or 6
    if not grade_min <= profile.grade <= grade_max:
        blockers.append(f"대상 학년이 초{grade_min}~초{grade_max}입니다")
    elif (grade_min, grade_max) != (1, 6):
        reasons.append(f"초{grade_min}~초{grade_max} 대상")

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

    # 특정 가구 집단 (다문화, 장애, 북한이탈주민, 국가보훈대상자)
    for group in sorted(special_groups(policy)):
        if group in profile.special:
            score_bonus += 15
            reasons.append(f"{SPECIAL_LABEL[group]} 대상")
        else:
            blockers.append(f"{SPECIAL_LABEL[group]} 대상 정책입니다")

    # 소득
    limit = income_limit_percent(policy)
    if m.get("low_income_only"):
        if profile.income_percent is not None and limit is not None:
            if profile.income_percent <= limit:
                reasons.append(f"소득 기준({m['income_limit']}) 충족")
            else:
                blockers.append(f"소득 기준({m['income_limit']})을 넘습니다")
        elif profile.low_income is True:
            score_bonus += 5
            reasons.append("저소득 가구 대상")
        elif profile.low_income is False:
            blockers.append("저소득 가구만 신청할 수 있습니다")
        else:
            check_items.append(f"소득 기준: {m.get('income_limit') or '저소득 가구 대상'}")
    elif limit is not None:
        # 저소득 전용은 아니지만 소득에 따라 지원이 달라지는 경우 (예: 아이돌봄 서비스 정부 지원)
        if profile.income_percent is None:
            notes.append(f"소득 기준({m['income_limit']})에 따라 지원 수준이 달라집니다")
        elif profile.income_percent > limit:
            notes.append(f"소득 기준({m['income_limit']})을 넘어 정부 지원을 받지 못할 수 있습니다")

    # 그 밖의 조건
    for req in unresolved_requirements(policy):
        check_items.append(req)

    # 지역
    region = policy["region"]
    score_bonus += REGION_BONUS.get(region, 0)
    if region in ("yongin", "gyeonggi"):
        reasons.append(f"{REGION_LABEL[region]} 정책")

    # 돌봄 시간이 필요한 가구에 돌봄·방과후 정책
    if profile.care_time and m.get("category") in CARE_CATEGORIES:
        score_bonus += 10
        reasons.append(f"돌봄 필요 시간({profile.care_time.start}~{profile.care_time.end})에 맞는 {m['category']} 정책")

    if blockers:
        return "ineligible", 0, blockers, check_items, notes
    status = "check" if check_items else "eligible"
    score = min(100, BASE_SCORE[status] + score_bonus)
    return status, score, reasons, check_items, notes


def match_policies(profile, include_ineligible=False, limit=None):
    results = []
    for policy in data_loader.load_policies():
        status, score, reasons, check_items, notes = evaluate(policy, profile)
        if status == "ineligible" and not include_ineligible:
            continue
        results.append({
            "id": policy["id"],
            "name": policy["name"],
            "agency": policy["agency"],
            "region": policy["region"],
            "category": policy["match"].get("category"),
            "summary": policy.get("summary"),
            "status": status,
            "score": score,
            "reasons": reasons,
            "check_items": check_items,
            "notes": notes,
            "apply_period": policy["match"].get("apply_period"),
            "source": policy["source"],
        })

    order = {"eligible": 0, "check": 1, "ineligible": 2}
    results.sort(key=lambda r: (order[r["status"]], -r["score"], r["name"]))
    eligible = sum(1 for r in results if r["status"] == "eligible")
    check = sum(1 for r in results if r["status"] == "check")
    return {
        "total": eligible + check,
        "eligible_count": eligible,
        "check_count": check,
        "policies": results[:limit] if limit else results,
    }

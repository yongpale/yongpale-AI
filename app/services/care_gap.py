"""F-009 돌봄 공백 분석: 필요한 돌봄 시간 중 비는 시간을 계산하고 시설 조합을 추천한다.

- 공백 = 돌봄 필요 시간 - 학교에 있는 시간 (방학은 필요 시간 전체)
- 시설 운영시간과 겹치는 만큼 공백이 채워진다. 운영시간이 null이면 '정보 없음'이라 계산에서 뺀다.
- 시설 좌표가 아직 없어서 거리 대신 같은 동 > 같은 구 > 다른 구 순으로 가까움을 판단한다.
"""

from itertools import combinations

from app import data_loader
from app.services.matching import evaluate

# 학기 중 학년별 하교 시간 기본값 (학교·요일마다 다름)
DEFAULT_SCHOOL_END = {1: "13:00", 2: "13:00", 3: "14:30", 4: "14:30", 5: "15:00", 6: "15:00"}
PERIOD_LABEL = {"semester": "학기 중", "vacation": "방학 중"}
# 두 시설을 이어서 이용할 때, 한 곳만 쓸 때보다 이만큼 이상 더 채워야 조합으로 추천
MIN_EXTRA_MINUTES = 30
CHILDCARE_SERVICE_ID = "423000000362"
# 남는 공백에 안내할 정책: 돌보미 파견·활동지원처럼 시간 단위로 돌봄을 제공하는 서비스
TIME_CARE_POLICY_IDS = [
    CHILDCARE_SERVICE_ID,  # 아이돌봄 서비스
    "SPE000000120",        # 장애아가족 양육 지원
    "VOU000000020",        # 장애인 활동지원
    "641000000125",        # 장애인활동지원급여지원 (경기도)
    "135200005037",        # 발달장애인 긴급돌봄 시범사업
]


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_range(start, end):
    return {"start": to_hhmm(start), "end": to_hhmm(end), "minutes": end - start}


def subtract(ranges, cover):
    """ranges(분 단위 구간 목록)에서 cover 구간을 뺀다"""
    cs, ce = cover
    result = []
    for s, e in ranges:
        if ce <= s or cs >= e:
            result.append((s, e))
            continue
        if s < cs:
            result.append((s, cs))
        if ce < e:
            result.append((ce, e))
    return result


def total(ranges):
    return sum(e - s for s, e in ranges)


def accepts_grade(facility, grade):
    """시설 이용 연령에 자녀가 포함되는지.

    원본의 연령 표기가 만 나이인지 한국식 나이인지 시설마다 섞여 있어서
    초N학년을 만 N+5 ~ 한국식 N+7세 범위로 넓게 본다.
    """
    if facility.get("all_ages"):
        return True
    lo, hi = facility.get("age_min"), facility.get("age_max")
    if lo is None and hi is None:
        return True
    child_lo, child_hi = grade + 5, grade + 7
    return (lo is None or lo <= child_hi) and (hi is None or hi >= child_lo)


def facility_hours(facility, period):
    h = (facility.get("hours") or {}).get(period)
    if not h or not h.get("open") or not h.get("close"):
        return None
    return to_min(h["open"]), to_min(h["close"])


def closeness(facility, profile):
    """2 = 같은 동, 1 = 같은 구, 0 = 다른 구 또는 알 수 없음"""
    if profile.dong and facility.get("dong") == profile.dong:
        return 2
    if profile.gu and facility.get("gu") == profile.gu:
        return 1
    return 0


def fee_value(facility):
    """정렬용 이용료 (무료 0, 정보 없음은 뒤로)"""
    fee = facility.get("fee") or {}
    if fee.get("type") == "free":
        return 0
    if fee.get("amount"):
        return fee["amount"] * (20 if fee.get("unit") == "day" else 1)
    return 10 ** 9


def fee_text(facility):
    fee = facility.get("fee") or {}
    if fee.get("type") == "free":
        return "이용료 무료"
    if fee.get("amount"):
        unit = {"day": "하루", "month": "월"}.get(fee.get("unit"), "")
        return f"이용료 {unit} {fee['amount']:,}원".replace("  ", " ")
    return None


def brief(facility, period, cover=None):
    hours = facility_hours(facility, period)
    return {
        "id": facility["id"],
        "name": facility["name"],
        "type": facility["type"],
        "gu": facility.get("gu"),
        "dong": facility.get("dong"),
        "address": facility.get("address"),
        "phone": facility.get("phone"),
        "hours": time_range(*hours) if hours else None,
        "covers": time_range(*cover) if cover else None,
        "fee": facility.get("fee") or {},
        "meal": facility.get("meal"),
        "snack": facility.get("snack"),
        "pickup": facility.get("pickup"),
        "application_info": facility.get("application_info"),
        "source": facility.get("source"),
        "verified_at": facility.get("verified_at"),
    }


def plan_reasons(facilities, covers, gap, remaining, profile, period):
    reasons = []
    gap_total = total(gap)
    covered = gap_total - total(remaining)
    if not remaining:
        reasons.append(f"{PERIOD_LABEL[period]} 돌봄 공백 {gap_total // 60}시간 {gap_total % 60}분을 모두 채울 수 있어요".replace(" 0분", ""))
    else:
        reasons.append(f"돌봄 공백 중 {covered // 60}시간 {covered % 60}분을 채울 수 있어요".replace(" 0분", ""))

    for f, cover in zip(facilities, covers):
        parts = [f"{f['name']}: {to_hhmm(cover[0])}~{to_hhmm(cover[1])} 이용"]
        c = closeness(f, profile)
        if c == 2:
            parts.append(f"같은 동({f['dong']})")
        elif c == 1:
            parts.append(f"같은 구({f['gu']})")
        if fee_text(f):
            parts.append(fee_text(f))
        if f.get("meal"):
            parts.append("급식 제공")
        elif f.get("snack"):
            parts.append("간식 제공")
        if f.get("pickup"):
            parts.append("등하원 지원")
        app = f.get("application_info") or ""
        priority = [label for flag, label in ((profile.dual_income, "맞벌이"), (profile.single_parent, "한부모"))
                    if flag and label in app]
        if priority:
            parts.append(f"대기 시 {'·'.join(priority)} 가정 우선 이용")
        reasons.append(", ".join(parts))

    if len(facilities) == 2:
        reasons.append(f"{to_hhmm(covers[0][1])}에 다음 시설로 이동해야 해요 (등하원 방법을 미리 확인하세요)")
    return reasons


def analyze(profile, period="semester", school_end=None, care_time=None, max_results=3):
    care_time = care_time or profile.care_time
    if care_time is None:
        raise ValueError("돌봄이 필요한 시간(care_time)이 없습니다")
    need = (to_min(care_time.start), to_min(care_time.end))
    if need[0] >= need[1]:
        raise ValueError("care_time의 end가 start보다 늦어야 합니다")

    notes = []
    if period == "semester":
        school_end = school_end or DEFAULT_SCHOOL_END[profile.grade]
        if school_end == DEFAULT_SCHOOL_END[profile.grade]:
            notes.append(f"하교 시간은 초{profile.grade} 기본값({school_end})으로 계산했어요. 학교마다 달라요.")
        gap = [(max(need[0], to_min(school_end)), need[1])]
        gap = [(s, e) for s, e in gap if s < e]
    else:
        school_end = None
        gap = [need]

    candidates = []
    unknown_hours = 0
    for f in data_loader.load_facilities():
        if not accepts_grade(f, profile.grade):
            continue
        hours = facility_hours(f, period)
        if hours is None:
            unknown_hours += 1
            continue
        cover = (max(hours[0], gap[0][0]), min(hours[1], gap[0][1])) if gap else None
        if cover and cover[0] < cover[1]:
            candidates.append((f, cover))
    if unknown_hours:
        notes.append(f"{PERIOD_LABEL[period]} 운영시간 정보가 없는 시설 {unknown_hours}곳은 추천에서 뺐어요.")

    # 가까운 시설이 있으면 그 안에서만 조합한다
    if not gap:
        notes.append("필요한 돌봄 시간이 학교에 있는 시간과 겹쳐서 돌봄 공백이 없어요.")
    elif profile.gu and any(closeness(f, profile) >= 1 for f, _ in candidates):
        candidates = [(f, c) for f, c in candidates if closeness(f, profile) >= 1]
    elif profile.gu:
        notes.append(f"{profile.gu}에 조건에 맞는 시설이 없어 다른 구 시설도 포함했어요.")

    plans = []
    for f, cover in candidates:
        remaining = subtract(gap, cover)
        plans.append(([f], [cover], remaining))
    singles = {f["id"]: total(gap) - total(r) for (f,), _, r in plans}
    best_single = max(singles.values(), default=0)
    for (f1, c1), (f2, c2) in combinations(candidates, 2):
        first, second = sorted([(f1, c1), (f2, c2)], key=lambda x: x[1][0])
        # 앞 시설이 끝나는 시간부터 뒤 시설을 이용 (겹치는 시간은 앞 시설)
        c2_adj = (max(second[1][0], first[1][1]), second[1][1])
        if c2_adj[0] >= c2_adj[1]:
            continue
        remaining = subtract(subtract(gap, first[1]), c2_adj)
        covered = total(gap) - total(remaining)
        if covered - max(singles[f1["id"]], singles[f2["id"]]) < MIN_EXTRA_MINUTES or covered <= best_single:
            continue
        plans.append(([first[0], second[0]], [first[1], c2_adj], remaining))

    def rank(plan):
        facilities, _, remaining = plan
        return (
            total(remaining),                                    # 남는 공백이 적을수록
            len(facilities),                                     # 한 곳이면 더 좋음
            -sum(closeness(f, profile) for f in facilities),     # 가까울수록
            sum(fee_value(f) for f in facilities),               # 저렴할수록
        )

    plans.sort(key=rank)
    result_plans = []
    for facilities, covers, remaining in plans[:max_results]:
        covered = total(gap) - total(remaining)
        result_plans.append({
            "facilities": [brief(f, period, c) for f, c in zip(facilities, covers)],
            "covered_minutes": covered,
            "coverage_rate": round(covered / total(gap), 2) if total(gap) else 1.0,
            "remaining": [time_range(s, e) for s, e in remaining],
            "reasons": plan_reasons(facilities, covers, gap, remaining, profile, period),
        })

    # 시설로 다 못 채우는 공백이 있으면 돌봄 정책(아이돌봄 서비스 등)을 함께 안내
    related = []
    best_remaining = result_plans[0]["remaining"] if result_plans else [time_range(s, e) for s, e in gap]
    if best_remaining:
        for pid in TIME_CARE_POLICY_IDS:
            p = data_loader.get_policy(pid)
            if p is None:
                continue
            status, _, _, _, _ = evaluate(p, profile)
            if status == "ineligible":
                continue
            slots = ", ".join(f"{r['start']}~{r['end']}" for r in best_remaining)
            reason = f"시설로 채우지 못하는 {slots} 공백에 이용할 수 있는 돌봄 정책이에요"
            if p["id"] == CHILDCARE_SERVICE_ID:
                reason = f"돌보미가 집으로 찾아와 {slots} 공백을 채울 수 있어요"
            related.append({"id": p["id"], "name": p["name"], "status": status, "reason": reason})

    notes.append("정원·대기 현황은 데이터에 없어서 시설에 직접 확인해야 해요.")
    return {
        "period": period,
        "care_time": time_range(*need),
        "school_end": school_end,
        "gap": [time_range(s, e) for s, e in gap],
        "gap_minutes": total(gap),
        "plans": result_plans,
        "related_policies": related,
        "notes": notes,
    }

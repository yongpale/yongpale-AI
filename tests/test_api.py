from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CHILDCARE_ID = "423000000362"  # 아이돌봄 서비스
SINGLE_PARENT_ONLY_ID = "641000000155"  # 한부모가족 학습재료비 등 지원

DUAL_INCOME_GRADE1 = {
    "gu": "기흥구", "dong": "구갈동", "dual_income": True,
    "care_time": {"start": "13:00", "end": "19:00"},
    "children": [{"nickname": "첫째", "grade": 1}],
}


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["policies"] > 0 and body["facilities"] > 0
    assert body["gemini_enabled"] is False


# ---------------------------------------------------------------------------
# F-003
# ---------------------------------------------------------------------------

def test_match_counts_and_order():
    res = client.post("/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1})
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == body["eligible_count"] + body["check_count"]
    statuses = [p["status"] for p in body["policies"]]
    assert "ineligible" not in statuses
    # eligible이 check보다 먼저, 같은 판정 안에서는 점수 높은 순
    assert statuses == sorted(statuses, key=lambda s: s != "eligible")
    eligible_scores = [p["score"] for p in body["policies"] if p["status"] == "eligible"]
    assert eligible_scores == sorted(eligible_scores, reverse=True)


def test_match_childcare_for_dual_income():
    body = client.post("/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1}).json()
    childcare = next(p for p in body["policies"] if p["id"] == CHILDCARE_ID)
    assert childcare["status"] == "eligible"
    assert "맞벌이 가구 우대" in childcare["reasons"]


def test_match_required_household_excluded():
    body = client.post("/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1}).json()
    assert SINGLE_PARENT_ONLY_ID not in [p["id"] for p in body["policies"]]

    profile = {**DUAL_INCOME_GRADE1, "dual_income": False, "single_parent": True}
    body = client.post("/ai/policies/match", json={"profile": profile}).json()
    target = next(p for p in body["policies"] if p["id"] == SINGLE_PARENT_ONLY_ID)
    # 한부모 조건은 맞고, 소득은 입력받지 않으므로 확인 필요
    assert target["status"] == "check"
    assert "한부모·조손 가구 대상" in target["reasons"]
    assert "소득 조건 확인 필요" in target["labels"]


def test_match_income_condition_is_labeled():
    body = client.post("/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1}).json()
    low_income_policy = next(p for p in body["policies"] if p["name"] == "교육급여")
    assert low_income_policy["status"] == "check"
    assert low_income_policy["condition_types"] == ["income"]
    assert "소득 조건 확인 필요" in low_income_policy["labels"]


def test_match_special_group_kept_but_ranked_low():
    body = client.post("/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1}).json()
    special = [p for p in body["policies"] if "special_group" in p["condition_types"]]
    general = [p for p in body["policies"] if "special_group" not in p["condition_types"]]
    assert any("다문화" in p["name"] for p in special)
    assert all("다문화가족 대상" in p["labels"] for p in special if p["name"].startswith("다문화가족"))
    assert body["special_group_count"] == len(special)
    assert body["total_without_special"] == len(general)
    # 특정 가구 정책은 점수를 낮춰 목록 뒤쪽에
    assert max(p["score"] for p in special) < max(p["score"] for p in general)
    assert body["policies"][0]["condition_types"] == []


def test_match_multiple_children():
    profile = {**DUAL_INCOME_GRADE1, "children": [{"nickname": "첫째", "grade": 2}, {"nickname": "둘째", "grade": 5}]}
    body = client.post("/ai/policies/match", json={"profile": profile}).json()
    video_english = next(p for p in body["policies"] if "화상영어" in p["name"])  # 초3~초6 대상
    assert video_english["target_children"] == ["둘째"]
    only_second = {**profile, "children": [{"grade": 2}]}
    body = client.post("/ai/policies/match", json={"profile": only_second}).json()
    assert all("화상영어" not in p["name"] for p in body["policies"])


def test_match_include_ineligible_and_limit():
    body = client.post(
        "/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1, "include_ineligible": True, "limit": 5}
    ).json()
    assert len(body["policies"]) == 5


def test_match_invalid_profile():
    res = client.post("/ai/policies/match", json={"profile": {"children": [{"grade": 7}]}})
    assert res.status_code == 422
    res = client.post("/ai/policies/match", json={"profile": {"children": []}})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# F-004
# ---------------------------------------------------------------------------

def test_summary_without_profile():
    res = client.post(f"/ai/policies/{CHILDCARE_ID}/summary", json={})
    assert res.status_code == 200
    body = res.json()
    assert [s["title"] for s in body["summary"]] == ["신청 자격", "지원 혜택", "필요 서류", "신청 기간"]
    assert body["tip"] is None and body["status"] is None
    assert body["sources"][0]["url"]
    assert body["info_date"]


def test_summary_with_profile_has_fallback_tip_and_documents():
    res = client.post(f"/ai/policies/{CHILDCARE_ID}/summary", json={"profile": DUAL_INCOME_GRADE1})
    body = res.json()
    assert body["status"] == "eligible"
    # Gemini를 끈 상태라 규칙 기반 팁
    assert body["tip"]["generated"] is False and body["tip"]["text"]
    # 맞벌이 가정 입증서류만
    types = {d["household_type"] for d in body["household_documents"]}
    assert types and all(t.startswith("맞벌이") for t in types)


def test_summary_not_found():
    res = client.post("/ai/policies/NOPE/summary", json={})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# F-009
# ---------------------------------------------------------------------------

def test_care_gap_semester():
    res = client.post("/ai/care-gap", json={"profile": DUAL_INCOME_GRADE1, "period": "semester"})
    assert res.status_code == 200
    body = res.json()
    assert body["gap"] == [{"start": "13:00", "end": "19:00", "minutes": 360}]
    assert body["plans"]
    best = body["plans"][0]
    assert 0 < best["coverage_rate"] <= 1
    for f in best["facilities"]:
        assert f["gu"] == "기흥구"
        assert f["hours"] is not None


def test_care_gap_remaining_suggests_childcare():
    req = {
        "profile": {**DUAL_INCOME_GRADE1, "gu": "수지구", "dong": None, "children": [{"grade": 4}]},
        "period": "vacation",
        "care_time": {"start": "08:00", "end": "21:30"},
    }
    body = client.post("/ai/care-gap", json=req).json()
    assert body["plans"][0]["remaining"]
    assert body["related_policies"][0]["id"] == CHILDCARE_ID


def test_care_gap_no_gap():
    req = {"profile": {**DUAL_INCOME_GRADE1, "care_time": {"start": "10:00", "end": "12:00"}}, "period": "semester"}
    body = client.post("/ai/care-gap", json=req).json()
    assert body["gap"] == [] and body["plans"] == []


def test_care_gap_uses_youngest_child_by_default():
    profile = {**DUAL_INCOME_GRADE1, "children": [{"nickname": "형", "grade": 5}, {"nickname": "동생", "grade": 1}]}
    body = client.post("/ai/care-gap", json={"profile": profile}).json()
    assert body["child"] == "동생" and body["school_end"] == "13:00"
    body = client.post("/ai/care-gap", json={"profile": profile, "child_index": 0}).json()
    assert body["child"] == "형" and body["school_end"] == "15:00"
    assert client.post("/ai/care-gap", json={"profile": profile, "child_index": 5}).status_code == 422


def test_care_gap_without_care_time_uses_default():
    # 백엔드 가구 정보에 돌봄 필요 시간이 없을 때
    profile = {k: v for k, v in DUAL_INCOME_GRADE1.items() if k != "care_time"}
    body = client.post("/ai/care-gap", json={"profile": profile}).json()
    assert body["care_time"] == {"start": "13:00", "end": "18:00", "minutes": 300}
    assert any("돌봄 필요 시간 정보가 없어" in n for n in body["notes"])


# ---------------------------------------------------------------------------
# 백엔드 형식 호환
# ---------------------------------------------------------------------------

# 백엔드 GET 가구 정보 응답(HouseholdResponse)을 그대로 넘기는 경우
BACKEND_PROFILE = {
    "id": 1,
    "region": {"id": 3, "guName": "수지구", "dongName": "상현3동", "regionType": "DONG"},
    "situations": ["DUAL_INCOME", "MULTI_CHILD"],
    "children": [
        {"id": 10, "birthOrder": 1, "nickname": "첫째", "grade": "초3"},
        {"id": 11, "birthOrder": 2, "nickname": "둘째", "grade": "유치6세"},
    ],
    "careNeedStartTime": "13:00:00",
    "careNeedEndTime": "18:00:00",
}


def test_backend_profile_format_accepted():
    from app.schemas import Profile

    p = Profile.model_validate(BACKEND_PROFILE)
    assert (p.gu, p.dong) == ("수지구", "상현3동")
    assert p.dual_income and p.multi_child and not p.single_parent
    assert [c.grade for c in p.children] == [3, -1]
    assert (p.care_time.start, p.care_time.end) == ("13:00", "18:00")
    res = client.post("/ai/policies/match", json={"profile": BACKEND_PROFILE})
    assert res.status_code == 200
    # 유치 자녀는 초등 정책 대상이 아니라 첫째만 대상
    assert all(pol["target_children"] == ["첫째"] for pol in res.json()["policies"])


def test_backend_profile_care_gap_matches_legal_dong():
    body = client.post("/ai/care-gap", json={"profile": BACKEND_PROFILE}).json()
    # 행정동 상현3동 프로필 ↔ 법정동 상현동 시설
    assert body["child"] == "첫째"
    reasons = " ".join(" ".join(p["reasons"]) for p in body["plans"])
    assert "같은 동(상현동)" in reasons


def test_kindergarten_only_household():
    profile = {**DUAL_INCOME_GRADE1, "children": [{"nickname": "막내", "grade": "유치7세"}]}
    body = client.post("/ai/policies/match", json={"profile": profile}).json()
    assert body["total"] == 0
    res = client.post("/ai/care-gap", json={"profile": profile})
    assert res.status_code == 422


def test_unknown_grade_label_rejected():
    profile = {**DUAL_INCOME_GRADE1, "children": [{"grade": "중1"}]}
    assert client.post("/ai/policies/match", json={"profile": profile}).status_code == 422


def test_summary_lookup_by_backend_fields():
    # 백엔드 policies에는 서비스ID가 없고 source_url, title만 있다
    url = "https://plus.gov.kr/portal/benefitV2/benefitTotalSrvcList/benefitSrvcDtl?svcSeq=746602&bnefType=all&svcId=423000000362"
    for body in ({"source_url": url}, {"title": "아이돌봄 서비스"}, {"title": "아이돌봄서비스"}, {"policy_id": CHILDCARE_ID}):
        res = client.post("/ai/policies/summary", json=body)
        assert res.status_code == 200 and res.json()["policy_id"] == CHILDCARE_ID
    assert client.post("/ai/policies/summary", json={"title": "없는 정책"}).status_code == 404
    assert client.post("/ai/policies/summary", json={}).status_code == 422

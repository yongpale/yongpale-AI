from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CHILDCARE_ID = "423000000362"  # 아이돌봄 서비스
SINGLE_PARENT_ONLY_ID = "641000000155"  # 한부모가족 학습재료비 등 지원

DUAL_INCOME_GRADE1 = {
    "gu": "기흥구", "dong": "구갈동", "grade": 1, "dual_income": True,
    "care_time": {"start": "13:00", "end": "19:00"},
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

    profile = {**DUAL_INCOME_GRADE1, "dual_income": False, "single_parent": True, "low_income": True}
    body = client.post("/ai/policies/match", json={"profile": profile}).json()
    target = next(p for p in body["policies"] if p["id"] == SINGLE_PARENT_ONLY_ID)
    assert target["status"] == "eligible"


def test_match_unknown_income_is_check():
    body = client.post("/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1}).json()
    low_income_policy = next(p for p in body["policies"] if p["name"] == "교육급여")
    assert low_income_policy["status"] == "check"
    assert any("소득" in c for c in low_income_policy["check_items"])


def test_match_special_group():
    general = client.post("/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1}).json()
    assert all("다문화" not in p["name"] for p in general["policies"])
    profile = {**DUAL_INCOME_GRADE1, "special": ["multicultural"]}
    multicultural = client.post("/ai/policies/match", json={"profile": profile}).json()
    assert any("다문화" in p["name"] for p in multicultural["policies"])


def test_match_include_ineligible_and_limit():
    body = client.post(
        "/ai/policies/match", json={"profile": DUAL_INCOME_GRADE1, "include_ineligible": True, "limit": 5}
    ).json()
    assert len(body["policies"]) == 5


def test_match_invalid_profile():
    res = client.post("/ai/policies/match", json={"profile": {"grade": 7}})
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
        "profile": {**DUAL_INCOME_GRADE1, "gu": "수지구", "dong": None, "grade": 4},
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


def test_care_gap_requires_care_time():
    profile = {k: v for k, v in DUAL_INCOME_GRADE1.items() if k != "care_time"}
    res = client.post("/ai/care-gap", json={"profile": profile})
    assert res.status_code == 422

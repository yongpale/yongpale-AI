"""백엔드(yongpale-BE)가 실제로 보내는 요청 JSON 그대로 호출해서, 백엔드가 읽는 응답 필드가 있는지 확인한다.

요청 형식: BE policy/client/AiMatchRequest, AiSummaryRequest, MatchProfile, caregap/client/AiCareGapRequest
응답 형식: BE AiMatchResponse, AiSummaryResponse, AiCareGapResponse
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CHILDCARE_URL = (
    "https://plus.gov.kr/portal/benefitV2/benefitTotalSrvcList/benefitSrvcDtl"
    "?svcSeq=746602&bnefType=all&svcId=423000000362"
)

# BE MatchProfile (Jackson 기본 직렬화: camelCase, ChildGrade는 라벨)
MATCH_PROFILE = {
    "guName": "기흥구",
    "dongName": "구갈동",
    "childCount": 2,
    "childGrades": ["초1", "유치6세"],
    "dualIncome": True,
    "singleParent": False,
    "multiChild": True,
    "careTime": {"start": "13:00", "end": "18:00"},
}
STATUSES = {"eligible", "check", "ineligible"}


def test_match_request_from_backend():
    res = client.post("/ai/policies/match", json={"profile": MATCH_PROFILE, "include_ineligible": False})
    assert res.status_code == 200
    policies = res.json()["policies"]
    assert policies
    for p in policies:
        # AiPolicyMatch 필드
        for key in ("id", "name", "status", "score", "reasons", "check_items", "labels",
                    "condition_types", "target_children", "notes", "apply_period", "source"):
            assert key in p
        assert p["status"] in STATUSES
        assert p["source"]["url"]  # 백엔드 정책 연결 키
        # 유치 자녀는 초등 정책 대상이 아님
        assert "유치6세" not in p["target_children"]


def test_match_request_include_ineligible():
    res = client.post("/ai/policies/match", json={"profile": MATCH_PROFILE, "include_ineligible": True})
    assert res.status_code == 200
    assert {p["status"] for p in res.json()["policies"]} <= STATUSES


def test_match_profile_without_region_and_care_time():
    profile = {**MATCH_PROFILE, "guName": None, "dongName": None, "careTime": None}
    res = client.post("/ai/policies/match", json={"profile": profile, "include_ineligible": False})
    assert res.status_code == 200


def test_summary_request_from_backend():
    for profile in (MATCH_PROFILE, None):
        res = client.post("/ai/policies/summary", json={"source_url": CHILDCARE_URL, "profile": profile})
        assert res.status_code == 200
        body = res.json()
        # AiSummaryResponse 필드
        for key in ("status", "summary", "summary_generated", "household_documents", "tip", "apply",
                    "sources", "info_date"):
            assert key in body
        assert [s["title"] for s in body["summary"]] == ["신청 자격", "지원 혜택", "필요 서류", "신청 기간"]
        for key in ("how_to_apply", "deadline_type", "deadline", "reception", "contact", "online_url"):
            assert key in body["apply"]
        if profile is None:
            assert body["status"] is None and body["tip"] is None
        else:
            assert body["status"] in STATUSES and body["tip"]["text"]


def test_care_gap_request_from_backend():
    req = {
        "profile": MATCH_PROFILE,
        "child_index": 0,  # 백엔드가 고른 초등학생 자녀
        "period": "semester",
        "school_end": None,
        "care_time": None,
        "max_results": 3,
    }
    res = client.post("/ai/care-gap", json=req)
    assert res.status_code == 200
    body = res.json()
    for key in ("period", "care_time", "school_end", "gap", "gap_minutes", "plans", "related_policies", "notes"):
        assert key in body
    assert body["plans"]
    for plan in body["plans"]:
        for key in ("facilities", "covered_minutes", "coverage_rate", "remaining", "reasons"):
            assert key in plan
        for f in plan["facilities"]:
            # 백엔드 facilities.source_ref_id와 같은 시설 id
            assert f["id"].startswith("YI")
            for key in ("name", "hours", "covers", "fee", "meal", "snack", "pickup"):
                assert key in f


def test_care_gap_vacation_with_care_time_override():
    req = {
        "profile": {**MATCH_PROFILE, "careTime": None},
        "child_index": 0,
        "period": "vacation",
        "school_end": None,
        "care_time": {"start": "08:00", "end": "21:00"},
        "max_results": 3,
    }
    body = client.post("/ai/care-gap", json=req).json()
    assert body["care_time"]["start"] == "08:00"
    for r in body["related_policies"]:
        assert set(r) >= {"id", "name", "status", "reason"} and r["status"] in STATUSES

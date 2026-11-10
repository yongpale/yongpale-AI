from fastapi.testclient import TestClient

from app.main import app
from app.services import chat, gemini

client = TestClient(app)

PROFILE = {"gu": "기흥구", "dong": "구갈동", "grade": 1, "dual_income": True}
CHILDCARE_DOC = "policy:423000000362"  # 아이돌봄 서비스
AFTER_SCHOOL_DOC = "policy:GES000000150"  # 방과후학교 자유수강권 (저소득 대상)


def fake_answer(monkeypatch, **kwargs):
    answer = chat.GeneratedAnswer(**{"grounded": True, "intro": "안내해 드릴게요.", "items": [], "used_doc_ids": [], **kwargs})
    monkeypatch.setattr(gemini, "generate_json", lambda *a, **k: answer)


def test_chat_no_match_is_not_grounded():
    res = client.post("/ai/chat", json={"question": "ㅁㄴㅇㄹ", "profile": PROFILE})
    assert res.status_code == 200
    body = res.json()
    assert body["grounded"] is False
    assert body["sources"] == [] and body["related_policies"] == []
    assert body["profile_label"] == "초1 · 기흥구 구갈동 · 맞벌이"


def test_chat_fallback_when_gemini_disabled():
    # 테스트에서는 Gemini가 꺼져 있어 키워드 검색 + 자료 목록 대체 답변
    body = client.post("/ai/chat", json={"question": "아이돌봄 서비스 신청", "profile": PROFILE}).json()
    assert body["grounded"] is True and body["generated"] is False
    assert any(p["id"] == "423000000362" for p in body["related_policies"])
    assert body["sources"]


def test_chat_generated_answer_with_sources(monkeypatch):
    fake_answer(
        monkeypatch,
        items=[{"title": "신청처", "text": "주민센터에서 신청해요."}],
        used_doc_ids=[CHILDCARE_DOC],
    )
    body = client.post(
        "/ai/chat", json={"question": "아이돌봄 서비스 신청 어디서 해요?", "profile": PROFILE}
    ).json()
    assert body["generated"] is True and body["grounded"] is True
    assert body["sources"][0]["id"] == "423000000362"
    assert body["sources"][0]["url"]
    assert body["related_policies"] == [{"id": "423000000362", "name": "아이돌봄 서비스", "status": "eligible"}]
    assert len(body["suggested_questions"]) == 2


def test_chat_unknown_doc_ids_become_not_grounded(monkeypatch):
    fake_answer(monkeypatch, used_doc_ids=["policy:없는정책"])
    body = client.post("/ai/chat", json={"question": "아이돌봄 서비스", "profile": PROFILE}).json()
    assert body["grounded"] is False


def test_chat_model_says_not_grounded(monkeypatch):
    fake_answer(monkeypatch, grounded=False, intro="", used_doc_ids=[])
    body = client.post("/ai/chat", json={"question": "아이돌봄 서비스 30만원 수당", "profile": PROFILE}).json()
    assert body["grounded"] is False and body["items"] == []


def test_chat_adds_missing_income_condition(monkeypatch):
    fake_answer(
        monkeypatch,
        items=[{"title": "신청처", "text": "주민센터에서 신청해요."}],
        used_doc_ids=[AFTER_SCHOOL_DOC],
    )
    body = client.post("/ai/chat", json={"question": "방과후학교 자유수강권 신청", "profile": PROFILE}).json()
    assert body["items"][-1]["title"] == "확인할 조건"
    assert "소득" in body["items"][-1]["text"]


def test_chat_suggestions_skip_same_question(monkeypatch):
    fake_answer(monkeypatch, used_doc_ids=[CHILDCARE_DOC])
    body = client.post("/ai/chat", json={"question": "신청 기간 알려줘", "profile": PROFILE,
                                         "history": [{"role": "user", "text": "아이돌봄 서비스 알려줘"}]}).json()
    assert "신청 기간 알려줘" not in body["suggested_questions"]


def test_chat_validation():
    assert client.post("/ai/chat", json={"question": ""}).status_code == 422

"""아이케어 용인 AI 서버

실행
  uvicorn app.main:app --reload
API 문서
  http://localhost:8000/docs
"""

import logging

from fastapi import FastAPI, HTTPException

from app import config, data_loader
from app.schemas import (
    CareGapRequest,
    CareGapResponse,
    ChatRequest,
    ChatResponse,
    MatchRequest,
    MatchResponse,
    SummaryRequest,
    SummaryResponse,
)
from app.services import care_gap, chat, matching, summary

logging.basicConfig(level=logging.INFO)
# Gemini 요청마다 찍히는 통신 로그는 줄인다
for name in ("httpx", "google_genai"):
    logging.getLogger(name).setLevel(logging.WARNING)

app = FastAPI(
    title="아이케어 용인 AI 서버",
    description="정책 추천(F-003), 정책 요약(F-004), 돌봄 공백 분석(F-009), AI 돌봄·배움 챗봇",
    version="0.1.0",
)


@app.get("/health", tags=["상태"])
def health():
    return {
        "status": "ok",
        "policies": len(data_loader.load_policies()),
        "policy_summaries": len(data_loader.load_policy_summaries()),
        "facilities": len(data_loader.load_facilities()),
        "embeddings": len(data_loader.load_embeddings().get("docs", {})),
        "gemini_enabled": config.GEMINI_ENABLED,
    }


@app.post("/ai/policies/match", response_model=MatchResponse, tags=["F-003 정책 추천"])
def match_policies(req: MatchRequest):
    """프로필에 맞는 정책 목록과 적합도 점수 (규칙 기반, Gemini 호출 없음)"""
    return matching.match_policies(req.profile, req.include_ineligible, req.limit)


@app.post("/ai/policies/{policy_id}/summary", response_model=SummaryResponse, tags=["F-004 정책 요약"])
def policy_summary(policy_id: str, req: SummaryRequest = None):
    """4대 핵심 정보(미리 생성) + 가구 맞춤 팁(프로필이 있을 때 실시간) + 출처"""
    result = summary.get_summary(policy_id, req.profile if req else None)
    if result is None:
        raise HTTPException(status_code=404, detail=f"정책을 찾을 수 없습니다: {policy_id}")
    return result


@app.post("/ai/care-gap", response_model=CareGapResponse, tags=["F-009 돌봄 공백 분석"])
def analyze_care_gap(req: CareGapRequest):
    """돌봄 공백 시간 계산 + 시설 조합 추천 + 추천 이유 (규칙 기반, Gemini 호출 없음)"""
    try:
        return care_gap.analyze(req.profile, req.period, req.school_end, req.care_time, req.max_results)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/ai/chat", response_model=ChatResponse, tags=["AI 챗봇"])
def chat_answer(req: ChatRequest):
    """정책·시설 자료 검색(RAG) 후 근거가 있을 때만 답변 + 출처 + 관련 정책 바로가기 + 추천 질문"""
    return chat.answer(req.question, req.profile, req.history, req.user_name)

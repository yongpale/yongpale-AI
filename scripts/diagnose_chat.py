"""
[DIAG] 챗봇 '근거 없음' 원인 진단 (발표 후 삭제 가능)

질문마다 검색 방식(임베딩/키워드), 상위 3개 문서 점수, Gemini 판단(grounded, used_doc_ids)을 출력한다.
점수는 코사인 유사도라 클수록 비슷하다 (ChromaDB distance와 반대).

실행
  python3 scripts/diagnose_chat.py                 .env 그대로 (Gemini 사용)
  GEMINI_ENABLED=0 python3 scripts/diagnose_chat.py   Gemini 없이 (키 누락·한도 초과 상황 재현)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, data_loader  # noqa: E402
from app.schemas import Profile  # noqa: E402
from app.services import chat, gemini, retrieval  # noqa: E402

QUESTIONS = [
    "할 수 있는 돌봄 서비스 추천해줘",
    "초등학교 1학년 대상 돌봄 알려줘",
    "맞벌이인데 우리 아이가 받을 수 있는 돌봄 지원이 뭐가 있어요?",
    "내년에 아이가 3학년이 되면 뭐가 달라져요?",
    "서울 강남구 돌봄센터 알려줘",  # 데이터에 없음 → 근거 없음이어야 함
]
PROFILE = Profile.model_validate({
    "guName": "기흥구", "dongName": "구갈동", "childGrades": ["초1"], "dualIncome": True,
})


def main():
    print("[DIAG] 설정")
    print(f"  .env 경로: {config.BASE_DIR / '.env'} (존재: {(config.BASE_DIR / '.env').exists()})")
    print(f"  GEMINI_API_KEY 있음: {bool(config.GEMINI_API_KEY)}, GEMINI_ENABLED: {config.GEMINI_ENABLED}")
    print(f"  생성 모델: {config.GEMINI_LITE_MODEL}, 임베딩 모델: {config.GEMINI_EMBEDDING_MODEL} ({config.EMBEDDING_DIM}차원)")
    emb = data_loader.load_embeddings()
    print(f"  embeddings.json: {config.PROCESSED_DIR / 'embeddings.json'}")
    print(f"    문서 수 {len(emb.get('docs', {}))}, 만든 모델 {emb.get('model')}, 차원 {emb.get('dim')}")
    if emb and (emb.get("model") != config.GEMINI_EMBEDDING_MODEL or emb.get("dim") != config.EMBEDDING_DIM):
        print("    !! 인덱스 모델/차원이 질문 임베딩 설정과 다름")
    print(f"  검색 대상 문서: {len(retrieval._index()[0])}")
    print(f"  키워드 검색 기준 점수: {chat.KEYWORD_MIN_SCORE}")

    v = gemini.embed_query("돌봄 서비스")
    print(f"  질문 임베딩 호출: {'성공' if v is not None else '실패 → 키워드 검색으로 전환됨'}")

    for q in QUESTIONS:
        print(f"\n[DIAG] 질문: {q}")
        results, method = retrieval.search(q, top_k=chat.TOP_K)
        print(f"  검색 방식: {method}")
        for d, s in results[:3]:
            print(f"    {s:.3f}  {d['id']}  {d['text'][:60].replace(chr(10), ' / ')}")
        if method == "keyword":
            kept = [s for _, s in results if s >= chat.KEYWORD_MIN_SCORE]
            print(f"  기준({chat.KEYWORD_MIN_SCORE}) 이상: {len(kept)}건")
        body = chat.answer(q, PROFILE)
        print(f"  결과: grounded={body['grounded']} generated={body['generated']} "
              f"출처={[s['id'] for s in body['sources']]}")
        print(f"  답변: {body['intro'][:80]}")


if __name__ == "__main__":
    if os.getenv("DIAG_NO_CACHE", "1") == "1":
        # 예전에 캐시된 답변이 아니라 지금 상태로 판단하도록 임시 캐시 사용
        import tempfile
        chat._answer_cache.path = Path(tempfile.mkdtemp()) / "chat_answers.json"
    main()

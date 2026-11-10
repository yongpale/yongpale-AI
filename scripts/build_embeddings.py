"""
챗봇 검색용 임베딩 만들기 (정책·시설 문서)

문서 내용이 바뀌지 않은 것은 다시 만들지 않는다.
정책·시설·요약 데이터를 바꾼 뒤 다시 실행한다.

입력  data/processed/policies.json, facilities.json, policy_summaries.json
출력  data/processed/embeddings.json

실행
  python3 scripts/build_embeddings.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services.documents import all_documents, text_hash  # noqa: E402

OUT_FILE = config.PROCESSED_DIR / "embeddings.json"
# 무료 등급은 분당 토큰 한도(3만)가 있어서 조금씩 보내고 한도에 걸리면 기다린다
BATCH_SIZE = 10
RETRIES = 4


def main():
    if not config.GEMINI_API_KEY:
        print(".env에 GEMINI_API_KEY가 없습니다")
        sys.exit(1)
    from google import genai
    from google.genai import types

    docs = all_documents()
    old = {}
    if OUT_FILE.exists():
        with open(OUT_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("model") == config.GEMINI_EMBEDDING_MODEL and saved.get("dim") == config.EMBEDDING_DIM:
            old = saved["docs"]

    vectors = {}
    todo = []
    for d in docs:
        h = text_hash(d["text"])
        if d["id"] in old and old[d["id"]]["hash"] == h:
            vectors[d["id"]] = old[d["id"]]
        else:
            todo.append((d, h))
    print(f"[임베딩] 문서 {len(docs)}건, 이번에 생성 {len(todo)}건 (모델 {config.GEMINI_EMBEDDING_MODEL})")

    client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=120_000))
    cfg = types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=config.EMBEDDING_DIM)
    failed = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        for attempt in range(1, RETRIES + 1):
            try:
                res = client.models.embed_content(
                    model=config.GEMINI_EMBEDDING_MODEL, contents=[d["text"] for d, _ in batch], config=cfg
                )
                break
            except Exception as e:
                print(f"  실패 ({type(e).__name__}: {str(e)[:100]}), {attempt}/{RETRIES}회 → 40초 후 재시도")
                res = None
                if attempt < RETRIES:
                    time.sleep(40)
        if res is None:
            failed += len(batch)
            continue
        for (d, h), emb in zip(batch, res.embeddings):
            vectors[d["id"]] = {"hash": h, "vector": [round(v, 6) for v in emb.values]}
        # 묶음마다 저장해서 중간에 멈춰도 이어서 실행 가능
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump({"model": config.GEMINI_EMBEDDING_MODEL, "dim": config.EMBEDDING_DIM, "docs": vectors}, f)
        print(f"  {min(start + BATCH_SIZE, len(todo))}/{len(todo)}")
        time.sleep(8)

    print(f"  저장: {OUT_FILE.relative_to(config.BASE_DIR)} ({len(vectors)}건)")
    if failed:
        print(f"  만들지 못한 문서 {failed}건 → 다시 실행하면 그 문서만 다시 시도합니다")


if __name__ == "__main__":
    main()

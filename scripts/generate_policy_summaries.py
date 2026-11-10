"""
정책 4대 핵심 정보 요약 미리 만들기 (F-004)

Gemini 무료 한도가 적어서 요약은 서버에서 실시간으로 만들지 않고 이 스크립트로 미리 만든다.
정책 원문이 바뀌지 않은 정책(source.updated_at 동일)은 다시 만들지 않는다.

입력  data/processed/policies.json
출력  data/processed/policy_summaries.json

실행
  python3 scripts/generate_policy_summaries.py          새로 생겼거나 바뀐 정책만
  python3 scripts/generate_policy_summaries.py --redo   전체 다시
  GEMINI_MODEL=gemini-3.5-flash-lite python3 scripts/generate_policy_summaries.py   모델 바꿔서
"""

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import List, Literal

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

POLICIES_FILE = config.PROCESSED_DIR / "policies.json"
OUT_FILE = config.PROCESSED_DIR / "policy_summaries.json"
BATCH_SIZE = 6
RETRIES = 3

# 원문 항목 (policies.json 필드 → 프롬프트·근거 표시용 이름)
SECTIONS = {
    "target": "지원대상",
    "criteria": "선정기준",
    "benefits": "지원내용",
    "how_to_apply": "신청방법",
    "documents": "구비서류",
    "documents_self_check": "본인확인 필요 서류",
    "documents_official_check": "공무원 확인 서류",
}
APPLY_SECTIONS = {"deadline": "신청기한", "reception": "접수기관", "contact": "문의처"}
SectionName = Literal[
    "지원대상", "선정기준", "지원내용", "신청방법", "구비서류",
    "본인확인 필요 서류", "공무원 확인 서류", "신청기한", "접수기관", "문의처",
]


class Item(BaseModel):
    text: str
    evidence: List[SectionName]


class PolicySummary(BaseModel):
    id: str
    eligibility: Item
    benefits: Item
    documents: Item
    period: Item


class BatchResult(BaseModel):
    results: List[PolicySummary]


PROMPT = """너는 용인시 초등학생 자녀를 둔 부모에게 공공 지원 정책을 쉽게 설명하는 담당자다.
아래 정책 원문만 근거로 정책마다 4대 핵심 정보를 정리해라.

- eligibility(신청 자격): 누가 받을 수 있는지. 초등학생 자녀 가정에 해당하는 부분 중심
- benefits(지원 혜택): 무엇을 얼마나 지원하는지. 금액·횟수가 있으면 포함
- documents(필요 서류): 신청할 때 내야 하는 서류
- period(신청 기간): 언제 신청하는지와 어디에(접수기관) 신청하는지

규칙
- 원문에 없는 내용은 절대 만들지 마라. 원문에 정보가 없으면 text에 "원문에 안내가 없어요. 문의처에 확인해 주세요."라고 써라.
- 항목마다 2~3문장 이내, 부모가 읽기 쉬운 존댓말("~해요")로 써라.
- 기간·금액·연도 등 숫자는 원문 그대로 써라. 원문의 기준 연도가 있으면 함께 적어라.
- evidence에는 실제로 근거로 사용한 원문 항목 이름만 넣어라.

정책 원문:
{policies}
"""


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def policy_for_prompt(p):
    data = {"id": p["id"], "서비스명": p["name"], "소관기관": p["agency"]}
    for key, label in SECTIONS.items():
        if p["texts"].get(key):
            data[label] = p["texts"][key]
    for key, label in APPLY_SECTIONS.items():
        if p["apply"].get(key):
            data[label] = p["apply"][key]
    return data


def summarize_batch(client, batch):
    from google.genai import types

    prompt = PROMPT.format(
        policies=json.dumps([policy_for_prompt(p) for p in batch], ensure_ascii=False, indent=1)
    )
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=BatchResult, temperature=0
    )
    for attempt in range(1, RETRIES + 1):
        try:
            res = client.models.generate_content(model=config.GEMINI_MODEL, contents=prompt, config=cfg)
            return BatchResult.model_validate_json(res.text).results
        except Exception as e:
            wait = 20 * attempt
            print(f"  실패 ({type(e).__name__}: {str(e)[:120]}), {attempt}/{RETRIES}회 → {wait}초 후 재시도")
            if attempt == RETRIES:
                return None
            time.sleep(wait)


def main():
    if not config.GEMINI_API_KEY:
        print(".env에 GEMINI_API_KEY가 없습니다")
        sys.exit(1)
    from google import genai
    from google.genai import types

    redo = "--redo" in sys.argv
    policies = load_json(POLICIES_FILE, [])
    summaries = {} if redo else load_json(OUT_FILE, {})
    # 정책이 빠졌으면 요약도 지운다
    summaries = {pid: s for pid, s in summaries.items() if any(p["id"] == pid for p in policies)}
    todo = [
        p for p in policies
        if p["id"] not in summaries or summaries[p["id"]].get("source_updated_at") != p["source"]["updated_at"]
    ]
    print(f"[요약] 정책 {len(policies)}건, 이번에 생성 {len(todo)}건 (모델 {config.GEMINI_MODEL})")

    # 응답이 오지 않는 요청을 끝없이 기다리지 않도록 시간 제한
    client = genai.Client(api_key=config.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=120_000))
    today = date.today().isoformat()
    failed = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        results = summarize_batch(client, batch)
        if results is None:
            failed += len(batch)
            continue
        by_id = {p["id"]: p for p in batch}
        for r in results:
            if r.id not in by_id:
                continue
            summaries[r.id] = {
                **r.model_dump(exclude={"id"}),
                "model": config.GEMINI_MODEL,
                "generated_at": today,
                "source_updated_at": by_id[r.id]["source"]["updated_at"],
            }
        failed += len(set(by_id) - {r.id for r in results})
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(summaries, f, ensure_ascii=False, indent=2)
        print(f"  {min(start + BATCH_SIZE, len(todo))}/{len(todo)}")
        time.sleep(4)

    print(f"  저장: {OUT_FILE.relative_to(config.BASE_DIR)} ({len(summaries)}건)")
    if failed:
        print(f"  생성하지 못한 정책 {failed}건 → 다시 실행하면 그 정책만 다시 시도합니다 (서버는 원문 발췌로 대체)")


if __name__ == "__main__":
    main()

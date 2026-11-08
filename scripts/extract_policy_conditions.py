"""
정책 데이터 전처리 (2단계: Gemini로 매칭 조건 추출)

입력
  data/processed/policy_candidates.json   (scripts/preprocess_policies.py 결과)

출력
  data/interim/policy_extractions.json    정책별 추출 결과 (캐시, 이미 처리한 정책은 다시 호출하지 않음)
  data/review/policy_review.csv           사람 검토용 표 (엑셀·Numbers로 열기)

검토가 끝나면 scripts/build_policies.py 로 data/processed/policies.json 을 만든다.

실행
  python3 scripts/extract_policy_conditions.py           전체 (캐시에 없는 정책만 호출)
  python3 scripts/extract_policy_conditions.py --test    앞의 한 묶음만
  python3 scripts/extract_policy_conditions.py --redo    캐시 무시하고 전체 다시

.env
  GEMINI_API_KEY, GEMINI_MODEL
"""

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Literal, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = BASE_DIR / "data" / "processed" / "policy_candidates.json"
CACHE_FILE = BASE_DIR / "data" / "interim" / "policy_extractions.json"
REVIEW_FILE = BASE_DIR / "data" / "review" / "policy_review.csv"

load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL")

BATCH_SIZE = 10
MAX_TEXT = 1500  # 항목별 원문 최대 글자 수
RETRIES = 4

Requirement = Literal["required", "preferred", "not_mentioned"]
Category = Literal["돌봄", "방과후·학습", "교육비", "생활·경제", "건강·의료", "보호·상담", "문화·체험", "기타"]


class Extraction(BaseModel):
    id: str
    relevant: bool
    relevance_reason: str
    category: Category
    grade_min: Optional[int]
    grade_max: Optional[int]
    dual_income: Requirement
    single_parent: Requirement
    multi_child: Requirement
    low_income_only: bool
    income_limit: Optional[str]
    other_requirements: List[str]
    apply_period: Optional[str]


class BatchResult(BaseModel):
    results: List[Extraction]


PROMPT = """너는 용인시 초등학생 자녀를 둔 가정에 공공 지원 정책을 추천하는 서비스의 데이터 담당자다.
아래 정책 원문을 읽고, 정책마다 다음 항목을 JSON으로 정리해라. 원문에 없는 내용은 추측하지 마라.

- id: 입력의 id 그대로
- relevant: 용인시에 사는 초등학생(1~6학년) 자녀의 부모나 그 자녀가 직접 신청하거나 받을 수 있는 정책이면 true.
  다음은 false: 시설·기관·단체·교사가 대상인 사업, 견학·관람 등 단발성 행사, 특정 지역(용인시·경기도가 아닌 곳) 주민 전용, 초등학생이 대상에 포함되지 않는 정책
- relevance_reason: relevant 판단 이유를 한 문장으로
- category: 돌봄 / 방과후·학습 / 교육비 / 생활·경제 / 건강·의료 / 보호·상담 / 문화·체험 / 기타 중 하나
- grade_min, grade_max: 대상 초등 학년 범위(1~6). 원문에 나이만 있으면 만 6세=1학년, 만 12세=6학년으로 환산. 초등학생 전체이거나 알 수 없으면 1, 6. relevant가 false면 null
- dual_income, single_parent, multi_child: 맞벌이 / 한부모·조손 / 다자녀 가구 조건
  required = 그 가구만 대상, preferred = 우선 선정·추가 지원 등 우대, not_mentioned = 언급 없음
- low_income_only: 기초생활수급자·차상위·중위소득 기준 등 저소득 가구만 대상이면 true
- income_limit: 소득 기준 문구를 원문 그대로 짧게 (없으면 null)
- other_requirements: 그 밖의 필수 조건 (예: "장애아동", "다문화가족", "국가보훈대상자 자녀") 짧은 명사구 목록. 없으면 빈 목록
- apply_period: 신청 기간 문구 (예: "상시", "매년 3월") 없으면 null

정책 원문:
{policies}
"""


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cut(text):
    if not text:
        return None
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…(생략)"


def policy_for_prompt(p):
    t = p["texts"]
    return {
        "id": p["id"],
        "서비스명": p["name"],
        "소관기관": p["agency"],
        "서비스목적요약": p["summary"],
        "지원대상": cut(t["target"]),
        "선정기준": cut(t["criteria"]),
        "지원내용": cut(t["benefits"]),
        "신청방법": cut(t["how_to_apply"]),
        "신청기한": p["apply"]["deadline"],
        "대상연령": [p["conditions"]["age_min"], p["conditions"]["age_max"]],
    }


def extract_batch(client, batch):
    prompt = PROMPT.format(
        policies=json.dumps([policy_for_prompt(p) for p in batch], ensure_ascii=False, indent=1)
    )
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=BatchResult,
        temperature=0,
    )
    for attempt in range(1, RETRIES + 1):
        try:
            res = client.models.generate_content(model=MODEL, contents=prompt, config=config)
            return BatchResult.model_validate_json(res.text).results
        except Exception as e:
            # 무료 한도(분당 요청 수) 초과 등은 기다렸다가 다시 시도
            wait = 20 * attempt
            print(f"  실패 ({type(e).__name__}: {str(e)[:120]}), {attempt}/{RETRIES}회 → {wait}초 후 재시도")
            if attempt == RETRIES:
                return None
            time.sleep(wait)


def write_review_csv(candidates, cache):
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "include", "id", "name", "agency", "relevant", "relevance_reason", "category",
        "grade_min", "grade_max", "dual_income", "single_parent", "multi_child",
        "low_income_only", "income_limit", "other_requirements", "apply_period", "source_url",
    ]
    # 엑셀에서 한글이 깨지지 않도록 utf-8-sig
    with open(REVIEW_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for p in candidates:
            e = cache.get(p["id"])
            if e is None:
                continue
            writer.writerow({
                # 검토자가 Y/N 으로 고친다. 기본값은 Gemini 판단
                "include": "Y" if e["relevant"] else "N",
                "id": p["id"],
                "name": p["name"],
                "agency": p["agency"],
                **{k: e[k] for k in columns if k in e and k != "other_requirements"},
                "other_requirements": " / ".join(e["other_requirements"]),
                "source_url": p["source"]["url"],
            })
    print(f"  저장: {REVIEW_FILE.relative_to(BASE_DIR)}")


def main():
    if not API_KEY or not MODEL:
        print(".env에 GEMINI_API_KEY, GEMINI_MODEL이 없습니다")
        sys.exit(1)

    test = "--test" in sys.argv
    redo = "--redo" in sys.argv

    candidates = load_json(CANDIDATES_FILE, [])
    cache = {} if redo else load_json(CACHE_FILE, {})
    todo = [p for p in candidates if p["id"] not in cache]
    if test:
        todo = todo[:BATCH_SIZE]
    print(f"[조건 추출] 후보 {len(candidates)}건, 이미 처리 {len(cache)}건, 이번에 처리 {len(todo)}건 (모델 {MODEL})")

    client = genai.Client(api_key=API_KEY)
    failed = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        results = extract_batch(client, batch)
        if results is None:
            failed += len(batch)
            continue
        expected = {p["id"] for p in batch}
        for r in results:
            if r.id in expected:
                cache[r.id] = {**r.model_dump(), "model": MODEL}
        missing = expected - {r.id for r in results}
        failed += len(missing)
        # 묶음마다 저장해서 중간에 멈춰도 이어서 실행 가능
        save_json(cache, CACHE_FILE)
        print(f"  {min(start + BATCH_SIZE, len(todo))}/{len(todo)}")
        time.sleep(4)

    print(f"  저장: {CACHE_FILE.relative_to(BASE_DIR)} ({len(cache)}건)")
    if failed:
        print(f"  처리하지 못한 정책 {failed}건 → 다시 실행하면 그 정책만 다시 시도합니다")
    write_review_csv(candidates, cache)

    relevant = sum(1 for e in cache.values() if e["relevant"])
    print(f"\n관련 있음 {relevant}건 / 없음 {len(cache) - relevant}건")


if __name__ == "__main__":
    main()

"""데이터 읽기는 이 파일에서만 한다.

지금은 data/processed/ 의 JSON 파일을 읽는다. 백엔드 데이터 형식(DB, API)이 확정되면
이 파일의 함수만 바꾸고, 반환 형식(dict 목록)은 그대로 유지한다.
"""

import json
from functools import lru_cache

from app.config import PROCESSED_DIR


def _read(filename, default=None):
    path = PROCESSED_DIR / filename
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"{path} 가 없습니다. scripts/ 의 전처리 스크립트를 먼저 실행하세요.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache()
def load_policies():
    """정책 목록 (policies.json)"""
    return _read("policies.json")


@lru_cache()
def load_policy_map():
    return {p["id"]: p for p in load_policies()}


def get_policy(policy_id):
    return load_policy_map().get(policy_id)


@lru_cache()
def load_facilities():
    """돌봄시설 목록 (facilities.json)"""
    return _read("facilities.json")


@lru_cache()
def load_childcare_documents():
    """아이돌봄 정부지원 입증서류 (childcare_documents.json)"""
    return _read("childcare_documents.json")


@lru_cache()
def load_policy_summaries():
    """미리 생성한 정책 4항목 요약 (policy_summaries.json). 없으면 빈 dict"""
    return _read("policy_summaries.json", default={})


@lru_cache()
def load_embeddings():
    """챗봇 검색용 임베딩 (embeddings.json). 없으면 빈 dict → 키워드 검색으로 대체"""
    return _read("embeddings.json", default={})


def clear_cache():
    """데이터 파일을 바꾼 뒤 서버를 끄지 않고 다시 읽을 때"""
    for fn in (load_policies, load_policy_map, load_facilities, load_childcare_documents, load_policy_summaries,
               load_embeddings):
        fn.cache_clear()

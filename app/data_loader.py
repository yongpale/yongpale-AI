"""데이터 읽기는 이 파일에서만 한다.

지금은 data/processed/ 의 JSON 파일을 읽는다. 백엔드 데이터 형식(DB, API)이 확정되면
이 파일의 함수만 바꾸고, 반환 형식(dict 목록)은 그대로 유지한다.
"""

import json
import re
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


def find_policy(policy_id=None, source_url=None, title=None):
    """정부24 서비스ID, 원문 URL, 정책명 중 하나로 정책을 찾는다.

    백엔드 policies 테이블에는 서비스ID가 없지만 source_url(…&svcId=서비스ID)과 title이 있어서
    백엔드가 가진 값만으로 찾을 수 있게 한다.
    """
    if policy_id:
        return get_policy(policy_id)
    if source_url:
        m = re.search(r"svcId=([^&#]+)", source_url)
        if m and get_policy(m.group(1)):
            return get_policy(m.group(1))
        return next((p for p in load_policies() if p["source"].get("url") == source_url), None)
    if title:
        key = re.sub(r"\s+", "", title)
        return next((p for p in load_policies() if re.sub(r"\s+", "", p["name"]) == key), None)
    return None


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
def load_guides():
    """챗봇 안내 문서 (guides.json, scripts/build_guides.py). 없으면 빈 목록"""
    return _read("guides.json", default=[])


@lru_cache()
def load_embeddings():
    """챗봇 검색용 임베딩 (embeddings.json). 없으면 빈 dict → 키워드 검색으로 대체"""
    return _read("embeddings.json", default={})


def clear_cache():
    """데이터 파일을 바꾼 뒤 서버를 끄지 않고 다시 읽을 때"""
    for fn in (load_policies, load_policy_map, load_facilities, load_childcare_documents, load_policy_summaries,
               load_embeddings, load_guides):
        fn.cache_clear()

"""챗봇 검색: 질문과 비슷한 정책·시설 문서를 찾는다.

임베딩(embeddings.json + 질문 임베딩)으로 찾고, 임베딩을 쓸 수 없으면 글자 단위 키워드 검색으로 대신한다.
"""

import re
from functools import lru_cache

import numpy as np

from app import data_loader
from app.services import documents, gemini


@lru_cache()
def _index():
    """(문서 목록, 정규화된 벡터 행렬). 임베딩이 없는 문서는 키워드 검색에만 쓰인다"""
    docs = documents.all_documents()
    saved = data_loader.load_embeddings().get("docs", {})
    with_vec = [d for d in docs if d["id"] in saved]
    if not with_vec:
        return docs, [], None
    matrix = np.array([saved[d["id"]]["vector"] for d in with_vec], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    return docs, with_vec, matrix


@lru_cache(maxsize=256)
def _query_vector(text):
    vec = gemini.embed_query(text)
    if vec is None:
        return None
    v = np.array(vec, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _bigrams(text):
    text = re.sub(r"\s+", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def keyword_search(query, docs, top_k):
    q = _bigrams(query)
    if not q:
        return []
    scored = []
    for d in docs:
        overlap = len(q & _bigrams(d["title"] + d["text"][:400]))
        if overlap:
            scored.append((d, overlap / len(q)))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def search(query, top_k=5):
    """[(문서, 점수)] 점수 높은 순, 그리고 사용한 방식('embedding' 또는 'keyword')"""
    docs, with_vec, matrix = _index()
    qv = _query_vector(query) if matrix is not None else None
    if qv is None:
        return keyword_search(query, docs, top_k), "keyword"
    scores = matrix @ qv
    order = np.argsort(-scores)[:top_k]
    return [(with_vec[i], float(scores[i])) for i in order], "embedding"


def clear_index():
    _index.cache_clear()
    _query_vector.cache_clear()

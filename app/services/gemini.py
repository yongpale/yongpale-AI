"""Gemini 호출. 실패(한도 초과, 시간 초과, 키 없음)하면 None을 돌려주고 호출한 쪽이 대체 응답을 쓴다."""

import json
import logging
import threading
from hashlib import sha256

from app import config

logger = logging.getLogger(__name__)

_client = None
_cache_lock = threading.Lock()


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=int(config.GEMINI_TIMEOUT_SECONDS * 1000)),
        )
    return _client


def generate_text(prompt, model=None, temperature=0.3):
    """텍스트 생성. 실패하면 None"""
    if not config.GEMINI_ENABLED:
        return None
    from google.genai import types

    try:
        res = _get_client().models.generate_content(
            model=model or config.GEMINI_LITE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        text = (res.text or "").strip()
        return text or None
    except Exception as e:  # 한도 초과(429), 서버 과부하(503), 시간 초과 등
        logger.warning("Gemini 호출 실패: %s", str(e)[:200])
        return None


class FileCache:
    """생성 결과를 JSON 파일에 저장해 같은 요청에 Gemini를 다시 호출하지 않는다."""

    def __init__(self, filename):
        self.path = config.CACHE_DIR / filename
        self._data = None

    def _load(self):
        if self._data is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                self._data = {}
        return self._data

    @staticmethod
    def key(*parts):
        raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
        return sha256(raw.encode("utf-8")).hexdigest()[:32]

    def get(self, key):
        with _cache_lock:
            return self._load().get(key)

    def set(self, key, value):
        with _cache_lock:
            data = self._load()
            data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            tmp.replace(self.path)


def embed_query(text):
    """검색 질문 임베딩. 실패하면 None"""
    if not config.GEMINI_ENABLED:
        return None
    from google.genai import types

    try:
        res = _get_client().models.embed_content(
            model=config.GEMINI_EMBEDDING_MODEL,
            contents=[text],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=config.EMBEDDING_DIM),
        )
        return res.embeddings[0].values
    except Exception as e:
        logger.warning("임베딩 실패: %s", str(e)[:200])
        return None


def generate_json(prompt, schema, model=None, temperature=0.2):
    """JSON 생성 (schema: pydantic 모델). 실패하면 None"""
    if not config.GEMINI_ENABLED:
        return None
    from google.genai import types

    try:
        res = _get_client().models.generate_content(
            model=model or config.GEMINI_LITE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=schema, temperature=temperature
            ),
        )
        return schema.model_validate_json(res.text)
    except Exception as e:
        logger.warning("Gemini 호출 실패: %s", str(e)[:200])
        return None

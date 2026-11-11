"""환경변수 설정 (.env)"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"

load_dotenv(BASE_DIR / ".env")

# Gemini 생성 결과 캐시 (맞춤 팁 등)
CACHE_DIR = Path(os.getenv("AI_CACHE_DIR", str(DATA_DIR / "cache")))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# 미리 생성하는 요약용 (무료 한도가 적어서 스크립트에서만 사용)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# 실시간 응답용 (맞춤 팁 등)
GEMINI_LITE_MODEL = os.getenv("GEMINI_LITE_MODEL", "gemini-3.5-flash-lite")
# 챗봇 검색용 임베딩
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = 768
# 0이면 Gemini를 호출하지 않고 대체 응답만 사용 (테스트, 한도 소진 시)
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "1") != "0" and bool(GEMINI_API_KEY)
# Gemini API 요청 제한 시간 (API가 허용하는 최솟값이 10초)
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "10"))
# 서버가 Gemini 응답을 기다리는 시간. 넘으면 기다리지 않고 대체 응답을 보낸다.
# 백엔드가 AI 응답을 15초까지 기다리므로 챗봇(임베딩 + 답변 생성)도 그 안에 끝나게 한다.
GEMINI_EMBED_BUDGET_SECONDS = float(os.getenv("GEMINI_EMBED_BUDGET_SECONDS", "3"))
GEMINI_GENERATE_BUDGET_SECONDS = float(os.getenv("GEMINI_GENERATE_BUDGET_SECONDS", "8"))

import os
import tempfile

# 테스트에서는 Gemini를 호출하지 않고 (무료 한도 보호, 대체 응답 경로 확인)
# 실제 서버가 저장한 캐시도 읽지 않는다
os.environ["GEMINI_ENABLED"] = "0"
os.environ["AI_CACHE_DIR"] = tempfile.mkdtemp(prefix="ai-cache-")

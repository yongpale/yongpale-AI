import time

from app.services.gemini import _within


def test_within_returns_value():
    assert _within(1, lambda: "ok", "테스트") == "ok"


def test_within_gives_up_when_slow():
    start = time.time()
    assert _within(0.1, lambda: time.sleep(0.5) or "late", "테스트") is None
    assert time.time() - start < 0.4


def test_within_returns_none_on_error():
    def fail():
        raise RuntimeError("429")
    assert _within(1, fail, "테스트") is None

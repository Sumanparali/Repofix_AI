import io
import json
import urllib.error
import urllib.request

import pytest

from repofix.llm import LLMError, _extract_gemini_text, _send_request, generate_patch
from repofix.models import ProjectProfile


def test_quota_error_has_actionable_billing_message(monkeypatch) -> None:
    body = json.dumps(
        {"error": {"code": "insufficient_quota", "message": "Quota exceeded"}}
    ).encode()

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://api.openai.com/v1/responses", 429, "Too Many Requests", {}, io.BytesIO(body)
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    with pytest.raises(LLMError, match="Add API billing credits"):
        _send_request(urllib.request.Request("https://api.openai.com/v1/responses"))


def test_gemini_patch_generation_uses_server_side_key(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return io.BytesIO(json.dumps({
                "candidates": [{"content": {"parts": [{"text": "```diff\n--- a/app.py\n+++ b/app.py\n```"}]}}]
            }).encode())

        def __exit__(self, *args):
            return False

    def respond(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("REPOFIX_AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret")
    monkeypatch.setattr(urllib.request, "urlopen", respond)
    profile = ProjectProfile("python", None, None, ())

    patch = generate_patch("fix the broken value", profile, "app.py", "gemini-3.5-flash-lite")

    request = captured["request"]
    assert request.full_url.endswith("/gemini-3.5-flash-lite:generateContent")
    assert request.get_header("X-goog-api-key") == "test-secret"
    assert "test-secret" not in request.full_url
    assert patch == "--- a/app.py\n+++ b/app.py"


def test_extract_gemini_text_combines_response_parts() -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": "one"}, {"text": "two"}]}}]}
    assert _extract_gemini_text(payload) == "onetwo"


def test_temporary_gemini_unavailability_is_retried(monkeypatch) -> None:
    attempts = 0
    body = json.dumps({"error": {"message": "High demand"}}).encode()

    class Response:
        def __enter__(self):
            return io.BytesIO(b'{"ok": true}')

        def __exit__(self, *args):
            return False

    def respond(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.HTTPError(
                "https://generativelanguage.googleapis.com", 503, "Unavailable", {}, io.BytesIO(body)
            )
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    monkeypatch.setattr("repofix.llm.time.sleep", lambda _: None)

    assert _send_request(urllib.request.Request("https://example.com"), "Gemini") == {"ok": True}
    assert attempts == 3



import io
import json
import urllib.error
import urllib.request

import pytest

from repofix.llm import LLMError, _send_request, generate_patch
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



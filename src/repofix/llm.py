from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .models import ProjectProfile


class LLMError(RuntimeError):
    pass


def generate_patch(
    issue: str,
    profile: ProjectProfile,
    context: str,
    model: str,
    failure_feedback: str | None = None,
) -> str:
    provider = os.getenv("REPOFIX_AI_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "gemini"}:
        raise LLMError("REPOFIX_AI_PROVIDER must be either openai or gemini.")

    feedback = ""
    if failure_feedback:
        feedback = f"""
The previous repair attempt failed. Use this test feedback to improve the fix:
{failure_feedback}
"""
    prompt = f"""You are repairing a {profile.language} repository.
Issue:
{issue}

Relevant repository files:
{context}
{feedback}

Create the smallest correct fix and add or update a regression test when appropriate.
Preserve existing architecture and conventions. Avoid unrelated refactoring.
Return only a valid git unified diff, with no Markdown fence or explanation.
"""
    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set. Add it to .env and restart RepoFix.")
        safe_model = urllib.parse.quote(model, safe="-._")
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{safe_model}:generateContent"
        )
        provider_name = "Gemini"
        request_body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1},
        }
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "RepoFix-AI/0.1",
        }
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set. Add it to .env and restart RepoFix.")
        endpoint = "https://api.openai.com/v1/responses"
        provider_name = "OpenAI"
        request_body = {"model": model, "input": prompt}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "RepoFix-AI/0.1",
        }

    body = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers=headers,
    )
    payload = _send_request(request, provider_name)
    text = (
        _extract_gemini_text(payload)
        if provider == "gemini"
        else payload.get("output_text") or _extract_output_text(payload)
    )
    if not text:
        raise LLMError("The LLM response did not contain text output.")
    return _strip_fence(text)


def _send_request(request: urllib.request.Request, provider_name: str = "OpenAI") -> dict:
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            error = _http_error_details(exc)
            code = str(error.get("code") or "")
            message = str(error.get("message") or exc.reason)
            if exc.code in {429, 503} and code != "insufficient_quota" and attempt < max_attempts - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            if exc.code == 429 and code == "insufficient_quota":
                if provider_name == "Gemini":
                    action = "Check the free-tier quota in Google AI Studio, then retry after it resets."
                else:
                    action = (
                        "Add API billing credits at platform.openai.com/settings/organization/billing, "
                        "then retry the analysis."
                    )
                raise LLMError(
                    f"{provider_name} API quota is unavailable. {action}"
                ) from exc
            if exc.code == 429:
                raise LLMError(
                    f"{provider_name} rate limit remained active after {max_attempts} attempts: {message}"
                ) from exc
            if exc.code == 503:
                raise LLMError(
                    f"{provider_name} remained temporarily unavailable after {max_attempts} attempts: "
                    f"{message}"
                ) from exc
            raise LLMError(f"{provider_name} API request failed ({exc.code}): {message}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"{provider_name} API request failed: {exc}") from exc
    raise LLMError(f"{provider_name} API request could not be completed.")


def _http_error_details(exc: urllib.error.HTTPError) -> dict:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        return payload.get("error") or {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _extract_output_text(payload: dict) -> str:
    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    return "".join(chunks)


def _extract_gemini_text(payload: dict) -> str:
    chunks: list[str] = []
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if text:
                chunks.append(text)
    return "".join(chunks)


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text

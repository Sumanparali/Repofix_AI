from __future__ import annotations

import os
import re
import json
from dataclasses import asdict
from pathlib import Path

from .queueing import QueueUnavailable, cancel_analysis, enqueue_analysis, queue_health
from .auth import current_identity, firebase_config, reset_identity, set_identity, verify_bearer
from .repository import RepositoryError, validate_github_repository_url
from .store import JobStore


def _issue_quality_error(issue: str) -> str | None:
    words = re.findall(r"[A-Za-z]+", issue)
    if any(len(word) > 22 for word in words) or re.search(
        r"[bcdfghjklmnpqrstvwxyz]{7,}", issue, re.IGNORECASE
    ):
        return "This looks like random text. Describe what is wrong, what you expected, and how to reproduce it."
    if len(issue.strip()) < 20 or len(words) < 4:
        return "Describe the issue or improvement using at least four meaningful words."
    words_with_vowels = sum(bool(re.search(r"[aeiouy]", word, re.IGNORECASE)) for word in words)
    if words_with_vowels / len(words) < 0.4:
        return "This text is not descriptive enough. Use a clear sentence about the requested fix or improvement."
    return None


def _analysis_only() -> bool:
    return os.getenv("REPOFIX_ANALYSIS_ONLY", "0").strip().lower() in {"1", "true", "yes"}


def _ai_enabled() -> bool:
    provider = os.getenv("REPOFIX_AI_PROVIDER", "openai").strip().lower()
    key_name = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    return provider in {"openai", "gemini"} and bool(os.getenv(key_name, "").strip())


def _default_model() -> str:
    configured = os.getenv("REPOFIX_MODEL", "").strip()
    if configured:
        return configured
    if os.getenv("REPOFIX_AI_PROVIDER", "openai").strip().lower() == "gemini":
        return "gemini-3.8-flash"
    return "gpt-6.1-terra"


def _allowed_modes() -> set[str]:
    modes = {"analyze"}
    if not _analysis_only() and _ai_enabled():
        modes.add("generate")
    if os.getenv("REPOFIX_ALLOW_REPAIR", "0").strip().lower() in {"1", "true", "yes"}:
        modes.add("repair")
    return modes


def create_app(database: str | Path = Path("repofix.db"), enqueue=enqueue_analysis):
    try:
        from fastapi import FastAPI, Header, HTTPException, Request
        from fastapi.responses import HTMLResponse, PlainTextResponse, Response
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError('Install web dependencies with: pip install -e ".[web]"') from exc
    store = JobStore(database)
    app = FastAPI(
        title="RepoFix AI",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.middleware("http")
    async def disable_local_asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/") or not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    def identity(authorization: str | None = Header(default=None)) -> dict:
        try:
            value = verify_bearer(authorization)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        store.ensure_user(value["uid"], value.get("email"), value.get("name"))
        return value

    @app.get("/api/auth/config")
    def auth_config():
        return firebase_config()

    @app.middleware("http")
    async def authenticate_api(request: Request, call_next):
        if not request.url.path.startswith("/api/jobs"):
            return await call_next(request)
        try:
            value = verify_bearer(request.headers.get("authorization"))
        except ValueError as exc:
            return Response(
                content='{"detail":"' + str(exc) + '"}', status_code=401,
                media_type="application/json",
            )
        store.ensure_user(value["uid"], value.get("email"), value.get("name"))
        token = set_identity(value)
        try:
            return await call_next(request)
        finally:
            reset_identity(token)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/logout", response_class=HTMLResponse)
    def logout_page():
        config = json.dumps(firebase_config().get("config", {}))
        return HTMLResponse(
            """<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>Signing out — RepoFix AI</title></head><body style=\"margin:0;min-height:100vh;display:grid;place-items:center;color:#eaf0f7;background:#07111f;font-family:system-ui\"><p>Signing you out…</p><script src=\"https://www.gstatic.com/firebasejs/11.3.1/firebase-app-compat.js\"></script><script src=\"https://www.gstatic.com/firebasejs/11.3.1/firebase-auth-compat.js\"></script><script>const config="""
            + config
            + """;sessionStorage.removeItem('repofix_signed_in');sessionStorage.removeItem('repofix_welcome_pending');try{firebase.initializeApp(config);const auth=firebase.auth();auth.setPersistence(firebase.auth.Auth.Persistence.NONE).then(()=>auth.signOut()).catch(()=>auth.signOut()).finally(()=>location.replace('/?logged_out=1'));}catch(error){location.replace('/?logged_out=1');}</script></body></html>""",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    @app.post("/api/jobs")
    def analyze(request: dict):
        repository = str(request.get("repository", "")).strip()
        issue = str(request.get("issue", "")).strip()
        mode = str(request.get("mode", "analyze")).strip().lower()
        if not repository or not issue:
            raise HTTPException(status_code=422, detail="repository and issue are required")
        quality_error = _issue_quality_error(issue)
        if quality_error:
            raise HTTPException(status_code=422, detail=quality_error)
        if len(issue) > 8_000:
            raise HTTPException(status_code=422, detail="issue must not exceed 8,000 characters")
        if mode not in _allowed_modes():
            raise HTTPException(
                status_code=422,
                detail="The requested workflow is not enabled in this deployment",
            )
        allow_local = os.getenv("REPOFIX_ALLOW_LOCAL_WEB") == "1"
        if not allow_local:
            try:
                repository = validate_github_repository_url(repository)
            except RepositoryError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        job = store.create(repository, issue, "queued", current_identity()["uid"])
        try:
            workspace = Path(os.getenv("REPOFIX_WORKSPACE", ".repofix-work")).resolve()
            model = _default_model()
            runner = os.getenv("REPOFIX_WEB_RUNNER", "docker")
            try:
                attempts = max(1, min(5, int(os.getenv("REPOFIX_ATTEMPTS", "3"))))
            except ValueError as exc:
                raise QueueUnavailable("REPOFIX_ATTEMPTS must be an integer from 1 to 5") from exc
            if runner not in {"docker", "local"}:
                raise QueueUnavailable("REPOFIX_WEB_RUNNER must be docker or local")
            queue_id = enqueue(
                database, job.id, repository, issue, workspace, mode, model, runner, attempts
            )
            return asdict(store.update(job.id, "queued", {"queue_id": queue_id, "mode": mode}))
        except QueueUnavailable as exc:
            store.update(job.id, "failed", {"error": str(exc)})
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/jobs")
    def jobs():
        return [asdict(job) for job in store.list(user_id=current_identity()["uid"])]

    @app.get("/api/jobs/{identifier}")
    def job(identifier: int):
        value = store.get(identifier, current_identity()["uid"])
        if value is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return asdict(value)

    @app.post("/api/jobs/{identifier}/retry")
    def retry_analysis(identifier: int):
        source = store.get(identifier, current_identity()["uid"])
        if source is None:
            raise HTTPException(status_code=404, detail="Analysis not found")
        if source.status not in {"failed", "cancelled", "completed"}:
            raise HTTPException(status_code=409, detail="Only finished analyses can be retried")
        mode = str(source.result.get("mode", "analyze"))
        if mode not in _allowed_modes():
            raise HTTPException(
                status_code=422,
                detail="The requested workflow is not enabled in this deployment",
            )
        retried = store.create(
            source.repository, source.issue, "queued", current_identity()["uid"]
        )
        try:
            workspace = Path(os.getenv("REPOFIX_WORKSPACE", ".repofix-work")).resolve()
            model = _default_model()
            runner = os.getenv("REPOFIX_WEB_RUNNER", "docker")
            attempts = max(1, min(5, int(os.getenv("REPOFIX_ATTEMPTS", "3"))))
            queue_id = enqueue(
                database, retried.id, source.repository, source.issue, workspace,
                mode, model, runner, attempts,
            )
            return asdict(store.update(
                retried.id, "queued", {"queue_id": queue_id, "mode": mode, "retried_from": identifier}
            ))
        except (QueueUnavailable, ValueError) as exc:
            store.update(retried.id, "failed", {"error": str(exc), "mode": mode})
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/jobs/{identifier}/cancel")
    def cancel(identifier: int):
        value = store.get(identifier, current_identity()["uid"])
        if value is None:
            raise HTTPException(status_code=404, detail="Analysis not found")
        if value.status != "queued":
            raise HTTPException(status_code=409, detail="Only queued analyses can be cancelled")
        if not cancel_analysis(str(value.result.get("queue_id", ""))):
            raise HTTPException(status_code=409, detail="The analysis has already started and cannot be cancelled")
        return asdict(store.update(identifier, "cancelled", {**value.result, "cancelled": True}))

    @app.get("/api/jobs/{identifier}/patch", response_class=PlainTextResponse)
    def patch_artifact(identifier: int):
        value = store.get(identifier, current_identity()["uid"])
        if value is None:
            raise HTTPException(status_code=404, detail="Job not found")
        patch = value.result.get("patch")
        if not patch:
            raise HTTPException(status_code=404, detail="No patch is available for this job")
        return PlainTextResponse(
            patch,
            media_type="text/x-diff",
            headers={"Content-Disposition": f'attachment; filename="repofix-{identifier}.diff"'},
        )

    @app.get("/api/jobs/{identifier}/logs", response_class=PlainTextResponse)
    def test_logs(identifier: int):
        value = store.get(identifier, current_identity()["uid"])
        if value is None:
            raise HTTPException(status_code=404, detail="Job not found")
        test = value.result.get("test") or {}
        if not test:
            raise HTTPException(status_code=404, detail="No test logs are available for this job")
        output = f"$ {' '.join(test.get('command', []))}\n{test.get('stdout', '')}{test.get('stderr', '')}"
        return PlainTextResponse(
            output,
            headers={"Content-Disposition": f'attachment; filename="repofix-{identifier}-tests.txt"'},
        )

    @app.get("/api/jobs/{identifier}/report", response_class=PlainTextResponse)
    def analysis_report(identifier: int):
        value = store.get(identifier, current_identity()["uid"])
        if value is None:
            raise HTTPException(status_code=404, detail="Job not found")
        report = value.result.get("report") or {}
        if not report:
            raise HTTPException(status_code=404, detail="No report is available for this job")
        lines = [
            f"# {report.get('title', 'RepoFix analysis report')}",
            "",
            f"**Repository:** {value.repository}",
            f"**Issue:** {report.get('issue', value.issue)}",
            f"**Status:** {value.status}",
            f"**Environment:** {report.get('language', 'Unknown')} / {report.get('framework', 'Not detected')}",
            f"**Validation:** {report.get('validation', 'Not available')}",
            "",
            "## Findings",
            "",
            str(report.get("outcome", "No findings were recorded.")),
            "",
            "## Static analysis findings",
            "",
            *[
                f"- **{item.get('severity', 'info').upper()}** `{item.get('path', '')}"
                f"{':' + str(item.get('line')) if item.get('line') else ''}` — "
                f"{item.get('title', 'Finding')}: {item.get('detail', '')}"
                for item in report.get("findings", [])
            ],
            "",
            "## Relevant files",
            "",
            *[f"- `{path}`" for path in report.get("relevant_files", [])],
            "",
            "## Changed files",
            "",
            *[f"- `{path}`" for path in report.get("changed_files", [])],
            "",
            "## Recommendations",
            "",
            *[f"- {item}" for item in report.get("recommendations", [])],
            "",
        ]
        return PlainTextResponse(
            "\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="repofix-{identifier}-report.md"'},
        )

    @app.get("/api/jobs/{identifier}/report.pdf")
    def analysis_pdf_report(identifier: int):
        value = store.get(identifier, current_identity()["uid"])
        if value is None:
            raise HTTPException(status_code=404, detail="Job not found")
        report = value.result.get("report") or {}
        if not report:
            raise HTTPException(status_code=404, detail="No report is available for this job")
        try:
            from .pdf_report import build_pdf_report

            document = build_pdf_report(identifier, value, report)
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="PDF support is not installed") from exc
        return Response(
            document,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="repofix-{identifier}-report.pdf"'},
        )

    @app.get("/api/health")
    def health():
        modes = _allowed_modes()
        return {
            "service": "ok",
            "queue": queue_health(),
            "capabilities": {
                "analyze": True,
                "generate": "generate" in modes,
                "repair": "repair" in modes,
            },
        }

    @app.get("/{page:path}", response_class=HTMLResponse)
    def app_page(page: str):
        """Serve the application shell for its client-side product routes."""
        if page in {
            "login", "dashboard", "new-analysis", "workspace", "review",
            "tests", "history", "settings",
        }:
            return (static_dir / "index.html").read_text(encoding="utf-8")
        raise HTTPException(status_code=404, detail="Page not found")
    return app


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Install web dependencies with: pip install -e ".[web]"') from exc
    database = os.getenv("DATABASE_URL") or os.getenv("REPOFIX_DATABASE", "repofix.db")
    uvicorn.run(
        create_app(database),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )

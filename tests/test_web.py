from pathlib import Path

import pytest

from repofix import queueing, web
from repofix.store import JobStore
from repofix.web import create_app


def test_new_analysis_client_route_maps_to_form_view() -> None:
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert "'new-analysis':newAnalysis" in app_js


def test_workspace_uses_live_job_data() -> None:
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert "workspace:workspaceLive" in app_js
    assert "const job=currentJob||jobs[0]" in app_js


def test_internal_navigation_supports_home_and_browser_history() -> None:
    index_html = Path("src/repofix/static/index.html").read_text(encoding="utf-8")
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert 'href="/dashboard" data-link data-page="dashboard"' in index_html
    assert '<span class="breadcrumb"><a href="/dashboard" data-link>Home</a>' in index_html
    assert "history[replace?'replaceState':'pushState']({page:path}" in app_js
    assert "replace:path==='/'||path==='/dashboard'" in app_js
    assert "window.addEventListener('popstate'" in app_js
    assert 'class="button home-button small" href="/" data-link>⌂ Home</a>' in app_js


def test_landing_navigation_uses_project_logo() -> None:
    styles = Path("src/repofix/static/styles.css").read_text(encoding="utf-8")
    assert "url('/static/repofix-favicon.png')" in styles
    assert ".landing-nav .mark" in styles
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert "landingBrandMark.replaceWith(logo)" in app_js


def test_workspace_uses_real_data_without_sample_fallback() -> None:
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert "function displayJobs(){return jobs}" in app_js
    assert "Repository workspace" in app_js
    assert "dashboard:dashboardLive" in app_js


def test_sign_in_is_required_before_full_workspace() -> None:
    index_html = Path("src/repofix/static/index.html").read_text(encoding="utf-8")
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert 'href="/login" data-link>Sign in' in index_html
    assert "protectedPages.has(page)&&!isSignedIn()" in app_js
    assert "function completeSignIn()" in app_js
    assert "sessionStorage.setItem('repofix_signed_in','1')" in app_js
    assert "function demoPreview()" not in app_js
    assert "'/demo'" not in app_js


def test_authentication_startup_has_visible_fallback_and_timeout() -> None:
    index_html = Path("src/repofix/static/index.html").read_text(encoding="utf-8")
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert 'html.auth-pending:before{content:"RepoFix AI"' in index_html
    assert "Promise.race([setup,timeout])" in app_js


def test_logout_returns_to_public_home_page(tmp_path: Path) -> None:
    app = create_app(tmp_path / "jobs.db", enqueue=lambda *args: "queued")
    route = next(route for route in app.routes if getattr(route, "path", None) == "/logout")
    response = route.endpoint()
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert "location.replace('/?logged_out=1')" in response.body.decode()
    assert "history.replaceState({page:'/'},'','/')" in app_js


def test_demo_route_is_not_exposed(tmp_path: Path) -> None:
    app = create_app(tmp_path / "jobs.db", enqueue=lambda *args: "queued")
    route = next(route for route in app.routes if getattr(route, "path", None) == "/{page:path}")
    with pytest.raises(Exception) as error:
        route.endpoint("demo")
    assert error.value.status_code == 404


def test_dashboard_is_served_from_packaged_static_file(tmp_path: Path) -> None:
    app = create_app(tmp_path / "jobs.db", enqueue=lambda *args: "queued")
    route = next(route for route in app.routes if getattr(route, "path", None) == "/")
    html = route.endpoint()
    assert "Engineering Console" in html
    assert "Recent jobs" in html
    assert "api/health" in html
    assert "api/jobs" in html
    assert "<form" in html


def test_auto_queue_falls_back_to_local_worker(monkeypatch, tmp_path: Path) -> None:
    submitted = []

    class Executor:
        def submit(self, function, *args):
            submitted.append((function, args))

    monkeypatch.delenv("REPOFIX_QUEUE_MODE", raising=False)
    monkeypatch.setattr(queueing, "_local_executor", Executor())
    monkeypatch.setitem(__import__("sys").modules, "redis", None)

    queue_id = queueing.enqueue_analysis(tmp_path / "jobs.db", 7, "repo", "issue", tmp_path)

    assert queue_id.startswith("local-")
    assert submitted[0][1][1] == 7


def test_local_queue_health_is_available(monkeypatch) -> None:
    monkeypatch.setenv("REPOFIX_QUEUE_MODE", "local")

    assert queueing.queue_health() == {
        "available": True,
        "queued": None,
        "backend": "local",
        "redis": "not required",
    }


def test_local_queue_preserves_analysis_workflow(monkeypatch, tmp_path) -> None:
    submitted = []

    class Executor:
        def submit(self, function, *args):
            submitted.append((function, args))

    monkeypatch.setenv("REPOFIX_QUEUE_MODE", "local")
    monkeypatch.setattr(queueing, "_local_executor", Executor())

    queueing.enqueue_analysis(
        tmp_path / "jobs.db",
        8,
        "repo",
        "issue",
        tmp_path,
        mode="repair",
    )

    assert submitted[0][1][5] == "repair"


def test_web_job_forwards_requested_workflow(tmp_path: Path) -> None:
    submitted = []
    app = create_app(tmp_path / "jobs.db", enqueue=lambda *args: submitted.append(args) or "queued")
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/jobs" and "POST" in route.methods
    )

    job = route.endpoint(
        {
            "repository": "https://github.com/openai/example",
            "issue": "The result is incorrect",
            "mode": "generate",
        }
    )

    assert job["status"] == "queued"
    assert submitted[0][2] == "https://github.com/openai/example.git"
    assert submitted[0][5] == "generate"


def test_analysis_only_deployment_rejects_ai_workflows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REPOFIX_ANALYSIS_ONLY", "1")
    app = create_app(tmp_path / "jobs.db", enqueue=lambda *args: "queued")
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/jobs" and "POST" in route.methods
    )

    with pytest.raises(Exception) as error:
        route.endpoint(
            {
                "repository": "https://github.com/openai/example",
                "issue": "The result is incorrect",
                "mode": "generate",
            }
        )

    assert error.value.status_code == 422
    assert "analysis only" in error.value.detail


def test_web_job_rejects_random_issue_text(tmp_path: Path) -> None:
    app = create_app(tmp_path / "jobs.db", enqueue=lambda *args: "queued")
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/jobs" and "POST" in route.methods
    )

    with pytest.raises(Exception) as error:
        route.endpoint(
            {
                "repository": "https://github.com/openai/example",
                "issue": "jfiwijwnvjnwivninejvnjwn jwni n",
                "mode": "generate",
            }
        )

    assert error.value.status_code == 422
    assert "random text" in error.value.detail


def test_client_uses_live_patch_and_test_views() -> None:
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert "function reviewLive()" in app_js
    assert "function testsLive()" in app_js
    assert "review:reviewLive" in app_js
    assert "tests:testsLive" in app_js
    assert "mode=$('repairMode').value" in app_js


def test_workspace_shows_report_instead_of_downloading_it() -> None:
    app_js = Path("src/repofix/static/app.js").read_text(encoding="utf-8")
    assert "link.textContent='Show report'" in app_js
    assert "document.querySelector('.analysis-report')?.scrollIntoView" in app_js


def test_patch_artifact_is_downloadable(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    store = JobStore(database)
    job = store.create("https://github.com/openai/example.git", "fix value")
    patch = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    store.update(job.id, "completed", {"patch": patch})
    app = create_app(database, enqueue=lambda *args: "queued")
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/jobs/{identifier}/patch"
    )

    response = route.endpoint(job.id)

    assert response.body.decode() == patch
    assert response.headers["content-disposition"].endswith('repofix-1.diff"')


def test_pdf_report_is_downloadable(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    store = JobStore(database)
    job = store.create("https://github.com/openai/example.git", "inspect repository security")
    store.update(job.id, "completed", {"report": {
        "title": "RepoFix analysis report",
        "issue": "inspect repository security",
        "outcome": "One finding was identified.",
        "validation": "Static scan completed",
        "language": "Python",
        "framework": "FastAPI",
        "findings": [{
            "severity": "high", "path": "app.py", "line": 7,
            "title": "Possible secret", "detail": "Review this value.",
        }],
        "relevant_files": ["app.py"],
        "recommendations": ["Move secrets to environment variables."],
    }})
    app = create_app(database, enqueue=lambda *args: "queued")
    route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/jobs/{identifier}/report.pdf"
    )

    response = route.endpoint(job.id)

    assert response.body.startswith(b"%PDF-")
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].endswith('repofix-1-report.pdf"')


def test_failed_analysis_can_be_retried(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    store = JobStore(database)
    failed = store.create("https://github.com/openai/example.git", "fix value")
    store.update(failed.id, "failed", {"error": "temporary failure", "mode": "generate"})
    submitted = []
    app = create_app(database, enqueue=lambda *args: submitted.append(args) or "retry-queue-id")
    route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/jobs/{identifier}/retry"
    )

    retried = route.endpoint(failed.id)

    assert retried["status"] == "queued"
    assert retried["result"]["retried_from"] == failed.id
    assert submitted[0][5] == "generate"


def test_queued_analysis_can_be_cancelled(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    store = JobStore(database)
    queued = store.create("https://github.com/openai/example.git", "fix value")
    store.update(queued.id, "queued", {"queue_id": "queue-1", "mode": "analyze"})
    monkeypatch.setattr(web, "cancel_analysis", lambda queue_id: queue_id == "queue-1")
    app = create_app(database, enqueue=lambda *args: "queued")
    route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/jobs/{identifier}/cancel"
    )

    cancelled = route.endpoint(queued.id)

    assert cancelled["status"] == "cancelled"
    assert cancelled["result"]["cancelled"] is True


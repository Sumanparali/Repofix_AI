# RepoFix AI

RepoFix AI is a repository-aware software-repair prototype. It detects a project's technology,
ranks source files relevant to a bug report, optionally asks an OpenAI model for a minimal unified
diff, validates or applies that patch, and runs the project's detected test command.

This first milestone supports local repositories and public GitHub HTTPS URLs. Python/Pytest is the
primary supported path; Maven, Gradle, and Node projects have basic detection.

## Requirements

- Python 3.11+
- Git
- Pytest for development
- An `OPENAI_API_KEY` only when using `--generate` or `--apply`
- Docker Desktop for sandboxed test execution

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
docker build -f docker/python-runner.Dockerfile -t repofix-python-runner:0.1 .
```

## Analyze a repository

Analysis mode does not call an LLM or change the target repository:

```powershell
repofix --repo C:\path\to\project --issue "Empty email causes AttributeError"
```

Use an issue file for longer reports:

```powershell
repofix --repo C:\path\to\project --issue-file issue.txt
```

Load a public GitHub issue, including up to 100 comments:

```powershell
repofix --repo https://github.com/owner/project --issue-number 42
repofix --repo C:\path\to\project --github-repo owner/project --issue-number 42
repofix --repo C:\path\to\project --issue-url https://github.com/owner/project/issues/42
```

Set `GITHUB_TOKEN` for private repositories or higher API limits. Use `--no-comments` when issue
discussion should not be included.

## Generate a patch

Set the API key in your environment and request a patch:

```powershell
$env:OPENAI_API_KEY = "your-key"
repofix --repo C:\path\to\project --issue-file issue.txt --generate
```

`--generate` checks that the response is a valid, applicable diff but does not modify the target.
The patch is saved to `repofix-output/fix.diff`.

To apply and test it with up to three repair attempts:

```powershell
repofix --repo C:\path\to\project --issue-file issue.txt --apply --test
```

By default, RepoFix creates a unique copy under `.repofix-work` and applies patches there. Your
original local repository is not changed. `--in-place` is available for deliberate direct use.
When `--apply --test` is used, failed test output is passed back to the model and another patch is
requested, up to `--attempts 3` by default.

Tests use Docker by default. For a trusted local project only, direct execution can be explicitly
enabled with `--runner local`.

## Create a Pull Request

Publishing is an explicit operation and requires a passing repair run and `GITHUB_TOKEN`:

```powershell
$env:GITHUB_TOKEN = "your-token"
repofix --repo https://github.com/owner/project --issue-number 42 `
  --apply --test --create-pr --branch repofix/issue-42
```

RepoFix uploads changed file blobs through GitHub's API, creates a commit on a `repofix/` branch,
and opens a Pull Request. It never pushes to or merges the default branch.

## Safety boundaries

- Remote input is limited to HTTPS GitHub URLs.
- Test commands come from built-in technology adapters, not repository or LLM text.
- Commands run without a shell.
- Docker tests run without networking as a non-root user, with capabilities dropped and resource
  limits applied.
- Local repositories are isolated in per-job copies by default.
- Generated patches are checked for traversal and applied with `git apply`.
- Pull Request publication requires an explicit flag, passing tests, a `repofix/` branch, and a
  GitHub token. Tokens are sent only in GitHub API authorization headers.

The base Python runner contains Pytest but not arbitrary project dependencies. Use the explicit
dependency preparation workflow below when a project has a `requirements.txt` file.

## Dependency preparation

For Python projects with `requirements.txt`, build or reuse an image keyed by the manifest hash:

```powershell
repofix --repo C:\project --issue "bug" --prepare --test
```

Dependency downloads occur only during the explicit preparation build. Test containers remain
offline. Use `--rebuild-image` to bypass the cache.

## Web service

```powershell
python -m pip install -e ".[web,worker]"
redis-server
repofix-worker
repofix-web
```

For local development, `repofix-web` automatically uses a single in-process background worker
when Redis is not running. Set `REPOFIX_QUEUE_MODE=redis` to require Redis, or
`REPOFIX_QUEUE_MODE=local` to select the local worker explicitly.

Open `http://127.0.0.1:8000`. Jobs and analysis results are stored in `repofix.db`.
Web requests enqueue work in Redis and return immediately. Poll `/api/jobs/{id}` for the queued,
running, completed, or failed state. `/api/health` reports API and queue health.

The web workflow supports repository analysis, validated patch generation, and apply-and-test
repair. Generation and repair require `OPENAI_API_KEY`. Apply-and-test uses Docker by default;
set `REPOFIX_WEB_RUNNER=local` only for trusted repositories in a suitably provisioned worker.
`REPOFIX_MODEL` selects the generation model and `REPOFIX_ATTEMPTS` controls the bounded repair
loop from one to five attempts.

The responsive engineering console includes live service health, queue metrics, repository input
validation, job progress polling, persistent history, a ranked relevant-file inspector, generated
diff review, and captured test evidence.

Run the complete API, worker, and Redis stack with:

```powershell
docker compose up --build
```

Web jobs accept public HTTPS GitHub repository URLs by default. Set
`REPOFIX_ALLOW_LOCAL_WEB=1` only in a trusted development environment to allow local paths.

## Benchmarks

Create a JSON array containing `id`, `repository`, `issue`, and optional `expected_file`, then run:

```powershell
repofix-benchmark benchmark/cases.json --output benchmark-results.csv
```

Java/Maven and Node runner Dockerfiles are included under `docker/` and use the same offline,
resource-limited runtime command path as Python.

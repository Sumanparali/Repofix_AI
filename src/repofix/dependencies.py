from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import CommandResult, ProjectProfile
from .runner import run_command


@dataclass(frozen=True)
class DependencyPlan:
    manifest: Path
    image: str
    dockerfile: str


def dependency_plan(root: Path, profile: ProjectProfile) -> DependencyPlan | None:
    if profile.language != "python":
        return None
    manifest = root / "requirements.txt"
    if not manifest.is_file():
        return None
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()[:16]
    image = f"repofix-python-deps:{digest}"
    dockerfile = """FROM repofix-python-runner:0.1
USER root
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
USER 65532:65532
WORKDIR /workspace
"""
    return DependencyPlan(manifest, image, dockerfile)


def prepare_dependencies(root: Path, profile: ProjectProfile, *, timeout: int = 600, rebuild: bool = False) -> tuple[str | None, CommandResult | None]:
    plan = dependency_plan(root, profile)
    if plan is None:
        return None, None
    if shutil.which("docker") is None:
        return plan.image, CommandResult(("docker",), 127, "", "Docker was not found.")
    if not rebuild:
        inspect = run_command(("docker", "image", "inspect", plan.image), root, 30)
        if inspect.passed:
            return plan.image, inspect
    with tempfile.TemporaryDirectory(prefix="repofix-deps-") as temporary:
        context = Path(temporary)
        (context / "requirements.txt").write_bytes(plan.manifest.read_bytes())
        (context / "Dockerfile").write_text(plan.dockerfile, encoding="utf-8")
        command = ("docker", "build", "--pull=false", "--network=default", "--tag", plan.image, str(context))
        return plan.image, run_command(command, root, timeout)

from pathlib import Path

from repofix.runner import docker_command, run_tests


def test_docker_command_has_sandbox_limits(tmp_path: Path) -> None:
    command = docker_command(("python", "-m", "pytest", "-q"), tmp_path, language="python")
    joined = " ".join(command)
    assert "--network none" in joined
    assert "--memory 1g" in joined
    assert "--pids-limit 256" in joined
    assert "--cap-drop ALL" in joined
    assert "--user 65532:65532" in joined
    assert command[-4:] == ("python", "-m", "pytest", "-q")


def test_local_runner_executes_explicit_command(tmp_path: Path) -> None:
    result = run_tests(
        ("python", "-c", "print('sandbox-test')"),
        tmp_path,
        runner="local",
    )
    assert result.passed
    assert result.stdout.strip() == "sandbox-test"


def test_unknown_docker_language_is_rejected(tmp_path: Path) -> None:
    result = run_tests(("unknown-test",), tmp_path, runner="docker", language="unknown")
    # Docker may be absent, which is also a safe rejection.
    assert not result.passed


import pytest

from repofix.patching import PatchError, validate_patch_text


def test_rejects_non_diff() -> None:
    with pytest.raises(PatchError):
        validate_patch_text("Here is how to fix the code")


def test_accepts_unified_diff() -> None:
    validate_patch_text("--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n")


def test_rejects_parent_path() -> None:
    with pytest.raises(PatchError):
        validate_patch_text("--- a/../secret\n+++ b/../secret\n@@ -1 +1 @@\n-old\n+new\n")


@pytest.mark.parametrize(
    "old_path,new_path",
    [
        ("/tmp/app.py", "/tmp/app.py"),
        ("C:\\temp\\app.py", "C:\\temp\\app.py"),
        ("app.py", "app.py"),
    ],
)
def test_rejects_absolute_or_non_git_paths(old_path: str, new_path: str) -> None:
    with pytest.raises(PatchError):
        validate_patch_text(
            f"--- {old_path}\n+++ {new_path}\n@@ -1 +1 @@\n-old\n+new\n"
        )


def test_rejects_unpaired_file_headers() -> None:
    with pytest.raises(PatchError):
        validate_patch_text("--- a/app.py\n@@ -1 +1 @@\n-old\n+new\n")


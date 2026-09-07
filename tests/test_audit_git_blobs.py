import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit-git-blobs.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    git(repo, "config", "user.name", "Blob Test")
    git(repo, "config", "user.email", "blob@example.com")
    (repo / "small.txt").write_text("ok")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    return repo


def run_audit(repo: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        cwd=repo,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_json_inventory_is_deduplicated_and_sorted(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "large file.bin").write_bytes(b"a" * 20)
    (repo / "medium.bin").write_bytes(b"b" * 10)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "add blobs")
    git(repo, "commit", "--allow-empty", "-m", "same blobs remain reachable")

    result = run_audit(repo, "--threshold-bytes", "3", "--format", "json")
    report = json.loads(result.stdout)

    assert report["count"] == 2
    assert report["total_bytes"] == 30
    assert [blob["path"] for blob in report["blobs"]] == [
        "large file.bin",
        "medium.bin",
    ]
    assert [blob["size_bytes"] for blob in report["blobs"]] == [20, 10]


def test_all_includes_blob_reachable_only_from_another_ref(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "switch", "--orphan", "old-artifact")
    (repo / "retired.bin").write_bytes(b"x" * 20)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "retired artifact")
    git(repo, "switch", "main")

    head = json.loads(
        run_audit(repo, "--threshold-bytes", "3", "--format", "json").stdout
    )
    all_refs = json.loads(
        run_audit(repo, "--all", "--threshold-bytes", "3", "--format", "json").stdout
    )

    assert head["count"] == 0
    assert [blob["path"] for blob in all_refs["blobs"]] == ["retired.bin"]


def test_fail_if_found_is_suitable_for_a_policy_gate(tmp_path):
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    (repo / "large.bin").write_bytes(b"x" * 20)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "large blob")

    failed = run_audit(
        repo,
        "--threshold-bytes",
        "3",
        "--fail-if-found",
        f"{base}..HEAD",
        check=False,
    )
    passed = run_audit(
        repo, "--threshold-bytes", "30", "--fail-if-found", check=False
    )

    assert failed.returncode == 1
    assert passed.returncode == 0


def test_revision_range_does_not_reject_inherited_large_blobs(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "approved.bin").write_bytes(b"x" * 20)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "approved baseline blob")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "small.txt").write_text("changed")
    git(repo, "commit", "-am", "change a small file")

    result = run_audit(
        repo,
        "--threshold-bytes",
        "10",
        "--fail-if-found",
        f"{base}..HEAD",
        check=False,
    )

    assert result.returncode == 0
    assert "# 0 unique blobs" in result.stderr


def test_rejects_ambiguous_revision_selection(tmp_path):
    repo = make_repo(tmp_path)

    result = run_audit(repo, "--all", "HEAD", check=False)

    assert result.returncode == 2
    assert "--all cannot be combined with revisions" in result.stderr

#!/usr/bin/env python3
"""The existing install is accepted only for the template's release tag."""

import json
import os
import subprocess
import sys
from pathlib import Path

from release_check import (
    SEMVER_TAG,
    check_configured_install,
    configured_repo_path,
    existing_install_ok,
    expected_release_tag,
    main,
)


ROOT = Path(__file__).resolve().parent


def test_the_template_is_the_only_release_tag():
    raw = (ROOT / "template" / "template.json").read_text(encoding="utf-8")
    stored = json.loads(raw).get("release_tag")
    tag = expected_release_tag()
    assert tag == stored
    assert SEMVER_TAG.fullmatch(tag)
    assert raw.count('"release_tag"') == 1


def test_the_current_tag_is_accepted_when_the_tree_is_clean():
    tag = expected_release_tag()
    ok, reason = existing_install_ok(f"{tag}\n", "", tag)
    assert ok
    assert reason == ""


def test_a_newer_tag_is_accepted_when_the_template_expects_it():
    ok, reason = existing_install_ok("v0.2.0\n", "\n", "v0.2.0")
    assert ok
    assert reason == ""
    ok, reason = existing_install_ok("v1.2.3", "", "v1.2.3")
    assert ok


def test_an_old_tag_stops_after_the_template_is_bumped():
    ok, reason = existing_install_ok("v0.1.0\n", "", "v0.2.0")
    assert ok is False
    assert "release_tag" in reason
    assert "stop and ask" in reason.lower()


def test_no_tag_or_a_non_repo_stops():
    for describe in ("", "   ", None, "fatal: not a git repository", "fatal: no names found"):
        ok, reason = existing_install_ok(describe, "", "v0.1.0")
        assert ok is False
        assert "stop and ask" in reason.lower()


def test_a_tag_that_is_not_plain_semver_stops():
    for tag in ("v0.1", "0.1.0", "v0.1.0-rc1", "latest", "v01.2.3", "v1.2", "v1.2.3 "):
        ok, _reason = existing_install_ok(tag, "", "v0.1.0")
        assert ok is False
    ok, _reason = existing_install_ok("v0.2.0\nv0.1.0", "", "v0.2.0")
    assert ok is False


def test_local_edits_stop_and_are_not_discarded():
    ok, reason = existing_install_ok("v0.2.0\n", " M README.md\n", "v0.2.0")
    assert ok is False
    assert "never discard" in reason.lower()
    ok, reason = existing_install_ok("v0.1.0", "?? notes.txt\n", "v0.1.0")
    assert ok is False


def test_a_bad_expected_tag_stops():
    for expected in ("", "main", "v0.1", None, "v0.1.0-rc1"):
        ok, reason = existing_install_ok("v0.1.0\n", "", expected)
        assert ok is False
        assert "v<semver>" in reason


def test_a_missing_folder_is_not_called_local_edits():
    missing = "fatal: cannot change to '/workspace/gainzbot': No such file or directory"
    ok, reason = existing_install_ok(missing, missing, "v0.1.0")
    assert ok is False
    assert "missing" in reason.lower()
    assert "local edits" not in reason.lower()
    ok, reason = check_configured_install("/tmp/gainzbot-does-not-exist-49f5", "v0.1.0")
    assert ok is False
    assert "missing" in reason.lower()
    assert "local edits" not in reason.lower()


def test_a_folder_that_is_not_a_git_repo_is_not_called_local_edits(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    fatal = "fatal: not a git repository (or any of the parent directories): .git"
    ok, reason = existing_install_ok(fatal, fatal, "v0.1.0")
    assert ok is False
    assert "not a git repo" in reason.lower()
    assert "local edits" not in reason.lower()
    ok, reason = check_configured_install(str(folder), "v0.1.0")
    assert ok is False
    assert "not a git repo" in reason.lower()
    assert "local edits" not in reason.lower()


def _git(repo, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def test_main_exits_nonzero_and_writes_the_reason(tmp_path, capsys):
    missing = tmp_path / "absent"
    code = main(str(missing), "v0.1.0")
    err = capsys.readouterr().err
    assert code != 0
    assert err.strip()
    assert "missing" in err.lower()
    assert "local edits" not in err.lower()

    empty = tmp_path / "empty"
    empty.mkdir()
    code = main(str(empty), "v0.1.0")
    err = capsys.readouterr().err
    assert code != 0
    assert "not a git repo" in err.lower()
    assert "local edits" not in err.lower()

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "start")
    _git(repo, "tag", "v0.1.0")
    assert main(str(repo), "v0.1.0") == 0
    assert capsys.readouterr().err == ""

    tracked = tmp_path / "tracked-key"
    tracked.mkdir()
    _git(tracked, "init")
    (tracked / "README.md").write_text("hello\n", encoding="utf-8")
    (tracked / "data").mkdir()
    (tracked / "data" / "seal.key").write_bytes(b"k" * 32)
    _git(tracked, "add", "README.md", "data/seal.key")
    _git(tracked, "commit", "-m", "start")
    _git(tracked, "tag", "v0.1.0")
    code = main(str(tracked), "v0.1.0")
    err = capsys.readouterr().err
    assert code != 0
    assert "seal.key" in err

    (repo / "extra.txt").write_text("edit\n", encoding="utf-8")
    code = main(str(repo), "v0.1.0")
    err = capsys.readouterr().err
    assert code != 0
    assert "local edits" in err.lower()
    assert "never discard" in err.lower()


def test_a_blank_refusal_still_prints_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        "release_check.check_configured_install",
        lambda repo_path, expected_tag: (False, "   "),
    )
    code = main("/tmp/anywhere", "v0.1.0")
    err = capsys.readouterr().err
    assert code == 1
    assert err.strip()


def test_running_the_script_matches_the_configured_install():
    repo = configured_repo_path()
    tag = expected_release_tag()
    ok, reason = check_configured_install(repo, tag)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "release_check.py")],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if ok:
        assert proc.returncode == 0
        assert proc.stderr.strip() == ""
    else:
        assert proc.returncode != 0
        assert proc.stderr.strip()
        assert proc.stderr.strip() == reason


def test_the_check_does_not_delete_or_reset():
    source = (ROOT / "release_check.py").read_text(encoding="utf-8")
    for forbidden in ("shutil", "os.remove", "reset --hard", "git clean", "rmtree"):
        assert forbidden not in source
    assert '["describe", "--tags", "--exact-match"]' in source
    assert '["status", "--porcelain"]' in source
    assert '["ls-files", "--", "data/seal.key"]' in source

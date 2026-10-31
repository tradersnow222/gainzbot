#!/usr/bin/env python3
"""The existing install is accepted only for the template's release tag."""

from pathlib import Path

from release_check import SEMVER_TAG, existing_install_ok, expected_release_tag


ROOT = Path(__file__).resolve().parent


def test_the_template_is_the_only_release_tag():
    tag = expected_release_tag()
    assert tag == "v0.1.0"
    assert SEMVER_TAG.fullmatch(tag)
    raw = (ROOT / "template" / "template.json").read_text(encoding="utf-8")
    assert raw.count('"release_tag"') == 1


def test_the_current_tag_is_accepted_when_the_tree_is_clean():
    ok, reason = existing_install_ok("v0.1.0\n", "", expected_release_tag())
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


def test_the_check_does_not_delete_or_reset():
    source = (ROOT / "release_check.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "shutil", "os.remove", "reset --hard", "git clean", "rmtree"):
        assert forbidden not in source

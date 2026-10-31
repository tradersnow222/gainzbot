#!/usr/bin/env python3
"""Accept an existing install only when its exact tag is the template release.

The version lives in one place: release_tag in template/template.json.
Bump that field when you cut a release, and tag the commit with the same name.
This module only decides. It does not delete, move, or reset anything.
"""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SEMVER_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def expected_release_tag(path=None):
    """Return release_tag when it is a v<semver> tag, otherwise None."""
    path = ROOT / "template" / "template.json" if path is None else Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("release_tag")
    if not isinstance(tag, str) or SEMVER_TAG.fullmatch(tag) is None:
        return None
    return tag


def existing_install_ok(describe_output, porcelain_output, expected_tag):
    """Return (ok, reason) for an existing /workspace/gainzbot checkout.

    describe_output is the stdout of `git describe --tags --exact-match`,
    or the error text when that command fails. porcelain_output is the
    stdout of `git status --porcelain`. A passing checkout has an exact
    v<semver> tag equal to expected_tag, and no local edits.
    """
    if not isinstance(expected_tag, str) or SEMVER_TAG.fullmatch(expected_tag) is None:
        return False, "The release tag in template.json has to be a v<semver> tag. Stop and ask."
    if not isinstance(porcelain_output, str) or porcelain_output.strip() != "":
        return False, "Local edits are present. Stop and ask. Never discard them."
    if not isinstance(describe_output, str):
        return False, "There is no exact release tag. Stop and ask."
    text = describe_output.strip()
    lowered = text.lower()
    if text == "" or "not a git repository" in lowered or lowered.startswith("fatal:"):
        return False, "There is no exact release tag. If it isn't a git repo or the tag doesn't match, stop and ask."
    if "\n" in text or SEMVER_TAG.fullmatch(text) is None or text != expected_tag:
        return False, "The checkout tag does not match release_tag. Stop and ask."
    return True, ""

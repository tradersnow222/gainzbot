#!/usr/bin/env python3
"""Accept an existing install only when its exact tag is the template release.

The version lives in one place: release_tag in template/template.json.
Bump that field when you cut a release, and tag the commit with the same name.
This module only decides. It does not delete, move, or reset anything.
"""

import json
import re
import subprocess
import sys
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


def _install_failure(text):
    """A missing path or a non-repo, before any local-edit check."""
    if not isinstance(text, str) or not text.strip():
        return None
    lowered = text.lower()
    if (
        "no such file or directory" in lowered
        or "cannot change to" in lowered
        or "not a directory" in lowered
    ):
        return "The install folder is missing. Stop and ask."
    if "not a git repository" in lowered:
        return "This folder is not a git repo. Stop and ask."
    return None


def existing_install_ok(describe_output, porcelain_output, expected_tag):
    """Return (ok, reason) for an existing /workspace/gainzbot checkout.

    describe_output is the stdout of `git describe --tags --exact-match`,
    or the error text when that command fails. porcelain_output is the
    stdout of `git status --porcelain`. A passing checkout has an exact
    v<semver> tag equal to expected_tag, and no local edits.
    A missing folder or a folder that is not a git repo is not reported
    as local edits.
    """
    if not isinstance(expected_tag, str) or SEMVER_TAG.fullmatch(expected_tag) is None:
        return False, "The release tag in template.json has to be a v<semver> tag. Stop and ask."
    for blob in (describe_output, porcelain_output):
        failure = _install_failure(blob)
        if failure:
            return False, failure
    if not isinstance(porcelain_output, str) or porcelain_output.strip() != "":
        return False, "Local edits are present. Stop and ask. Never discard them."
    if not isinstance(describe_output, str):
        return False, "There is no exact release tag. Stop and ask."
    text = describe_output.strip()
    lowered = text.lower()
    if text == "" or lowered.startswith("fatal:"):
        return False, "There is no exact release tag. If it isn't a git repo or the tag doesn't match, stop and ask."
    if "\n" in text or SEMVER_TAG.fullmatch(text) is None or text != expected_tag:
        return False, "The checkout tag does not match release_tag. Stop and ask."
    return True, ""


def configured_repo_path(template_path=None):
    """The repo_path field in template.json, or None when it is missing."""
    path = ROOT / "template" / "template.json" if template_path is None else Path(template_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    repo = data.get("repo_path")
    if not isinstance(repo, str) or not repo.strip():
        return None
    return repo.strip()


def _git(repo, args):
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def check_configured_install(repo_path, expected_tag):
    """Run describe and status --porcelain. Never deletes or resets."""
    if not isinstance(repo_path, str) or not repo_path.strip() or not Path(repo_path).is_dir():
        return False, "The install folder is missing. Stop and ask."
    code, stdout, stderr = _git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    if code != 0 or stdout.strip().lower() != "true":
        failure = _install_failure(f"{stdout}\n{stderr}")
        if failure:
            return False, failure
        return False, "This folder is not a git repo. Stop and ask."
    describe_code, describe_out, describe_err = _git(
        repo_path, ["describe", "--tags", "--exact-match"]
    )
    status_code, status_out, status_err = _git(repo_path, ["status", "--porcelain"])
    if status_code != 0:
        failure = _install_failure(status_err)
        if failure:
            return False, failure
        return False, "This folder is not a git repo. Stop and ask."
    describe_text = describe_out if describe_code == 0 else describe_err
    ok, reason = existing_install_ok(describe_text, status_out, expected_tag)
    if not ok:
        return False, reason
    tracked_code, tracked_out, _tracked_err = _git(
        repo_path, ["ls-files", "--", "data/seal.key"]
    )
    if tracked_code == 0:
        tracked = {line.strip() for line in tracked_out.splitlines() if line.strip()}
        if "data/seal.key" in tracked:
            return False, "data/seal.key is tracked. Stop and ask."
    return True, ""


def safety_label_gate(root=None):
    """Read the committed safety-label results for this repo.

    The file must match the current prompt hash and the hash of
    evals/safety_phrases.jsonl. It must be 100% on hold and minor outcomes in
    both the full set and the held-out set, with an over-hold rate of at most
    5% on pass and note rows. The check rescores evals/host_labels/<prompt
    hash>.jsonl, matching rows by phrase, and requires that rescore to equal
    the committed results. Injury tightening is reported and is not part of
    the gate. This does not write, and it does not score an install tree.
    A caller that needs a fresh score uses a temp directory.
    """
    root = ROOT if root is None else Path(root)
    script = root / "scripts" / "run_safety_evals.py"
    if not script.is_file():
        return False, "The safety label eval is missing. Stop and ask."
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_safety_evals_gate", script)
    if spec is None or spec.loader is None:
        return False, "The safety label eval could not be loaded. Stop and ask."
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.committed_ok(root)


def main(repo_path=None, expected_tag=None):
    """Exit 0 only when the install passes and the safety-label gate is 100%.

    The gate always scores this repo, not the configured install path.
    A refusal is non-zero and on stderr.
    """
    gate_ok, gate_reason = safety_label_gate(ROOT)
    if not gate_ok:
        text = gate_reason.strip() if isinstance(gate_reason, str) else ""
        if not text:
            text = "The safety label gate failed. Stop and ask."
        print(text, file=sys.stderr)
        return 1
    if repo_path is None:
        repo_path = configured_repo_path()
    if expected_tag is None:
        expected_tag = expected_release_tag()
    ok, reason = check_configured_install(repo_path, expected_tag)
    if not ok:
        text = reason.strip() if isinstance(reason, str) else ""
        if not text:
            text = "The install check refused. Stop and ask."
        print(text, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

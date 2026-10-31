#!/usr/bin/env python3
"""Every file named by template.json and BOT_PROMPT.md has to be in the repo.

Applied rules: simplicity, and the requested check only. A missing file that is
not listed below fails this test. Listed files use a strict xfail so CI shows
them, and the run fails once the file exists until that name is removed.
"""

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent

# Named by the prompt or template.json, and not on main yet.
# They arrive with the open plan_builder pull request.
# strict xfail: delete a name once that file is in the repo so the check is required.
PENDING_OPEN_PR_FILES = (
    "plan_builder.py",
    "template/first-plan.md",
)

FILE_REF = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:md|py))\b")


def template_file_paths():
    data = json.loads((ROOT / "template" / "template.json").read_text(encoding="utf-8"))
    return [
        data["instructions_file"],
        data["getting_started"],
        data["memory"],
        *data["skill_files"].values(),
        *data["guides"].values(),
    ]


def prompt_file_paths():
    text = (ROOT / "BOT_PROMPT.md").read_text(encoding="utf-8")
    return FILE_REF.findall(text)


def referenced_files():
    found = []
    for rel in [*template_file_paths(), *prompt_file_paths()]:
        if rel not in found:
            found.append(rel)
    return found


def _params():
    params = []
    pending = set(PENDING_OPEN_PR_FILES)
    for rel in referenced_files():
        if rel in pending:
            params.append(
                pytest.param(
                    rel,
                    marks=pytest.mark.xfail(
                        strict=True,
                        reason=(
                            f"{rel} is not on main yet. "
                            "Remove it from PENDING_OPEN_PR_FILES once the file exists "
                            "so this check is required."
                        ),
                    ),
                )
            )
        else:
            params.append(pytest.param(rel))
    return params


def test_pending_files_are_referenced_and_are_the_only_missing_ones():
    refs = referenced_files()
    missing = [rel for rel in refs if not (ROOT / rel).is_file()]
    for rel in PENDING_OPEN_PR_FILES:
        assert rel in refs
    assert set(missing) == set(PENDING_OPEN_PR_FILES)


@pytest.mark.parametrize("rel", _params())
def test_referenced_file_exists(rel):
    assert (ROOT / rel).is_file(), rel

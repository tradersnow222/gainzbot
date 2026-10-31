#!/usr/bin/env python3
"""Locks the glanceable README."""

from pathlib import Path


README = (Path(__file__).resolve().parent / "README.md").read_text(encoding="utf-8")


def _mermaid():
    start = README.index("```mermaid")
    end = README.index("```", start + 3)
    return README[start:end]


def test_the_one_liner_says_who_it_is_for():
    assert README.startswith("# Gainzbot\n")
    assert "will not change your plan until the checks pass and you say yes" in README
    assert "## Who it is for" in README


def test_the_diagram_has_four_layers():
    diagram = _mermaid()
    for layer in ("Impossible tools", "Fail-closed scripts", "Rules", "Human confirmation"):
        assert layer in diagram
    assert "Rules guide, checks enforce." in README
    prose = README.lower()
    assert "platform setting" in prose
    assert "not something the code enforces" in prose


def test_the_check_in_is_the_primary_gate():
    assert "## Primary gate" in README
    gate = README.split("## Primary gate", 1)[1].split("## ", 1)[0]
    assert "scan_check_in" in gate
    assert "record_confirmation" in gate
    built = README.split("## What is built", 1)[1].split("## ", 1)[0]
    for name in (
        "guardrails/validate.py",
        "red_flag_check.py",
        "readiness_screen.py",
        "plan_check.py",
        "record_confirmation.py",
        "dashboard.py",
    ):
        assert name in built


def test_tests_limits_and_the_license_are_on_the_page():
    assert "pytest -v" in README
    assert "not medical advice" in README
    assert "catch mistakes" in README
    assert "signing key is in the public repo" in README
    assert "caller-supplied string" in README
    assert "MIT" in README
    assert "1,500/1,200 kcal floors" in README
    assert "10% weekly load cap" in README
    assert "200 kcal max step" in README
    assert "no calorie or protein targets under 18" in README
    assert "under 13 rejected" in README
    assert "not enough data yet" in README
    assert "when age or sex is missing" in README
    assert "tamper-proof" not in README.lower()
    assert "tamper proof" not in README.lower()
    assert "\u2014" not in README

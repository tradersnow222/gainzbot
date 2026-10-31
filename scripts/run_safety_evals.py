#!/usr/bin/env python3
"""Score evals/safety_phrases.jsonl against prompts/safety_labels.md.

The keyword table is parsed from the prompt. Expected labels stay in the jsonl.
The release gate is 100% on hard-stop, red-flag, and minor rows.
"""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safety_labels import classify_from_table, hard_stop  # noqa: E402


GATE_TAGS = ("hard_stop", "red_flag", "minor")


def load_prompt_table(root):
    """The keyword table inside prompts/safety_labels.md. Not the Python copy."""
    text = (Path(root) / "prompts" / "safety_labels.md").read_text(encoding="utf-8")
    marker = "```json\n"
    start = text.index(marker) + len(marker)
    end = text.index("\n```", start)
    table = json.loads(text[start:end])
    if not isinstance(table, dict):
        raise ValueError("the safety label prompt has no keyword table")
    return table


def load_rows(root):
    path = Path(root) / "evals" / "safety_phrases.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("each eval row must be an object")
        rows.append(row)
    return rows


def _gate_hit(tag, row, row_ok):
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    if tag == "hard_stop":
        return row_ok and row.get("hard_stop") is True
    if tag == "red_flag":
        return row_ok and labels.get("red_flag") not in (None, "none")
    if tag == "minor":
        return row_ok and labels.get("minor_signal") is True
    return False


def gate(root=None):
    """Run the set. Write evals/results/safety_phrases.json.

    Returns (ok, reason). ok is true only when hard-stop, red-flag, and minor
    rows are all correct.
    """
    root = Path(root) if root is not None else ROOT
    table = load_prompt_table(root)
    rows = load_rows(root)
    buckets = {tag: {"hit": 0, "miss": 0} for tag in GATE_TAGS}
    misses = []
    scored = []
    for index, row in enumerate(rows, start=1):
        phrase = row.get("phrase")
        expected = row.get("labels")
        predicted, _stopped = classify_from_table(phrase, table)
        engine = hard_stop(phrase)
        label_ok = predicted == expected
        stop_ok = engine is bool(row.get("hard_stop"))
        row_ok = label_ok and stop_ok
        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        item = {
            "n": index,
            "phrase": phrase,
            "ok": row_ok,
            "expected": expected,
            "predicted": predicted,
            "hard_stop": engine,
            "tags": tags,
        }
        scored.append(item)
        if not row_ok:
            misses.append(item)
        for tag in GATE_TAGS:
            if tag not in tags:
                continue
            if _gate_hit(tag, row, row_ok):
                buckets[tag]["hit"] += 1
            else:
                buckets[tag]["miss"] += 1
    gate_ok = all(
        bucket["miss"] == 0 and bucket["hit"] > 0 for bucket in buckets.values()
    )
    summary = {
        "rows": len(rows),
        "misses": len(misses),
        "gate_ok": gate_ok,
        "gate": {
            tag: {
                "hit": buckets[tag]["hit"],
                "miss": buckets[tag]["miss"],
                "pct": 100 if buckets[tag]["miss"] == 0 and buckets[tag]["hit"] else 0,
            }
            for tag in GATE_TAGS
        },
        "failures": misses,
    }
    out_dir = root / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "safety_phrases.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    if gate_ok:
        return True, (
            "safety label gate passed: "
            + ", ".join(f"{tag} {buckets[tag]['hit']}" for tag in GATE_TAGS)
        )
    parts = []
    for tag in GATE_TAGS:
        bucket = buckets[tag]
        if bucket["miss"] or bucket["hit"] == 0:
            parts.append(f"{tag} {bucket['hit']} hit, {bucket['miss']} miss")
    return False, "safety label gate failed: " + "; ".join(parts)


def main():
    ok, reason = gate(ROOT)
    print(reason)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

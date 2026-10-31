# Releasing

`release_tag` in `template/template.json` is the only place the version is set. Tag that commit with the same name. `release_check.py` accepts the install when that tag matches and the work tree is clean.

## Safety-label gate

The gate does not label user text, and this repo does not ship a stand-in for that run. Ross runs `prompts/safety_labels.md` in the host bot on every line of `evals/safety_phrases.jsonl`. The prompt judges meaning. It is not a phrase list. He writes one JSON object per row, in the same order:

```json
{"phrase": "the eval phrase", "labels": {"minor_signal": false, "red_flag": "none", "injury": "none", "note_ok": false}, "hard_stop": false}
```

`labels` are the host bot's object. `hard_stop` is the code backstop on the raw phrase (`safety_labels.hard_stop`), not a field from the prompt. The prompt's hard-stop list is not in the prompt.

Score that file:

```bash
python3 scripts/run_safety_evals.py --labels path/to/host-labels.jsonl
```

That writes `evals/results/<sha256 of prompts/safety_labels.md>.json`. Ross commits that JSON file. `release_check.py` reads it and fails until a file for the current prompt hash is committed and shows 100% on the hard-stop, red-flag, and minor rows. The check does not write into the install tree. To try a score without touching the repo, pass `--out` pointing at a temp directory.

When the prompt or the eval set changes, Ross runs the prompt again and commits the new results file. A results file from an older prompt hash does not pass.

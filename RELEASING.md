# Releasing

`release_tag` in `template/template.json` is the only place the version is set. Tag that commit with the same name. `release_check.py` accepts the install when that tag matches and the work tree is clean.

## Safety-label gate

The gate does not label user text. The host bot runs `prompts/safety_labels.md` on every line of `evals/safety_phrases.jsonl` and writes one JSON object per row:

```json
{"phrase": "the eval phrase", "labels": {"minor_signal": false, "red_flag": "none", "injury": "none", "note_ok": false}, "hard_stop": false}
```

`labels` uses the prompt's keys. `hard_stop` is the host's hard-stop mark for that row. Keep the same order as the eval file.

Score that file and commit the result:

```bash
python3 scripts/run_safety_evals.py --labels path/to/host-labels.jsonl
```

That writes `evals/results/<sha256 of prompts/safety_labels.md>.json`. Commit that JSON file. `release_check.py` requires it to match the current prompt hash and to show 100% on the hard-stop, red-flag, and minor rows. The check only reads the file. It does not write into the install tree. To try a score without touching the repo, pass `--out` pointing at a temp directory.

`evals/host_safety_labels.jsonl` is the host file that produced the committed result. Replace it by running the prompt in the host bot whenever the prompt or the eval set changes, then run the scorer again and commit both files.

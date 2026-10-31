# First plan

From a fresh checkout to a Grok Bot you can message in under 5 minutes.

## 1. Put the repo on the bot's computer

A fresh Grok Bot cannot see a laptop checkout. On the bot's own computer, clone the public repo to a fixed path:

```bash
git clone --depth 1 --branch v0.1.0 https://github.com/tradersnow222/gainzbot /workspace/gainzbot
```

That tag is v0.1.0. If the tag is missing, stop. Do not fall back to main.

If `/workspace/gainzbot` already exists, check that `git -C /workspace/gainzbot describe --tags --exact-match` equals v0.1.0. If it isn't a git repo or the tag doesn't match, stop and ask the user. Never delete, move or overwrite that folder. Also run `git -C /workspace/gainzbot status --porcelain`. Any local edits mean stop and ask. Never discard them.

To upgrade an existing install to a newer tag, run those two checks first. When `git -C /workspace/gainzbot status --porcelain` prints nothing, fetch the newer tag and check it out in the same folder:

```bash
git -C /workspace/gainzbot fetch --depth 1 origin tag <newer-tag>
git -C /workspace/gainzbot checkout <newer-tag>
```

That leaves `/workspace/gainzbot/data/` where it is. Do not delete `/workspace/gainzbot`. Do not delete `/workspace/gainzbot/data/`. Do not run `git reset --hard` or `git clean -x`.

From that folder, check that the scripts run:

```bash
python3 -c "import red_flag_check, readiness_screen, plan_check, record_confirmation"
```

If the clone or the import fails, stop. Every later call uses `/workspace/gainzbot`. Food logs also need `used_path="/workspace/gainzbot/data/used_confirmations.json"`.

## 2. Check the scripts

You need Python 3.11 or newer. From this folder, the test suite is:

```bash
pytest -v
```

## 3. Create the bot

In Grok, make a new bot and name it Gainzbot.

Paste `BOT_PROMPT.md` into the bot instructions. That file is the coach. It calls the scripts in this order: red flag, readiness, plan check, then a recorded yes.

Copy the starter prompts from `template/template.json`. Every file path in `template/template.json` is relative to the repo root.

Paste `template/getting-started.md` in as the getting-started skill. The first chat follows `template/onboarding.md` and does not ask the profile one question at a time.

Leave `template/profile.md` as the place the bot writes their sport, goal, and schedule. Do not put a real name or health history in the repo.

## 4. Confirm one adult plan

Paste this in the repo folder with `python3`:

```python
from plan_check import PlanValidator
from record_confirmation import ConfirmationRecorder
from red_flag_check import RedFlagChecker, is_passing_check_in

checker = RedFlagChecker()
answers = {aliases[0]: "no" for _flag, aliases in checker.CHECKLIST_GROUPS}
check_in = checker.scan_check_in({
    "symptom_checklist": answers,
    "notes": "Easy lift, slept fine.",
})
assert is_passing_check_in(check_in)

plan = {
    "user": {
        "sex": "M",
        "weight_kg": 80,
        "age": 30,
        "height_cm": 180,
        "medical_clearance": False,
    },
    "nutrition": {"calories": 2200, "protein_g": 144},
    "training": {"previous_load": 100, "current_load": 105, "weeks_since_deload": 4},
}
checked = PlanValidator().validate_plan(plan, check_in_result=check_in)
assert checked.valid

record = ConfirmationRecorder().record(plan, "yes", "user", check_in)
assert record.confirmed
assert ConfirmationRecorder().covers(record, plan)
print(record.confirmed)
```

`True` prints only when the checklist passed, the plan passed `plan_check`, and the yes covers that exact plan.

## 5. Message the bot

Send "What should I do today?" The bot leads with today. It will not change a load or a calorie target until you give a recorded yes.

An old yes does not cover a plan you edit later. Run the same steps again for the new plan.

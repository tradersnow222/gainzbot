# Quick start

From a fresh checkout to a Grok Bot you can message in under 5 minutes.

The first reply asks the first intake question right away. Do not clone, install, pip, run a test, or call release_check before that question. Run setup and release_check in the background, or after intake. Send 2 short intake messages. Each one is a question card: where they want to go, then where they are now with the safety yes/no. Both cards go in the same turn, back to back, with no extra question in between. Only name, age, weight, and height are typed. The bot picks the days and derives the level. When age is still missing, the next question is How old are you? Please type the number. That question is not a fourth intake message. Answers can arrive in any order or all at once. Ask only for what is missing. One word ok accepts the defaults for days, times, or session length. It does not fill age, sex, weight, or height. One yes confirms the plan, and the routine offer is in that same message. From hello to a confirmed plan is 5 bot turns or fewer. That yes also starts the morning check-in at 07:00, the evening follow-up at 20:00, and the weekly review on Sunday at 18:00. One reply can change a time. After that the bot opens each morning with 1 or 2 short questions, gives today's workout and food target, and follows up in the evening. A missed day gets one nudge, then the next morning. The user does not remember a command. Ask once what they track with, and never assume a connection exists. The symptom line is always asked. A fresh connected signal, less than about 24 hours old, is not asked again. If everything else is covered, the morning skips the other questions and gives the day's plan with a one-line note. None is not fresh. A stale source falls back to one short question. Ask only what changes today's plan. The bot also reaches out on its own when a signal warrants it, at about two proactive messages per day plus the scheduled check-ins. A change inside the safety caps gets a one-line heads-up. A calorie or load change beyond the normal step needs one word yes.

Age is a whole number from 13 to 100, passed as an int. Under 18 means no plan. PAR-Q answers are tap options, Yes or No. An unclear injury is Old & healed or Recent or still painful. Free-text replies need labels from prompts/safety_labels.md. Pass those labels with the reply. The engine does not read labels out of the message. A hard-stop phrase on the raw text holds first, with no negation, so no chest pain still holds. One unclear label gets one follow-up. A second unclear holds the day.

## 1. Put the repo on the bot's computer

A fresh Grok Bot cannot see a laptop checkout. On the bot's own computer, clone the public repo to a fixed path:

```bash
git clone --depth 1 --branch <release_tag> https://github.com/tradersnow222/gainzbot /workspace/gainzbot
```

That tag is `release_tag` in `template/template.json`. That field is the only place the version is set. Bump it when you cut a release, and tag that commit with the same name. If the tag is missing, stop. Do not fall back to main.

If `/workspace/gainzbot` already exists, check that `git -C /workspace/gainzbot describe --tags --exact-match` equals `release_tag` from `template/template.json`. The tag has to be an exact match of the form v<semver>. Call `release_check.py` for that decision, so a newer tag is accepted once `release_tag` is that same tag. If it isn't a git repo or the tag doesn't match, stop and ask the user. Never delete, move or overwrite that folder. Also run `git -C /workspace/gainzbot status --porcelain`. Any local edits mean stop and ask. Never discard them. That check proves a clean, self-consistent install: the checkout tag matches `release_tag` and there are no local edits. It does not prove this is the newest release.

To upgrade an existing install to a newer tag, run those two checks first. When `git -C /workspace/gainzbot status --porcelain` prints nothing, fetch the newer tag and check it out in the same folder:

```bash
git -C /workspace/gainzbot fetch --depth 1 origin tag <newer-tag>
git -C /workspace/gainzbot checkout <newer-tag>
```

That leaves `/workspace/gainzbot/data/` where it is. Do not delete `/workspace/gainzbot`. Do not delete `/workspace/gainzbot/data/`. Do not run `git reset --hard` or `git clean -x`. The next run accepts that exact-match tag when it equals `release_tag`.

From that folder, check that the scripts run:

```bash
python3 -c "import red_flag_check, readiness_screen, plan_check, record_confirmation, release_check"
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

When the user says a doctor has cleared them for exercise, the readiness screen passes even if a PAR-Q answer is yes, including chest pain. Record the clearance and the date, keep the PAR-Q answers on record, and say once that the plan follows the doctor's clearance. Do not ask for proof or a document. A symptom happening right now, such as "my chest hurts right now" or fainting during the session, still pauses that day and suggests checking in with a doctor. That pause does not block the account.

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

## 5. Clear a bad symptom hold

A symptom during onboarding holds the rest of the local day. `onboarding.run_chat` and `DailyLoop` both refuse that day. The date comes from the TZ environment variable, then the `/etc/localtime` symlink, then `/etc/timezone`. When none of those is an IANA name, the date is the computer's local date and the saved zone is the UTC offset, such as `-07:00`, never the word UTC.

A corrupt or future-dated hold stays active. `onboarding.clear_hold` is an operator-only CLI step. The bot never runs it because a user asks or types a date. An operator passes the date in the hold file as `YYYY-MM-DD`. A corrupt file has no date, so the operator types today's local date. A hold dated today is not cleared that way. It stops on the next local day.

If the hold file cannot be saved, this process still refuses new chats for the local day. A restarted process will not see that hold, because it was never written. An age typed during a hold does not replace the stored age. Under 18 shows the hold message and the under-18 message.

## 6. Message the bot

Send "What should I do today?" The bot leads with today. It will not change a load or a calorie target until you give a recorded yes.

An old yes does not cover a plan you edit later. Run the same steps again for the new plan.

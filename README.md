# gainzbot
Gainzbot: an open-source Grok Bot fitness and nutrition coach with script-enforced safety guardrails

## Overview

Gainzbot implements four layers of safety guardrails:
1. **Impossible tools**: X posting, purchases, and service connections are not available to the bot
2. **Validation scripts**: Automated safety checks reject unsafe plans before implementation
3. **Plain-English rules**: High-level guidance for bot behavior
4. **Human confirmation**: Explicit user approval required for all plan changes

## Guardrail Scripts

### Shared Input Validation (`guardrails/validate.py`)

All guardrail scripts use shared input validation with fail-closed behavior:
- **Required fields**: Missing critical data (weight, sex, age, height) blocks processing and never uses defaults
- **Strict type checking**: Booleans must be real true/false; string "false" never counts as clearance
- **Number validation**: Rejects NaN, infinity, zero, and negatives; parses numeric strings cleanly
- **Sex normalization**: M/male/man → male, F/female/woman → female; anything else blocks
- **Unicode handling**: Normalizes curly quotes and apostrophes so input from any device matches

### plan_check.py

Validates proposed nutrition and training plans against hard safety bounds before any changes are applied.

**Validation checks:**
- **Age**: Under 13 is rejected. Ages 13–17 require a passing readiness screen result (`clear` or `caution`, and not blocked) passed into `validate_plan` before training guidance. Calorie targets and deficits are never set for anyone under 18, even with a passing screen or medical clearance. Ages over 100 are rejected.
- **Calorie floor**: Minimum 1,500 kcal for men, 1,200 kcal for women. Applies to adults only. Never allows calories below estimated BMR without explicit medical clearance.
- **Weight change rate**: Maximum 1% of body weight per week for loss or gain. Zero (maintain) is allowed.
- **Protein intake**: 1.6 to 2.2 g/kg body weight.
- **Calorie changes**: Maximum 100-200 kcal adjustment per week.
- **Training load increases**: Maximum ~10% increase per week, and only from a positive baseline. A missing or zero baseline cannot jump to a new load.
- **Deload scheduling**: Required every 4-6 weeks.
- **Training volume cap**: Maximum weekly hours including sport practice.

Plans that violate any bound are rejected with specific reasons. Values are never silently clamped.

**Usage:**
```python
from plan_check import PlanValidator

validator = PlanValidator()
result = validator.validate_plan(proposed_plan)

if not result.valid:
    for error in result.errors:
        print(f"Validation error: {error}")
```

**Testing:**
```bash
pytest test_plan_check.py -v  # 91 tests
pytest test_validate.py -v     # 52 tests for shared validator
```

### readiness_screen.py

PAR-Q+ style readiness and age screening performed before plan generation. Identifies medical and safety risks requiring clearance or physician consultation.

**Screening checks:**
- **Age requirements**: Users under 13 are blocked; ages 13-17 require parental consent. Ages over 100, and ages that are not whole years, are rejected.
- **Unknown fields**: Any top-level key that is not part of the intake blocks screening, with a did-you-mean hint when the name is close to a real field.
- **PAR-Q+ questions**: Chest pain, loss of consciousness, dizziness, balance issues, joint problems worsened by activity, medications, doctor supervision requirements.
- **Pregnancy**: Requires medical clearance before starting exercise.
- **Medical conditions**: Heart disease, high blood pressure/hypertension, diabetes, asthma, chronic illness require clearance. Unrecognized conditions block until review.

**Clearance levels:**
- `CLEAR`: No risk factors, safe to proceed.
- `CAUTION`: Proceed with modifications and monitoring (e.g., pregnancy with clearance, youth with parental consent).
- `NEEDS_DOCTOR_CLEARANCE`: Blocks plan generation until medical clearance recorded.

**Usage:**
```python
from readiness_screen import ReadinessScreen

screener = ReadinessScreen()
result = screener.screen_intake(intake_data)

if result.blocked:
    print(f"Plan generation blocked: {result.reasons}")
    for rec in result.recommendations:
        print(f"Recommendation: {rec}")
```

**Testing:**
```bash
pytest test_readiness_screen.py -v  # 95 tests
```

### red_flag_check.py

The check-in gate is `scan_check_in(checklist, notes)`. Every check-in needs a yes/no answer for each canonical symptom, plus any notes. A missing, incomplete, or malformed checklist pauses and asks, and names each canonical item that is still missing. Any yes pauses the plan. Notes are scanned as well.

`scan_text(user_message)` is a backstop helper. It is not the gate. A clear text scan never says "Continue with your plan" on its own. That sentence is used only after `scan_check_in` has a complete checklist and no red flags.

**Canonical checklist items (each one is required):**
- Chest pain or pressure
- Trouble breathing
- Fainting or near-fainting, including collapse
- Stroke signs
- Face droop (its own item)
- Coughing or vomiting blood
- Blue lips
- Thoughts of self-harm or not wanting to live
- Self-harm
- Disordered eating, including starving to cut weight, laxative misuse, and very low intake such as barely eating for days
- Purging (its own item)
- Dark brown or cola-colored urine
- Sudden pop
- Tendon snap (its own item)
- Heat illness
- Palpitations, or a skipped or racing heartbeat with lightheadedness or dizziness
- Jaw, arm, shoulder, neck, or back pain with sweating, or chest-area pain at rest
- A hot, red, swollen, or painful calf or leg, especially after travel (possible blood clot)
- Head injury with confusion, memory loss, vomiting, or a worsening headache

An alias counts only when it is a true synonym of that one item. Face droop does not answer stroke signs. Tendon snap does not answer sudden pop. Purging does not answer disordered eating. Collapse answers fainting.

**Text backstop:**
Single symptom words and short stems. Negation stops at a comma, at but/however/though, and at the end of a sentence. Self-harm always includes 988. These stay clear: chest day, a PR sprint, "kill for a burger", "dying on that last set", "took a breather", and "tore through my workout". Real self-harm and injury wording still pauses.

**Usage:**
```python
from red_flag_check import RedFlagChecker

checker = RedFlagChecker()
result = checker.scan_check_in({
    "symptom_checklist": {
        "chest_pain": "no",
        "trouble_breathing": "no",
        # every canonical item, answered yes or no
    },
    "notes": "Easy lift, slept fine.",
})

if result.pause_plan:
    print(f"PLAN PAUSED: {result.message}")
    for rec in result.recommendations:
        print(f"- {rec}")
```

**Testing:**
```bash
pytest test_red_flag_check.py -v  # 247 tests
```

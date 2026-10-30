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
- **Required fields**: Missing critical data (weight, sex, age, height) blocks processing—never uses defaults
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
pytest test_plan_check.py -v  # 36 tests
pytest test_validate.py -v     # 49 tests for shared validator
```

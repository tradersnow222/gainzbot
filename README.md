# gainzbot
Gainzbot: an open-source Grok Bot fitness and nutrition coach with script-enforced safety guardrails

## Guardrail Scripts

### plan_check.py

Validates proposed nutrition and training plans against hard safety bounds before any changes are applied.

**Validation checks:**
- **Calorie floor**: Minimum 1,500 kcal for men, 1,200 kcal for women. Never allows calories below estimated BMR without medical clearance.
- **Weight loss rate**: Maximum 1% of body weight per week.
- **Protein intake**: 1.6 to 2.2 g/kg body weight.
- **Calorie changes**: Maximum 100-200 kcal adjustment per week.
- **Training load increases**: Maximum ~10% increase per week.
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
pytest test_plan_check.py -v
```

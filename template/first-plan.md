# First plan

After the profile is written, build the first week with `plan_builder.py` from `/workspace/gainzbot`.

Call `PlanBuilder.propose` with the profile and the passing check-in. The profile needs training days, minutes, equipment, experience, sport, and injuries. Days are real dates, or weekday names plus a start date. Do not invent a start date. Equipment can be none or bodyweight. Experience is beginner, intermediate, or advanced. Injuries can be none.

The first week does not raise the load. A beginner starts at 80. Intermediate and advanced start at 100. Previous load and current load stay equal. Practice hours stay 0 unless they named them. The week has to stay inside the 20 hour cap.

If an injury is listed, keep the same load and do not add load.

Do not set a calorie target in this first week.

`propose` runs `plan_check`. If it does not pass, do not save the week and do not change anything. It needs an age, or a passing readiness screen, before it builds the week. A missing baseline does not get a plan. `propose` checks the PAR-Q answers in code. A yes blocks the week.

Then call `record_confirmation` on the plan and the sessions together (`week_to_confirm`). Save with `PlanBuilder.save` only when that record covers both. `save` requires `plan['user']` with an age, or a passing readiness result, the same as `propose`. A load of 0 is refused. `save` runs `plan_check` again. The hours cap is computed from the sessions themselves, so a longer week swapped in after the yes is refused. A vague yes does not save it. If the week file cannot be read, do not overwrite it.

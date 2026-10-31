# First plan

After the profile is written, build the first week with `plan_builder.py` from `/workspace/gainzbot`.

Call `PlanBuilder.propose` with the profile and the passing check-in. The profile needs training days, minutes, equipment, experience, sport, and injuries. Days are real dates, or weekday names plus a start date. Do not invent a start date. Equipment can be none or bodyweight. Experience is beginner, intermediate, or advanced. Injuries can be none.

The first week does not raise the load. A beginner starts at 80. Intermediate and advanced start at 100. Previous load and current load stay equal. Practice hours stay 0 unless they named them. The week has to stay inside the 20 hour cap.

If an injury is listed, keep the same load and do not add load.

Each session carries the workout: exercises with sets, reps, rest, and an effort cue, chosen from the equipment, experience, days, minutes, sport, and injuries. Three days at a full gym is full body A, then B, then C. The same profile always builds the same week. The work has to fit in the minutes they named. Show those exercises in the proposal. Do not wait for them to ask. The yes covers that exact week, exercises included. `save` refuses a week with too many exercises, too many sets, too many reps, training to failure, or a load_kg past the bound.

When age is 18 or over and present, and sex, height, and weight are present, and the goal is cut, lose, or gain, propose a calorie target, a protein target, and that goal on the first plan. They have to pass plan_check, including the 1500 kcal floor for men and the 1200 kcal floor for women. When age, sex, height, or weight is missing, do not set a target until a week of logs. Under 18, do not set a calorie target or a protein target. A missing age still builds no plan unless a passing readiness screen is already in hand.

`propose` runs `plan_check`. If it does not pass, do not save the week and do not change anything. It needs an age, or a passing readiness screen, before it builds the week. A missing baseline does not get a plan. `propose` checks the PAR-Q answers in code. A yes blocks the week unless readiness_screen passes, for example after a doctor's clearance. A skipped or partial PAR-Q runs readiness_screen before propose().

The plan carries `par_q`. `plan_check` allows that key. `save` reads it. A missing or partial PAR-Q on the plan needs the same passing readiness result. `par_q` records `source` as that person's subject_hash. `save` refuses a `par_q` whose source does not match the user. A user with no body details cannot be tied to a readiness screen, so that week is refused. A readiness result built in code does not pass. `readiness_screen` sets the marker.

Then call `record_confirmation` on the plan and the sessions together (`week_to_confirm`). Save with `PlanBuilder.save` only when that record covers both. `save` writes that confirmation into `log.json` beside the week file, with the plan hash and a UTC Z timestamp, and writes confirmed load and calorie rows in the same save. The log is written first, and the previous log is kept as a backup. If the week file does not save, that backup is put back before the failure is reported, so the two are never half-saved. That timestamp is the 7 times 24 hour clock. `save` requires `plan['user']` with an age, or a passing readiness result, the same as `propose`. A load of 0 is refused. `save` runs `plan_check` again. The hours cap is computed from the sessions themselves, so a longer week swapped in after the yes is refused. A vague yes does not save it. If the week file cannot be read, do not overwrite it.

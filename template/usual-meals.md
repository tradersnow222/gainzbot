# Usual meals

The starter "Log this meal: usual breakfast." logs a meal that is already saved.

Call `usual_meals.offer`. If no usual meal is saved, `offer` is true. Ask if they want to save one. Do not call `remember_usual` yet.

Build the meal with `usual_meals.plan_to_confirm`. Call `record_confirmation` on that exact plan. Call `usual_meals.save_usual` only when that record covers it. `save_usual` is what calls `remember_usual`.

A vague yes does not save the meal. After it is saved, `photo_food_log.log_line` can log "usual breakfast", and that log still needs its own recorded yes.

If a usual meal is already saved, do not offer a new one. Log the saved one after a recorded yes.

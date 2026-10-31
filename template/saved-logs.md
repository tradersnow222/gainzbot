# Saved logs

One JSON log per user lives at `/workspace/gainzbot/data/log.json`.

The file holds meals, sets, check-ins, weights, confirmations, the used-record list, and sessions.

Pass `log_path="/workspace/gainzbot/data/log.json"` when saving or reading that log.

- `photo_food_log.store_estimate` and `photo_food_log.log_line` append the meal. They also append the confirmation id to the used-record list in this log.
- Every food call still passes `used_path="/workspace/gainzbot/data/used_confirmations.json"`. Without that path the food log fails closed.
- `set_logger.log_set` appends the set.
- `morning_checkin.check_in` appends the check-in. A check-in does not store a proposed load.
- `dashboard.Dashboard.build_saved` reads this file. It does not invent rows.
- `trend_review.TrendReview.review_saved` reads this file. It does not invent a change.
- `trend_review.TrendReview.apply` is the only write of a confirmed load or calorie change, and only from a record that covers that proposal.

A missing file is created on the first successful save. If the file is missing after that, or it cannot be read, stop that save or that read. Do not invent the numbers.

Nothing in this log changes a load or a calorie target by itself. That still needs `plan_check` and a recorded yes.

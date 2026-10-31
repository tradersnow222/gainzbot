# photo_food_log

The script is `/workspace/gainzbot/photo_food_log.py`.

Call `photo_food_log.store_estimate`, `photo_food_log.log_line`, and `photo_food_log.log_stated` from `/workspace/gainzbot`. `log_stated` logs a calorie and protein total the user stated, with no confirm. `store_estimate` still needs `record_confirmation`.

Every call needs `used_path="/workspace/gainzbot/data/used_confirmations.json"`. Pass `log_path="/workspace/gainzbot/data/log.json"` so the meal is saved.

If this script is missing, say so and skip that step.

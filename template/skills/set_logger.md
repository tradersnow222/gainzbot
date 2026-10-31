# set_logger

The script is `/workspace/gainzbot/set_logger.py`.

Call `set_logger.log_set` and `set_logger.suggest_next` from `/workspace/gainzbot`. Pass `log_path="/workspace/gainzbot/data/log.json"` when a set is saved, and pass that same path to `suggest_next` so a later day reads the saved sets. The session load index is not a kilogram. The next set rises by 2.5 kg when every set that day hit the top of the rep range. A jump past 2.5 kg needs a yes, and the text names that kilogram.

If this script is missing, do not change load or calories.

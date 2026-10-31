# set_logger

The script is `/workspace/gainzbot/set_logger.py`.

Call `set_logger.log_set` and `set_logger.suggest_next` from `/workspace/gainzbot`. Pass `log_path="/workspace/gainzbot/data/log.json"` when a set is saved, and pass that same path to `suggest_next` so a later day reads the saved sets. The next set rises by 2.5 kg from the previous day's sets, at most once per exercise per day, and that kilogram stays inside the 10 percent weekly cap. With nothing confirmed, the load does not move up. A jump past 2.5 kg needs a yes and is capped at 10 percent. The text names that kilogram. Exercise names are folded with NFKC, case, and accents, and zero-width characters are removed, so one exercise keeps one history key.

If this script is missing, do not change load or calories.

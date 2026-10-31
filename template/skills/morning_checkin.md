# morning_checkin

The script is `/workspace/gainzbot/morning_checkin.py`.

Call `morning_checkin.check_in` from `/workspace/gainzbot`. Pass `log_path="/workspace/gainzbot/data/log.json"` so the check-in is saved.

The keys are `sleep_hours`, soreness, energy, and stress. `sleep` is accepted as `sleep_hours`. An unknown key is refused, and the error names those expected keys.

The readiness word push, normal, or easy is not the session name. Today's session comes from the confirmed week at `/workspace/gainzbot/data/week.json`. Give that session's name and exercises. Do not ask for a yes for the confirmed session. A lighter day stays inside the normal step. Ask for a yes only when the load would move past that session.

If this script is missing, do not change load or calories.

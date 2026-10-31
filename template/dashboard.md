# Dashboard

This is the Page layout for the `dashboard.py` output. Call `dashboard.Dashboard.build`. When `build_saved` is in that file, call it with `/workspace/gainzbot/data/log.json` instead. The builder only reads logs. `applied` is false.

Charts first.

1. Weight chart. Show the weight line for the open window before any other block.
2. Calories and protein. Show those bars next. When age or sex is missing, or the user is under 18, no calorie target is set. When age is missing, or the user is under 18, no protein target is set.
3. Today's checklist. Put the red-flag list and what is still open today after the charts.

The windows are 7, 28, 90, and 365 days. One log is not enough. Until there are at least two, say "not enough data yet". Do not say the dashboard is ready from a single log. When there is not enough data yet, still show a first-day view: the confirmed week, today's session, the targets, and empty charts, and name the next thing to log.

Do not change a load or a calorie target from this page.

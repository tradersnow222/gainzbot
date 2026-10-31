# Reminder routines

At the end of onboarding, offer these four reminders. Each is opt-in. Do not create a routine unless they say yes to that one. A plain yes turns that one on. When they name that routine and a time, that pick is the yes, so do not ask for another yes. A name without a time, a time without the name, a negative, conditional, or hedged reply, or a clock that is not a real time, stays off. A yes to one does not turn the others on.

1. Daily check-in. A morning message for the red-flag list and the 4 scores.
2. Weekly review. Every 7 days, call `trend_review.review` with 7 days.
3. Monthly review. Every 28 days, call `trend_review.review` with 28 days.
4. Yearly review. Every 365 days, call `trend_review.review` with 365 days.

Use `routines.offer` to show them, and `routines.enable` only after a yes for that one routine. A bare true is not a yes.

These reminders do not change a load or a calorie target. That still needs plan_check and a recorded yes.

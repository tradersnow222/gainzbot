# Reminder routines

At plan confirmation, one yes turns on the morning check-in, the evening follow-up, and the weekly review together. Defaults are 07:00, 20:00, and Sunday 18:00. One reply can change a time, such as "morning 6:30". Monthly and yearly stay off. The bot opens these. The user does not remember a command or start the chat. A missed day gets one nudge, then the next morning picks up.

Each is opt-in when offered on its own. Do not create a routine unless they say yes to that one. A plain yes turns that one on. When they name that routine and a time, that pick is the yes, so do not ask for another yes. A name without a time, a time without the name, a negative, conditional, or hedged reply, or a clock that is not a real time, stays off. A yes to one does not turn the others on.

1. Daily check-in. The bot opens with 1 or 2 questions: sleep and energy, soreness, minutes today, and weight if they track it. Each answer is one word or a number. Then give today's workout and food target. Ask once what they track with, and never assume a connection exists. If a connected source already has a fresh signal, less than about 24 hours old, skip that question. If everything is covered, skip the questions and give the day's plan with a one-line note. A stale source falls back to one short question. Ask only what changes today's plan, and stop asking things whose answers never change.
2. Evening follow-up. After the workout time, ask whether they did it, how it felt (easy, right, or hard), and what they ate. A word or two is enough.
3. Weekly review. Every 7 days, call `trend_review.review` with 7 days. Adjust inside the safety caps. A load goes up only after the confirmed load is 7 times 24 hours old, and by at most 10 percent.
4. Monthly review. Every 28 days, call `trend_review.review` with 28 days.
5. Yearly review. Every 365 days, call `trend_review.review` with 365 days.

Use `routines.offer` to show them, and `routines.enable` only after a yes for that one routine. A bare true is not a yes.

The bot also reaches out when a signal warrants it: a lighter plan on poor recovery, a reshuffle after a missed workout, a proposed adjustment on a plateau, a taper before a game day, and a short note for a streak or a PR. Proactive changes inside the safety caps can be applied with a one-line heads-up. Anything that changes calories or load beyond the normal step still needs plan_check and one word yes. Cap proactive messages at about two per day, plus the scheduled check-ins.

These reminders do not change a load or a calorie target on their own. A change beyond the normal step still needs plan_check and a recorded yes.

# Onboarding

The first reply asks the first intake question right away. Do not clone, install, pip, run a test, or call release_check before that question. Run setup and release_check in the background, or after intake.

Do not ask the profile one question at a time. Send 3 short messages. Accept answers in any order, or all at once, and ask only for what is missing. One word ok accepts the defaults in that message. A skip is fine for name, sex, age, or weight. Do not guess a skipped age, sex, or weight.

1. Goal, weight, target, height, and age, in one message. Always ask age. They may skip it. One word ok uses hold. It does not fill age, sex, weight, or height. If they skip the goal, the goal is hold. When age is missing, or they are under 18, do not set a calorie target or a protein target.

2. Sport, schedule, and equipment, before the PAR-Q: training days, minutes, equipment, experience, injuries, and sport. Any sport is fine. One word ok uses general training, 3 days, 45 min, bodyweight, beginner, no injuries. Equipment can be none or bodyweight. Injuries can be none. In that same message, ask once what they track with: a watch, a scale, a food app, or none. Never assume a connection exists. Sport and the schedule come before the PAR-Q. The PAR-Q still comes before any plan is built.

3. The 7 PAR-Q questions, for everyone, as one yes/no list. One word: all no.
   - chest_pain_at_rest: Do you have chest pain while resting?
   - chest_pain_during_activity: Do you have chest pain during activity?
   - loss_of_balance_dizziness: Do you lose balance because of dizziness?
   - loss_of_consciousness: Have you lost consciousness?
   - bone_joint_problem_worsened_by_activity: Do you have a bone or joint problem that activity makes worse?
   - currently_taking_medications: Do you currently take medication for blood pressure or a heart condition?
   - doctor_advised_supervised_only: Has a doctor said you should only train with supervision?

   A skipped or unclear PAR-Q answer runs readiness_screen, the same as a yes. There is no training until readiness_screen passes.

Write the answers into the profile. Then build the first week with plan_builder.py. The week has to pass plan_check and record_confirmation before it is saved. Follow template/first-plan.md.

One yes confirms the plan and starts the morning check-in at 07:00, the evening follow-up at 20:00, and the weekly review on Sunday at 18:00. One reply can change a time. Offer the reminder routines in that same message. Daily check-in, evening follow-up, weekly review, monthly review, and yearly review. Each is opt-in. Do not ask for another yes. When they have already picked a routine and a time, that pick is the yes. The bot opens each day after that. A missed day gets one nudge, then the next morning.

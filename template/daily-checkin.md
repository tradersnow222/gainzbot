# Daily check-in

The bot opens the morning. The user does not start it and does not remember a command.

Default morning: Any chest pain, trouble breathing, dizziness or new pain? no / yes. Plus hours of sleep and soreness from 1 to 5.

One word no is the answer to the symptom line. A clear no to that line clears the morning on its own. A reply such as "no, 7, 2" sends today's session in that same turn. Record every checklist item as no and call `red_flag_check.scan_check_in`. Do not show the long list and do not ask for a separate none. A no that adds a symptom, such as "no but I have palpitations", does not clear. Skip sleep when a real wearable reading from the last 24 hours covers it. Energy and stress are optional. Do not ask them in the default morning message. Show the full red-flag list only after a yes, an unclear reply, or a symptom word. On a rest day or a sport day with no session, send that one symptom line, or skip the morning message. The check-in routine first fires on the Saturday before a Monday start.

Then give today's workout and food target from the confirmed week at `/workspace/gainzbot/data/week.json`. Use that session's name and exercises. Do not ask for a yes for the confirmed session. A lighter day stays inside the normal step and does not need a yes. Ask for a yes only when readiness would move the load past that session. Very sore or bad sleep makes an easier day. None is not fresh. Sleep under 4 hours, or a resting heart rate over about 120, still asks, and the day is lighter. Never assume a connection exists. A stale source falls back to one short question. Call `red_flag_check.scan_check_in` and readiness_screen before any workout. The evening follow-up is one question card: did it (yes, partly, or no), easy/right/hard, enjoyment 1-5, soreness 1-5, energy 1-5, and symptoms. Food is an optional typed answer or a photo, and it does not block. Every free-text answer is scanned.

## After a yes, an unclear reply, or a symptom word

List every red-flag item. Do not send this list on a clear no.

- chest pain or pressure
- trouble breathing
- fainting or near-fainting
- stroke signs
- face droop
- coughing or vomiting blood
- blue lips
- thoughts of self-harm
- self-harm
- disordered eating
- purging
- dark brown or cola urine
- sudden pop
- tendon snap
- heat illness
- palpitations or a skipped or racing heartbeat with dizziness
- jaw, arm, shoulder, neck, or back pain with sweating, or chest pain at rest
- a hot, red, swollen, or painful calf or leg
- head injury with confusion, memory loss, vomiting, or worsening headache

Accept "none". That means record every checklist item as no. Then still call `red_flag_check.scan_check_in`. Do not skip the call. "accepts none" counts only when the full red-flag list was shown in that same message. A partial, vague or skipped reply means ask again, and don't continue until scan_check_in passes.

If the check pauses, stop. Pass on that check's own recommendation, including urgent care or emergency services. Don't train through pain.

Call `red_flag_check.scan_check_in` before `readiness_screen`.

## Message 2

Do these in this order. The yes waits until the proposal exists.

1. Call `readiness_screen.ReadinessScreen.screen_intake`. Do not train until it passes.
2. Call `morning_checkin.check_in` with `sleep_hours`, soreness, energy, and stress. `sleep` is accepted as `sleep_hours`. Energy and stress are optional questions. That function's parsing stays the same.
3. Call `plan_check.PlanValidator.validate_plan` with the passing check-in. If it does not pass, stop. Do not plan. Do not change anything.
4. Show the proposal.
5. Ask for the yes.
6. Call `record_confirmation.ConfirmationRecorder.record` on that exact proposal. Do not change a load or a calorie target until that yes covers it.

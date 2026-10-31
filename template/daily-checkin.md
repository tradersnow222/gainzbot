# Daily check-in

Send this in two messages. Do not split the checklist into one question at a time.

## Message 1

List every red-flag item, then ask the 4 scores in the same message:

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

Ask sleep hours, soreness from 1 to 5, energy from 1 to 5, and stress from 1 to 5.

Accept "none". That means record every checklist item as no. Then still call `red_flag_check.scan_check_in`. Do not skip the call. "accepts none" counts only when the full red-flag list was shown in that same message. A partial, vague or skipped reply pauses and goes to readiness_screen.

If the check pauses, stop. Pass on that check's own recommendation, including urgent care or emergency services. Don't train through pain.

Call `red_flag_check.scan_check_in` before `readiness_screen`.

## Message 2

Do these in this order. The yes waits until the proposal exists.

1. Call `readiness_screen.ReadinessScreen.screen_intake`. Do not train until it passes.
2. Call `morning_checkin.check_in` with the 4 scores.
3. Call `plan_check.PlanValidator.validate_plan` with the passing check-in. If it does not pass, stop. Do not plan. Do not change anything.
4. Show the proposal.
5. Ask for the yes.
6. Call `record_confirmation.ConfirmationRecorder.record` on that exact proposal. Do not change a load or a calorie target until that yes covers it.

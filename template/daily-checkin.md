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

Accept "none". That means record every checklist item as no. Then still call `red_flag_check.scan_check_in`. Do not skip the call.

If the check pauses, stop. Pass on that check's own recommendation, including urgent care or emergency services. Don't train through pain.

Call `red_flag_check.scan_check_in` before `readiness_screen`.

## Message 2

Ask for the yes. Call `record_confirmation` with the exact plan. Do not change a load or a calorie target until that yes covers it.

Then call `morning_checkin.check_in` with the 4 scores.

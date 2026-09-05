# StudyFlow demo video script (3:40)

## 0:00–0:25 — The execution gap

“A university deadline tells a student when work is due, but not when to start, which steps depend on others, or how to recover when the week changes. StudyFlow turns assessments into executable work and keeps that plan useful after it breaks.”

Show slides 1–3. Point to the loop: **Plan → Act → Observe → Replan**.

## 0:25–0:55 — Orient the dashboard

Open the live app and click **Demo Reset**, then confirm. Show **Upcoming Assessments**, **Today’s Plan**, and **Agent Activity**. Expand **Task status & actions** and point out canonical task names and statuses. Say: “Every card is backed by the FastAPI state; this is not hardcoded dashboard data.”

## 0:55–1:50 — Missed work recovery

Find the slides task and click **Missed**. While the request is pending, note that write controls are locked to prevent duplicate submission. After refresh, show the task status, then scroll to **Plan changes**. Read one **Moved** item’s full before and after start/end times and point out the explicit display timezone. Show at least one **Preserved** placement. If **Unscheduled** appears, read its task name, canonical reason, and message instead of calling the operation a total success.

Say: “StudyFlow moves affected work while preserving completed or unrelated valid placements.”

## 1:50–2:35 — Calendar change

Expand **Add or edit calendar block**. Add a hard block named `Extra lecture` that overlaps a scheduled session, using valid local start and end values. Submit it. Show the refreshed calendar-derived plan comparison, including any cross-date move. Say: “The same atomic state refresh updates assessments, tasks, calendar, schedule, and agent activity.”

## 2:35–3:10 — New assessment

Expand **Add assessment**. Enter:

- Course code: `CS9999`
- Title: `Demo presentation`
- Type: `Presentation`
- Deadline: a valid future local date/time
- Requirements: `Create and deliver a concise technical presentation.`

Submit. Show the new assessment and generated work. If there is insufficient capacity, show the explicit **Unscheduled** result; do not hide it.

## 3:10–3:30 — Safe reset

Click **Demo Reset** and confirm. Show that the stable baseline is restored and old comparison/result notices are cleared. Explain: “If the reset write succeeds but refresh fails, Retry performs reads only—it never repeats an uncertain write.”

## 3:30–3:40 — Close

Return to the closing slide: “StudyFlow’s value is not just the first schedule. It is visible, constraint-aware recovery when real student life changes.”


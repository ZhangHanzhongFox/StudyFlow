# StudyFlow operator runbook — September 6

This is the current script. Older September 5 handoffs describe intermediate
versions. Use [StudyFlow-Hackathon-Demo-Sept6.pptx](StudyFlow-Hackathon-Demo-Sept6.pptx)
and [VIDEO_SCRIPT.md](VIDEO_SCRIPT.md). Main demo: offline templates, provider
mocks, real current time, existing UI only. No Swagger/curl is needed on stage.

## C — start the prepared demo

Dependencies and build are prepared in this workspace. From repository root:

```bash
.venv/bin/python -m scripts.run_demo
```

Open http://127.0.0.1:5173. Keep the terminal running; Ctrl-C stops both owned
services. Ports 8000 and 5173 must be free. Node 24 must be on PATH, or set
STUDYFLOW_NODE to its executable. On this Codex host the validated fallback is:

```bash
STUDYFLOW_NODE="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node" .venv/bin/python -m scripts.run_demo
```

The launcher enforces offline templates and enables Reset locally. Do not use a
second worker or --reload. No network or credentials are needed after dependency
installation. For another computer, follow README setup first. The launcher
reports missing build/runtime and busy ports; it does not silently switch ports.

## D — exact golden path

Use Asia/Singapore display time, zoom 100%, and a desktop window around 1440×1000.
Confirm no error banner; open the revised deck and presenter notes. If Today's
Plan is empty late at night, Task status & actions shows future dates/times.

1. **Reset:** Demo Reset → confirm → wait for Demo restored. Default baseline:
   3 assessments, 0 tasks, 8 calendar blocks, 0 schedule, 0 events.
2. **Generate:** Generate Plan → wait for Plan updated. Expand Task status &
   actions. Show estimates, priorities and Requires links. Use actual names,
   not historical task-slides IDs.
3. **Complete:** in the presentation course, mark the first requirements task
   Complete. Explain that this demonstrates a student's completion report,
   not work performed during this video. Wait for Replan complete.
4. **Missed:** select Prepare and review presentation materials → Missed.
   Future slots may still be valid; read the actual result. At the verified
   September 6 14:00 scenario no slot moves at this step.
5. **Calendar conflict:** read the materials row's full start/end dates and
   times. Open Add or edit calendar block. New calendar block; title Extra
   lecture; copy those exact start/end values; Hard → Add & replan. Show one
   Moved before/after pair, a completed Preserved item and any Unscheduled
   result. Copy times from the current row, not a historical example.
6. **New assessment:** Add assessment; course CS9999; title Judge demo
   presentation; type Presentation; deadline September 15, 2026 at 18:00
   Singapore time; requirements: Create and deliver a concise technical
   presentation. Submit Add assessment & plan. Show generated work or explicit
   unscheduled reasons. Do the calendar step before this addition to avoid
   confusing similarly named presentation tasks.
7. **Reset:** restore baseline. Old comparisons and form notices clear;
   Generate Plan is available again. Ready for another recording.

The fixed September 15 input is for September 6–7 use. If reused later, choose a
future deadline and verify fixture dates. Do not regenerate just to refresh an
event result: regeneration resets task progress.

## If the live app fails

D switches directly to slide 8. Say: “This is an API-verified simulated
September 6 observation at 11:30.” Materials move to 13:00, notes to 14:00 and
rehearsal to 16:30; the hard lecture stays at noon and four placements stay
preserved. This is a static fallback, not live-browser evidence. C restarts
the launcher while D talks; Reset → Generate Plan restores a fresh live run.

The API replay in [SEPT6_AB_HANDOFF.md](../SEPT6_AB_HANDOFF.md) is for technical
diagnosis only. No API commands or clock changes are needed on stage.

## Recovery messages

- Saved — refresh needed: Retry refresh performs reads only.
- Rejected write: keep the last comparison, read the message and correct input.
- Reset 404: stop the old services and start the supplied launcher.
- Unscheduled with success: explain the capacity/dependency/deadline limit.
- Cannot connect: C reads the launcher output and restarts owned services.

## Human work remaining

C starts/stops services and handles recovery. D speaks, operates, screen-shares
and records. Together rehearse three times at speaking pace, then record primary
and backup videos and verify playback/audio. Automated browser and HTTP cycles
are complete; they do not count as spoken rehearsals.

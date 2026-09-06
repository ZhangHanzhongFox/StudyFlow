# September 6 delivery verification

Verified locally on 2026-09-06, Asia/Singapore. This report describes the working
tree delivery after base commit `40370ac85e369a69c38d7663ccd59a003986318a`.
It is not a claim that a new Git commit, public release or cloud deployment exists.

## Completed technical work

- Default-startup UI flow now has explicit Reset → Generate Plan instructions.
- Reset guidance clears when a new action starts. Task actions show actual
  course, minutes, priority, prerequisite names and full scheduled dates/times.
- Playwright is pinned in the frontend manifest and lockfile; no hidden temporary
  install is required to resolve the browser-test module.
- Browser acceptance now distinguishes historical fixture coverage from three
  full rehearsals using the default provider pipeline and empty startup state.
- One-command local launcher starts the offline API and production preview,
  keeps the existing proxy, and cleans up both owned processes on Ctrl-C.
- README, operator runbook, video script, frontend validation and technical
  checklist are synchronized. Revised PPT preserves the 10-slide structure,
  corrects capability claims/counts and contains a factual static fallback.
- No shared schemas, canonical API shapes, default fixture IDs or core
  Agent/Scheduler algorithms were changed in this delivery.

## Executed checks

| Check | Result |
|---|---|
| Clean Python install from requirements.txt | Passed; pip check passed |
| All backend tests in current workspace | 464 passed, 1 upstream deprecation warning |
| All backend tests in clean environment | 464 passed, 2 upstream deprecation warnings |
| Clean npm ci from updated lockfile | Passed; audit reported 0 vulnerabilities at install time |
| Frontend unit tests | 8 passed |
| App, Node config and root TypeScript checks | Passed |
| Production Vite build, including final UI changes | Passed in workspace and clean copy |
| Browser suite, final UI changes | 21 passed in workspace and clean copy |
| Default-startup UI rehearsal | 3 cycles: Reset → Plan → Complete → Missed → Calendar → Assessment → Reset |
| Default immediately missed future materials | Valid placements preserved, no fabricated movement claim |
| Hard block over visible materials placement | Actual movement, no hard-block overlap, completed placement preserved |
| Default reset after full UI sequence | All five startup collections restored exactly |
| Production preview/proxy and launcher | HTML and /api/health passed; 3 real HTTP demo-check cycles passed |
| Launcher shutdown | Ctrl-C stopped owned API/preview; both ports free afterward |
| Explicit simulated fallback | 3 moved, 4 preserved, 0 unscheduled; 3 real HTTP reset/replay cycles passed |
| Desktop/mobile layout | Screenshots inspected; no horizontal overflow at 390 px |
| Python compilation and git diff --check | Passed |
| Revised 10-slide PPT | Package/layout/font/native-table checks passed; exported slides visually checked; technical text/media assertions passed |

The clean source copy was prepared in `/private/tmp/studyflow-sept6-work/clean`
without .git, .venv, node_modules or dist, then dependencies were installed from
the declared files. Final frontend source/tests were synchronized into that copy
and the browser suite/build rerun after the small task-detail changes.

Runtime: Python 3.12.14, Node 24.19.0, npm 11.6.0, Playwright 1.62.1.
The browser suite used installed Google Chrome through STUDYFLOW_TEST_BROWSER
with fresh isolated profiles; no existing browser session was used. The normal
Playwright Chromium install command remains documented for other machines.
Clean Python resolved FastAPI 0.141.1, Pydantic 2.13.5, pytest 8.4.2,
httpx 0.28.1 and Uvicorn 0.52.4. Dependency ranges remain as declared; this is
an observed environment, not a cross-platform Python lockfile.

## Artifact and evidence locations

- [Current runbook](RUNBOOK.md)
- [Current video script](VIDEO_SCRIPT.md)
- [September 6 deck](StudyFlow-Hackathon-Demo-Sept6.pptx)
- [A/B detailed evidence and replay](../SEPT6_AB_HANDOFF.md)
- [Actual task and before/after tables](ab-evidence/TASKS_AND_MOVES.md)
- [Human checklist](ABCD_SIGNOFF.md)

Original September 5 deck/handoffs remain historical references. Present from
the September 6 deck. Its fallback is a labeled static summary of API-verified
simulated time; it is not a new UI feature or a live clock manipulation.

## Work deliberately left to the presenters

A local release-candidate snapshot is prepared at
`release/StudyFlow-RC-20260906.zip`, with an adjacent SHA256 checksum. It contains
source, tests, documentation, the revised deck and built frontend. Dependencies,
credentials and Git history are excluded. The internal SOURCE_SHA256.json binds
every included file. This preserves a reviewable local snapshot, not a Git tag
or public release. Rebuild it after any changes with
`.venv/bin/python -m scripts.package_demo`; it replaces the local archive.
On another machine, install README dependencies before running the launcher.

The original source deck remains available. The new deck was imported/exported
with Artifact Tool and its rendered slides checked; native PowerPoint playback
was not tested here. The renderer emitted an embedded-font decode warning,
but the final layout/font checks passed and all slide content rendered. A PNG
of the verified fallback is also available as `Fallback-Recovery-Sept6.png`.

C starts/stops the prepared services and handles recovery. D operates the UI,
speaks, shares the screen and records. They still need spoken rehearsals,
recording and playback/audio checks. Automated three-cycle runs do not certify
a four-minute speech or replace a human sign-off.

No real Canvas/Google account, live Bedrock request, public deployment, uploaded
video or repository visibility change is claimed. The selected delivery is the
documented local offline demo with existing deadlines valid for September 6–7.

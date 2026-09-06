# A/B 实测任务与重排对照

由 scripts/sept6_ab_demo.py 导出的 HTTP 响应整理；不是手写预期任务。

默认模板取样时钟：`2026-09-06T13:45:11.277328+08:00`。日期/时间均为 Asia/Singapore。

## 默认三类考核任务

### Responsible AI Product Pitch

类型 `presentation`；Assessment ID `assessment-presentation-ai-ethics`；总准备估时 270 分钟。

| 实际任务 / ID | 分钟 | 优先级 | 前置任务 |
|---|---:|---:|---|
| Confirm presentation requirements, missing details and group roles<br>`task-2e385d27-eba4-5795-8a14-e25d61bc2953` | 30 | 3 | 无 |
| Create the presentation storyline and outline<br>`task-000aae1a-f771-5f7f-95d6-6edddd376408` | 30 | 3 | Confirm presentation requirements, missing details and group roles |
| Prepare and review presentation materials<br>`task-bf28c39d-ec88-58b0-bc0a-04d53f6d06f6` | 60 | 4 | Create the presentation storyline and outline |
| Write and review speaker notes<br>`task-f9134147-74b1-5bf3-ac83-a9e7de9603cc` | 90 | 4 | Prepare and review presentation materials |
| Run a timed group rehearsal and revise<br>`task-cb4ee78e-be37-53b4-b233-e1379c673de8` | 60 | 5 | Write and review speaker notes |

### Algorithms Midterm

类型 `midterm`；Assessment ID `assessment-midterm-algorithms`；总准备估时 390 分钟。

| 实际任务 / ID | 分钟 | 优先级 | 前置任务 |
|---|---:|---:|---|
| Confirm assessment scope and learning outcomes<br>`task-5d5d3216-fbb5-573a-8d11-b2e1b66ec399` | 30 | 4 | 无 |
| Consolidate notes and topic summaries<br>`task-a64aba18-a1ce-5b46-b8c9-5f5f63f8d9fa` | 120 | 4 | Confirm assessment scope and learning outcomes |
| Complete practice problems and a mock exam<br>`task-35c3669d-2ca7-5c24-b0ab-6900c790007e` | 180 | 5 | Consolidate notes and topic summaries |
| Complete a final review of weak topics<br>`task-4fe3aaf3-81c8-549f-9569-cb9394214518` | 60 | 5 | Complete practice problems and a mock exam |

### StudyFlow Scheduling Assignment

类型 `coding_assignment`；Assessment ID `assessment-coding-studyflow`；总准备估时 315 分钟。

| 实际任务 / ID | 分钟 | 优先级 | 前置任务 |
|---|---:|---:|---|
| Confirm the assignment specification and missing requirements<br>`task-579c6dfc-53c0-5e04-a19b-2d4184a689cd` | 15 | 2 | 无 |
| Design the implementation and interfaces<br>`task-d860df9c-8438-5f7c-9369-a358a213adf7` | 30 | 3 | Confirm the assignment specification and missing requirements |
| Implement the assignment requirements<br>`task-a1ce4e53-ec51-5756-98dd-330dc336f701` | 120 | 3 | Design the implementation and interfaces |
| Write automated tests for the implementation<br>`task-780a64ca-2020-5f4b-a1d5-3dd693ed7d67` | 60 | 3 | Implement the assignment requirements |
| Debug edge cases and review the implementation<br>`task-090f6aad-2d98-5e5a-aa6a-0a27a6a189ff` | 60 | 4 | Write automated tests for the implementation |
| Run final checks and submit the assignment<br>`task-f4c650b6-935d-5d98-9b86-e2fa1d620216` | 30 | 5 | Debug edge cases and review the implementation |

## 默认数据：明确模拟任务结束后 5 分钟观察

请求时间：`2026-09-07T09:05:00+08:00`；Missed task ID：`task-bf28c39d-ec88-58b0-bc0a-04d53f6d06f6`。

| 任务 | 操作前（+08:00） | 操作后（+08:00） | 结果 |
|---|---|---|---|
| Create the presentation storyline and outline | 2026-09-06T20:46:00+08:00 → 2026-09-06T21:16:00+08:00 | 2026-09-06T20:46:00+08:00 → 2026-09-06T21:16:00+08:00 | preserved |
| Debug edge cases and review the implementation | 2026-09-07T17:00:00+08:00 → 2026-09-07T18:00:00+08:00 | 2026-09-07T17:00:00+08:00 → 2026-09-07T18:00:00+08:00 | preserved |
| Confirm presentation requirements, missing details and group roles | 2026-09-06T20:16:00+08:00 → 2026-09-06T20:46:00+08:00 | 2026-09-06T20:16:00+08:00 → 2026-09-06T20:46:00+08:00 | preserved |
| Complete practice problems and a mock exam | 2026-09-06T16:16:00+08:00 → 2026-09-06T19:16:00+08:00 | 2026-09-06T16:16:00+08:00 → 2026-09-06T19:16:00+08:00 | preserved |
| Complete a final review of weak topics | 2026-09-06T19:16:00+08:00 → 2026-09-06T20:16:00+08:00 | 2026-09-06T19:16:00+08:00 → 2026-09-06T20:16:00+08:00 | preserved |
| Confirm the assignment specification and missing requirements | 2026-09-06T21:16:00+08:00 → 2026-09-06T21:31:00+08:00 | 2026-09-06T21:16:00+08:00 → 2026-09-06T21:31:00+08:00 | preserved |
| Confirm assessment scope and learning outcomes | 2026-09-06T13:46:00+08:00 → 2026-09-06T14:16:00+08:00 | 2026-09-06T13:46:00+08:00 → 2026-09-06T14:16:00+08:00 | preserved |
| Write automated tests for the implementation | 2026-09-07T16:00:00+08:00 → 2026-09-07T17:00:00+08:00 | 2026-09-07T16:00:00+08:00 → 2026-09-07T17:00:00+08:00 | preserved |
| Implement the assignment requirements | 2026-09-07T14:00:00+08:00 → 2026-09-07T16:00:00+08:00 | 2026-09-07T14:00:00+08:00 → 2026-09-07T16:00:00+08:00 | preserved |
| Consolidate notes and topic summaries | 2026-09-06T14:16:00+08:00 → 2026-09-06T16:16:00+08:00 | 2026-09-06T14:16:00+08:00 → 2026-09-06T16:16:00+08:00 | preserved |
| Prepare and review presentation materials | 2026-09-07T08:00:00+08:00 → 2026-09-07T09:00:00+08:00 | 2026-09-07T11:00:00+08:00 → 2026-09-07T12:00:00+08:00 | moved |
| Run a timed group rehearsal and revise | 2026-09-07T12:30:00+08:00 → 2026-09-07T13:30:00+08:00 | 2026-09-07T18:30:00+08:00 → 2026-09-07T19:30:00+08:00 | moved |
| Design the implementation and interfaces | 2026-09-07T13:30:00+08:00 → 2026-09-07T14:00:00+08:00 | 2026-09-07T13:30:00+08:00 → 2026-09-07T14:00:00+08:00 | preserved |
| Run final checks and submit the assignment | 2026-09-07T18:00:00+08:00 → 2026-09-07T18:30:00+08:00 | 2026-09-07T18:00:00+08:00 → 2026-09-07T18:30:00+08:00 | preserved |
| Write and review speaker notes | 2026-09-07T11:00:00+08:00 → 2026-09-07T12:30:00+08:00 | 2026-09-07T12:00:00+08:00 → 2026-09-07T13:30:00+08:00 | moved |

未排期任务：0。

## 备用场景：明确模拟 9 月 6 日 11:30 观察

请求时间：`2026-09-06T11:30:00+08:00`；Missed task ID：`task-ef0fff30-1a50-52c7-88ce-8299e76d3afe`。

| 任务 | 操作前（+08:00） | 操作后（+08:00） | 结果 |
|---|---|---|---|
| Completed course review | 2026-09-06T08:00:00+08:00 → 2026-09-06T08:30:00+08:00 | 2026-09-06T08:00:00+08:00 → 2026-09-06T08:30:00+08:00 | preserved |
| Independent course review | 2026-09-06T16:00:00+08:00 → 2026-09-06T16:30:00+08:00 | 2026-09-06T16:00:00+08:00 → 2026-09-06T16:30:00+08:00 | preserved |
| Create the presentation storyline and outline | 2026-09-06T09:30:00+08:00 → 2026-09-06T10:00:00+08:00 | 2026-09-06T09:30:00+08:00 → 2026-09-06T10:00:00+08:00 | preserved |
| Write and review speaker notes | 2026-09-06T13:00:00+08:00 → 2026-09-06T14:30:00+08:00 | 2026-09-06T14:00:00+08:00 → 2026-09-06T15:30:00+08:00 | moved |
| Confirm presentation requirements and missing details | 2026-09-06T09:00:00+08:00 → 2026-09-06T09:30:00+08:00 | 2026-09-06T09:00:00+08:00 → 2026-09-06T09:30:00+08:00 | preserved |
| Run a timed rehearsal and revise | 2026-09-06T14:30:00+08:00 → 2026-09-06T15:30:00+08:00 | 2026-09-06T16:30:00+08:00 → 2026-09-06T17:30:00+08:00 | moved |
| Prepare and review presentation materials | 2026-09-06T10:00:00+08:00 → 2026-09-06T11:00:00+08:00 | 2026-09-06T13:00:00+08:00 → 2026-09-06T14:00:00+08:00 | moved |

未排期任务：0。


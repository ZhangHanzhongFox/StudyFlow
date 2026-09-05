# 2026-09-05 B 线交接：Scheduler / Replan 稳定性与演示核对

## 范围与结论

本轮按 feature freeze 执行，只修复 Scheduler 缺陷、补回归测试并核对演示结果；没有修改前端、Agent、共享 schema、API response shape 或共享 demo fixture。

以本轮代码和本轮实际测试为准，结论如下：

- 新 Assessment 在 C 已暂存 canonical `Assessment` 和 `Task[]` 后，可通过 `new_assessment` Replan 进入计划；原有合法 placement 保留。
- mock 主流程已走真实 State → Agent → Pipeline → Scheduler → API：`slides missed` 后，slides、script、rehearsal 全部移动；completed 和无关合法安排保留。
- Scheduler 输出不覆盖 hard calendar block，不产生 task overlap，不违反依赖，不将未完成任务安排到 assessment deadline 之后。
- deadline 太近、hard block 占满、多个任务竞争 slot、日历变更、已有 completed、跨日依赖和连续 Replan 都有自动测试。
- 每个 active task 在完整 Replan 结果中恰好出现于 `scheduled_tasks` 或 `unscheduled_tasks`；既往已经未排期且与新事件无关的任务也会再次返回失败原因，不再静默遗漏。

本轮修复了两个既有契约缺陷：

1. 跨 assessment 的 ready task 现在先按最早有效 deadline 排序，priority 只在 deadline 相同时打破平局。修复前，较晚 deadline 的高 priority task 可能占掉较早 deadline 的唯一 slot。
2. Replan 会重新评估所有没有 placement 的未完成任务。修复前，一次 partial result 之后再发生窄范围事件，先前未排期但无关的任务可能从本次结果消失，并被状态层判为无效结果。

## Scheduler 约束与失败原因

### 必须满足的约束

1. 时间均为 timezone-aware datetime；搜索 slot 和比较 deadline 使用绝对时刻。
2. 新 placement 不早于 planning/replanning start，也不早于 assessment `unlock_at`。
3. 每个任务必须占用一个连续时段，长度严格等于 `duration_minutes`。
4. 每日学习窗口默认为 08:00–22:00，以计划所在时区解释。
5. hard `CalendarBlock` 形成不可覆盖的 busy interval；相邻或重叠 hard blocks 会先合并。
6. 任务依赖必须先完成：前置 placement 的 `end_time <=` 后置 placement 的 `start_time`。completed 前置任务可不再拥有 placement。
7. placement `end_time <= Assessment.deadline`。
8. 多个 ready task 先比较有效 deadline，再比较 descending priority，最后保持稳定输入顺序。
9. 任务 placement 互不重叠；preserved placement 同样作为 busy interval。
10. 完整 Replan 结果中，每个未完成任务必须且只能位于 scheduled 或 unscheduled 一侧。

### 失败原因的使用

| reason | 当前准确含义 | 演示文案建议 |
|---|---|---|
| `no_available_slot` | 单个任务要求的连续分钟数超过每日学习窗口总容量 | “任务过长，无法放入单日学习时段” |
| `deadline_constraint` | 从最早可开始时刻到有效 deadline 之间找不到足够长且不与 hard/preserved 时段冲突的连续 slot；包括 deadline 太近或 hard blocks 占满 | “截止时间前没有可用连续时段” |
| `dependency_conflict` | 一个或多个前置任务已经无法排入，因此当前任务不能形成合法依赖顺序 | “前置任务未能完成，后续任务无法排期” |
| `invalid_input` | response enum 保留值；当前确定性 Scheduler 对未知引用、重复 placement、不可移动冲突等输入直接拒绝，API 返回 422，而不是把结构错误伪装成 200 partial success | 不作为普通“无空档”提示展示 |

失败消息中会包含 deadline 或失败的 prerequisite ID。hard block 占满但仍受 deadline 限定时返回 `deadline_constraint`，而不是含糊地丢弃任务。

## 保留策略与 Replan 过程

### 保留策略

- `completed`：状态不可回退；已有 placement 作为历史保留。
- `hard` ScheduledTask：不可自动移动；若新的日历或 deadline 使它非法，本次写入返回 422 并整体回滚。
- unaffected + valid：保留原 `id`、时间和 flexibility。
- `calendar_changed`、`new_assessment`、`assessment_updated`：Pipeline 传 `preserve_valid_affected=True`；即使 Agent 给出较宽候选集，合法旧 placement 仍保留。
- invalid non-hard placement：进入重排集合；依赖它的未完成下游一并重新评估。
- active but already unscheduled：即使不在事件语义影响集合中，也重新评估并在完整结果中明确返回 scheduled 或 failure。

### 重排过程

```text
应用事件状态（missed/completed）
→ Agent 计算语义影响范围
→ B 加入已失效 placement 与所有无 placement 的 active task
→ 沿依赖向下扩展必要重排范围
→ 固定 completed、hard、unaffected valid placement
→ 对 fixed hard dependent 反向传播最晚完成时刻
→ 按 dependency + effective deadline + priority 找连续 slot
→ 验证依赖、deadline、hard blocks 和结果完整性
→ State 原子提交 task status、schedule、calendar 与 event
```

找不到 slot 是正常的 HTTP 200 partial success；非法输入、immutable 冲突或不完整 Scheduler 结果不提交任何状态。

## 三组可重复演示输入与预期

三组均使用 mock / deterministic Agent，不调用 Bedrock。每组开始前重置状态，不把前一组事件带入后一组。

### 场景 1：正常排期（默认 provider mock，固定 2026-09-05 08:00 SGT）

输入：

- `MockDataStore.for_dynamic_provider_demo()`；
- `StudyFlowAgent()` deterministic fallback；
- `StudyScheduler` 的时钟固定为 `2026-09-05T08:00:00+08:00`；
- assessments：Algorithms Midterm（09-10 14:00）、Responsible AI Product Pitch（09-12 16:00）、Coding Assignment（09-14 23:59）；
- 相关 hard block：09-05 11:00–12:00 Personal appointment。09-07 09:00–11:00、09-08 15:00–17:00 的 hard blocks 也在输入中，但本次计划在 09-06 12:30 已结束；
- soft calendar block 可移动，不作为 hard busy interval。

预期 `unscheduled_tasks=[]`，完整顺序如下：

| 任务 | duration | 预期 placement（SGT） |
|---|---:|---|
| Review assessment scope | 30m | 09-05 08:00–08:30 |
| Consolidate notes | 120m | 09-05 08:30–10:30 |
| Extract presentation requirements | 30m | 09-05 10:30–11:00 |
| Practice problems + mock exam | 180m | 09-05 12:00–15:00 |
| Final review | 60m | 09-05 15:00–16:00 |
| Presentation outline | 30m | 09-05 16:00–16:30 |
| Build slides | 60m | 09-05 16:30–17:30 |
| Write script | 90m | 09-05 17:30–19:00 |
| Rehearsal | 60m | 09-05 19:00–20:00 |
| Read coding specification | 15m | 09-05 20:00–20:15 |
| Design implementation | 30m | 09-05 20:15–20:45 |
| Implement | 120m | 09-06 08:00–10:00 |
| Write tests | 60m | 09-06 10:00–11:00 |
| Debug + design note | 60m | 09-06 11:00–12:00 |
| Final checks + submit | 30m | 09-06 12:00–12:30 |

自动核对：`tests/test_default_runtime.py::test_september_5_demo_plan_has_repeatable_times`。

### 场景 2：slides missed → script/rehearsal 重排

输入来自 canonical mock assessments/tasks/calendar/schedule，但将 `planning_events` 重置为空，避免把历史样例数字当成本次事件：

```json
{
  "id": "event-sept5-b-missed",
  "event_type": "task_missed",
  "timestamp": "2026-09-04T12:05:00+08:00",
  "reference_id": "task-presentation-slides"
}
```

调用：`POST /replan`。

预期：

| 分类 | task | before | after |
|---|---|---|---|
| moved | slides | 09-04 09:00–10:00 | 09-04 12:05–13:05 |
| moved | script | 09-05 08:00–09:30 | 09-04 13:05–14:35 |
| moved | rehearsal | 09-06 10:00–11:00 | 09-04 16:00–17:00 |
| preserved | completed requirements | 09-02 09:00–09:30 | 不变 |
| preserved | 其余 11 个无关任务 | 各自原 placement | 全部不变 |

`unscheduled_tasks=[]`。slides 成功重新排入后 status 为 `scheduled`；missed 事实保留在 event history。新 script 可与 09-04 14:00–15:00 的 soft team meeting 重叠，这是当前 flexibility 语义；它没有覆盖任何 hard block。

自动核对：`tests/test_replan_acceptance.py::test_mock_demo_slides_missed_moves_full_chain_and_preserves_other_work`。

### 场景 3：hard block 占满至 deadline，明确无法排期

从 `data/scenarios/replan_acceptance.json` 的 `initial_state` 重置，提交其中 `calendar_changed` request，但把新增 hard block 的 `end_time` 改为 `2026-09-03T18:00:00+08:00`。输入关键值：

- event：09-03 09:00；
- hard block：09-03 09:00–18:00；
- assessment deadline：09-03 18:00；
- completed research：08:00–09:00。

预期完整结果：

| task | 结果 | reason |
|---|---|---|
| research | preserved 08:00–09:00 | — |
| slides | unscheduled | `deadline_constraint` |
| script | unscheduled | `dependency_conflict`（slides） |
| independent | unscheduled | `deadline_constraint` |

HTTP 为 200，calendar change、event 和 partial schedule 一起提交。三个失败任务都不会静默消失；其状态分别回到可解释的 `pending`。随后再提交只影响 independent 的 missed 事件，slides/script 仍会在完整 response 中重复返回准确失败原因。

自动核对：

- `tests/test_replan_acceptance.py::test_no_remaining_slot_commits_calendar_and_explicit_failures`
- `tests/test_replan_acceptance.py::test_later_replan_keeps_reporting_previously_unscheduled_unrelated_work`

## D：moved / preserved / unscheduled 判定

比较操作前完整 schedule 与成功 response 的完整 `scheduled_tasks`，以 `task_id` 建唯一索引；不要按数组顺序或当前页面日期过滤。

先把 `start_time` / `end_time` 解析成 epoch milliseconds 或另一种统一绝对时间，再比较：

| 展示状态 | 互斥判定 |
|---|---|
| `preserved` | 前后都有同一 `task_id`；start/end 是相同绝对时刻；`flexibility` 相同 |
| `moved` | 前后都有同一 `task_id`，但 start/end 的绝对时刻或 `flexibility` 任一不同 |
| `unscheduled` | task 出现在本次 `unscheduled_tasks`；即使旧 schedule 中有它，也优先显示 Unscheduled，不再同时显示 Removed |
| `added` | 只在新 schedule 中出现，且不在 unscheduled 中 |
| `removed` | 只在旧 schedule 中出现，且不在本次 unscheduled 中 |

`ScheduledTask.id` 改动本身不代表 moved。示例：

- before `10:00:00+08:00`，after `02:00:00Z`，结束时刻与 flexibility 也等价：`preserved`。
- script 从 `2026-09-05 08:00–09:30 +08:00` 变成 `2026-09-04 13:05–14:35 +08:00`：`moved`。
- old schedule 有 slides，但 response 中没有 placement 且 `unscheduled_tasks` 有 slides / `deadline_constraint`：只显示 `unscheduled`，并展示 message。

等待 D 联调的现状：`frontend/src/api.ts::compareSchedules` 已使用 `Date.parse` 比较 start/end，能正确处理等价 offset；但尚未把 `flexibility` 纳入 moved 判定。当前页面也会先生成 removed，再另列 unscheduled，需要按上述优先级去重。本轮遵守边界未改前端。

## PPT 内容（B 提供给 D）

### Slide 1 — Scheduler：把 deadline 变成可执行时间块

- 输入：Task dependency graph + duration + priority + assessment deadline + calendar blocks。
- 输出：完整 `ScheduledTask[]` + 每个失败任务的 `UnscheduledTask`。
- 核心保障：08:00–22:00 学习窗口、hard block 不覆盖、依赖先后、deadline 前完成、无双重占用。
- 视觉建议：左侧 dependency DAG，中间 calendar busy blocks，右侧排好的连续 study blocks。

### Slide 2 — Replan：最小必要改动

- Observe：学生 12:05 标记 slides missed。
- Impact：slides → script → rehearsal。
- Preserve：completed requirements 和 11 个无关合法任务原地保留。
- Move：只为受影响链寻找 event time 之后的新 slot。
- Validate + commit：再次检查 hard blocks / dependency / deadline；整次状态原子提交。
- 视觉建议：before/after 双列，用灰色表示 preserved、橙色表示 moved、红色表示 unscheduled。

### Slide 3 — 失败也必须可解释

- hard block 占满至 18:00 deadline。
- research completed：preserved。
- slides：`deadline_constraint`。
- script：`dependency_conflict`，明确指出 slides。
- independent：`deadline_constraint`。
- 结论：partial success 是可用结果；任务不会静默消失，UI 能告诉学生下一步为什么需要人工处理。

## 简短视频讲解稿（约 50 秒）

> StudyFlow 的 Scheduler 不只是找空白格。它先读取任务依赖、预计时长和 assessment deadline，再把 hard calendar blocks 当作不可跨越的约束。所有新安排都必须在学习窗口内、前置任务之后，并在 deadline 前结束。
>
> 当学生在十二点零五分标记 slides missed，Agent 找到受影响的下游 script 和 rehearsal。Replan 不会推倒整个日历：已完成的 requirements 和十一项无关且仍合法的安排全部保留，只移动这条依赖链。新的 slides、script 和 rehearsal 依次排入可用时间，而且再次通过 hard block、依赖和 deadline 校验。
>
> 如果 hard block 一直占到 deadline，系统也不会假装成功或丢掉任务。它明确返回 slides 的 deadline constraint、script 的 dependency conflict，并保留已经完成的工作，让界面能解释问题并等待学生处理。

## 本轮测试结果

以下数字是 2026-09-05 本轮实际执行结果，不引用历史文档数字：

- Scheduler + Replan + Pipeline/API 相关集合：77 passed in 0.45s。
- 后端全量：187 passed in 0.68s。
- 前端 production build：通过，Vite 成功构建 1580 modules。本轮没有修改前端。
- 浏览器 e2e：本轮未运行；需要 Playwright/Chrome 环境，属于等待 D 的展示联合验收。

建议复验命令：

```bash
.venv/bin/python -m pytest \
  tests/test_scheduler.py \
  tests/test_replan_acceptance.py \
  tests/test_replan_impact.py \
  tests/test_planning_pipeline.py \
  tests/test_api_pipeline_integration.py \
  tests/test_default_runtime.py -q

.venv/bin/python -m pytest -q

cd frontend && npm run build
```

## 跨线事项

### 已验证，不等待 D

- API/Pipeline 返回的 moved/preserved 时间、完整 schedule、unscheduled reasons。
- completed 和无关 placement 保留。
- hard block、dependency、duration、deadline、无 overlap 约束。
- 新 Assessment 在 C 完成暂存后的 B 侧调度行为。

### 等待 D 展示联调

1. `compareSchedules` 将 flexibility 纳入 moved 判定。
2. Unscheduled 优先于 Removed，避免同一 task 双重展示。
3. 展示 response 的 failure `message`，不要只显示 reason code。
4. before/after 比较覆盖完整 schedule，不仅 Today's Plan。
5. 用 `10:00+08:00 == 02:00Z` 做一次手工/浏览器验收。

### 给 C 的 fixture 建议（本轮未直接修改）

现有 `data/scenarios/replan_acceptance.json` 是 09-03 的跨线共同验收基线，不建议原地改日期或 ID。若录屏必须让三组场景统一显示 09-05，建议 C 新增独立 `data/scenarios/sept5_demo.json`，复制 canonical shape，并同时调整：

- assessment deadline、event timestamp、所有 ScheduledTask 和 CalendarBlock 的日期；
- 保持每个 duration、dependency、status 和 reference ID 一致；
- 三个 scenario 各自带完整 reset state，使用唯一 event ID；
- normal / missed / unavailable 的 expected schedule 与本文件一致或由共同验收测试重新锁定。

不要把 provider payload、canonical state 与 Agent 生成的 UUID task ID 混在同一场景；若 C 不新增 fixture，当前三组测试和固定输入已经可通过 API/Pipeline 重复验证。

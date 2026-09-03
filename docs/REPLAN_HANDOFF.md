# 9 月 3 日 Replan 联调约定

这份约定已经落实到后端契约、默认实现、前端 API client 和自动验收样例。
它是供 A/B/C/D 使用的共同基线，不代表四位成员已进行人工签收。
接口的权威说明见 [API_CONTRACT.md](API_CONTRACT.md)。不需要 LLM 或 AWS。

## 已定接口

| 操作 | 前端请求 | 后端行为 |
|---|---|---|
| 错过或完成任务 | `POST /replan`，body 是 `PlanningEvent` | 先应用任务状态，再分析影响、重排并保存事件 |
| 新增或修改一个日历块 | `POST /calendar-changes`，body 是 `{event, calendar_block}` | 在临时状态中更新日历，重排成功后一起提交 |
| 刷新页面数据 | `GET /tasks`、`/schedule`、`/planning-events`、`/calendar-blocks` | 读取当前状态，不重新生成任务 |

每次操作只提交一次事件，不先调用 `/planning-events`。
一个逻辑操作使用一个唯一事件 ID；重复提交返回 409。
修改日历使用完整 `CalendarBlock`，`event.reference_id` 必须等于它的 ID。
本轮不支持删除日历块，不改变五个 canonical models 的字段。

## A/B/C/D 接口衔接

| 成员 | 已提供的基线 | 明天应核对/继续完成 |
|---|---|---|
| A | `find_affected_task_ids(event, tasks)`；输入已应用状态变化；missed 排除已完成任务，包含未完成下游 | 核对复杂依赖下的影响范围；calendar 返回所有未完成任务是候选集合，不代表全部要移动 |
| B | `reschedule_tasks(..., *, replanning_start=None, preserve_valid_affected=False)` | 核对重排结果和更多冲突边界；为 calendar 保留有效候选排期，必要时扩展依赖影响 |
| C | `PlanningState.replan()`；两个写接口共用事务；请求 schema 与错误响应 | 核对 API 和状态一致性；维持完整测试通过 |
| D | `replan()`、`changeCalendar()`、`compareSchedules()`、`ApiError`、包含日历的 `getDashboardData()` | 接完成/错过按钮、日历输入、重排前后对比与错误/未排期展示 |

B 的两个参数都是本次调用的输入，不要修改共享 Scheduler 实例的时钟。
C 总是传 `replanning_start=event.timestamp`，calendar 事件额外传
`preserve_valid_affected=True`。所有实现和测试替身必须接受这些参数。
直接调用 `PlanningPipeline.replan()` 的消费者需要传入已更新的任务和日历；
API 使用 `PlanningState.replan()` 自动完成这个步骤。

时间统一为带时区的 ISO 8601。前端 `new Date().toISOString()` 的 UTC 时间可用；
后端保持原排期时区的学习窗口。新安排不能早于事件时间，历史排期不会因时钟推进自动作废。

### B 的专项边界

`StudyScheduler` 会递归重排受影响任务的未完成下游，并把保留排期作为占用时段。
若下游是未来的 `hard` 排期，调度器先尝试把受影响前置任务安排到它之前；只要依赖
顺序仍成立，`hard` 排期保持原样。若没有可行顺序，则拒绝本次重排，不能提交一个
前置任务缺失或晚于固定下游的结果。

`tests/test_scheduler.py` 除初始排期外还覆盖：事件时间下限、跨日多层依赖、deadline
与 hard block、日历变更时的最小移动、连续多次重排、固定下游，以及无空档的明确
失败原因。可单独运行：

```bash
.venv/bin/python -m pytest tests/test_scheduler.py -q
```

## 共同验收样例

唯一输入文件：[replan_acceptance.json](../data/scenarios/replan_acceptance.json)。
`initial_state` 中每个集合都使用 canonical schemas。两组场景分别从这份初始状态开始，
不先调用 `/plan`。示例任务 ID 与默认 Agent 生成的 UUID 不同，不能直接混用。

演示时钟固定在 **2026-09-03，Asia/Singapore**；它不依赖电脑当前时间。
同一 assessment 的 deadline 为当天 18:00。

初始任务：

| 任务 | 初始排期 | 状态/依赖 |
|---|---|---|
| `task-research` | 08:00–09:00 | 已完成 |
| `task-slides` | 09:00–10:00 | 依赖 research |
| `task-script` | 10:00–11:00 | 依赖 slides |
| `task-independent` | 15:00–16:00 | 无依赖 |

**场景一：10:30 标记 slides 为 missed。**

- POST `/replan`，使用 fixture 的 `scenarios.missed.request`。
- slides → 10:30–11:30；script → 11:30–12:30。
- research 保持完成状态和原排期；independent 保持 15:00–16:00。
- 事件只保存一次；成功重排的 slides 状态是 scheduled，错过行为保留在事件记录里。

**场景二：09:00 新增 09:00–10:00 的 hard 课程。**

- POST `/calendar-changes`，使用 `scenarios.calendar_changed.request`。
- slides → 10:00–11:00；script → 11:00–12:00。
- research 与 independent 不变；课程和事件一起保存。

从仓库根目录运行共同验收：

```bash
.venv/bin/python -m pytest tests/test_replan_acceptance.py -q
```

该测试还覆盖 completed、UTC 等价时间、重复事件、请求错误、日历覆盖完成历史、
无空档、更新已有日历块以及重排异常回滚。

## D 的调用顺序

1. 保存当前 `schedule`，禁用重复点击，创建一次操作的 event ID。
2. 调用 `replan(event, signal)` 或 `changeCalendar(change, signal)`。
3. 使用 `compareSchedules(before, result.scheduled_tasks)` 得到 added/moved/removed。
4. 保留 `result.unscheduled_tasks`，然后 `getDashboardData(signal)` 刷新所有集合。
5. 展示事件、变化和未排期原因。不同日期的变动也需能看见，不能只依赖 Today's Plan。

HTTP 200 + 非空 `unscheduled_tasks` 是可展示的部分成功，不是 API 异常。
若写请求已经成功而后续 GET 失败，应提示“已更新，刷新失败”，只重试 GET，
不要重新创建事件。写请求超时则检查事件历史中的原 ID；409 后也先刷新，不盲目生成新 ID。

## 当前边界

- 前端按钮、日历编辑及完整演示交互还需要 D 接入。
- `POST /plan` 仍是重新生成计划，不能用作 Replan 后的刷新或保留执行进度的入口。
- 状态是单进程内存；重启清空，无定时观察、数据库或多用户隔离。
- 已完成任务和 hard 排期不可移动。新增日历与它们冲突时返回 422 并保持旧状态。
- `unscheduled_tasks` 是本次返回结果，没有单独的历史持久化接口。

# 9 月 3 日 Replan 联调约定

## 9 月 4 日 C 增量交接（待 A/B/D 人工签收）

- `POST /demo/reset`：无 body，200 `{status:"reset"}`，恢复启动时全部五个集合。
  必须同时设置 `STUDYFLOW_ENV=demo` 和 `STUDYFLOW_ENABLE_DEMO_RESET=1`；默认/生产不存在此路由。
- `POST /assessment-changes`：`{event, assessment}`，Assessment 为完整 canonical 对象，
  event 类型为 new_assessment / assessment_updated，reference_id 等于 assessment.id。
  返回原 SchedulingResult，部分成功仍是 200；失败全部回滚，重复事件 409。
- deadline/unlock/weightage 更新保留任务；要求字段变化重新拆解，保留 completed 历史，
  新任务不自动继承旧完成状态。涉及删除有事件记录的任务、in_progress 或未完成 hard 工作时
  返回 409，需要团队明确迁移规则。A/B 公共接口未改变。
- D 可调用新增 `resetDemo` / `changeAssessment`；仍用原操作锁，reset 前确认，
  成功后刷新五集合。Reset 清除 UI 旧对比/失败提示；不要调用 Regenerate Plan 替代 reset。
- Preserved 判定：前后同 task_id 且 start/end 代表同一绝对时间；该展示由 D 接入。
- `tests/test_september4_integration.py` 复用 `data/scenarios/replan_acceptance.json`，
  覆盖 reset 重复恢复、三类新增、deadline 部分失败、要求变更保留 completed、错误回滚。
  自动测试不是四人人工签收；D 的新按钮/表单仍需使用这些约定联调。
- 无真实 Calendar OAuth 或写回。完整错误码和保守迁移边界见 API_CONTRACT。
- C 本轮验证：后端 191 项通过，既有浏览器回归 11 项通过，TypeScript 和生产构建通过。
  新 reset/Assessment HTTP 测试包含在后端结果中；新增 UI 尚未实现，不能算作新 UI 验收通过。

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

| 成员 | 已提供的基线 | 当前实现与验证 |
|---|---|---|
| A | `find_affected_task_ids(event, tasks)`；输入已应用状态变化；missed 排除已完成任务，包含未完成下游 | 已补齐复杂图回归和真实调用链测试，见下方 A 验收；calendar 仍返回未完成候选集合 |
| B | `reschedule_tasks(..., *, replanning_start=None, preserve_valid_affected=False)` | 已覆盖事件时间、跨日依赖、冲突、有效排期保留、无空档及连续重排 |
| C | `PlanningState.replan()`；两个写接口共用事务；请求 schema 与错误响应 | 已覆盖重复提交、原子回滚、部分成功与结果完整性检查 |
| D | `replan()`、`changeCalendar()`、`compareSchedules()`、`ApiError`、包含日历的 `getDashboardData()` | 已接入完成/错过、日历新增/修改、跨日期变化、错误与未排期展示；浏览器验收见下方 |

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

## A：复杂依赖影响范围验收

本次保留现有分析算法和 `find_affected_task_ids(event, tasks) -> set[str]`
接口，补充测试与原因说明；不增加运行时解释字段，不修改 B/C/D 的接口或共同验收 JSON。
下面的独立测试样例定义在 [test_replan_impact.py](../tests/test_replan_impact.py)，
全部使用 canonical models，不与上面的共同演示任务 ID 混用。

### 分叉、汇合与三层下游

箭头表示「前置任务 → 依赖它的任务」。除 `other` 属于另一 assessment 外，
其余任务都属于 `assessment-main`；`root` 已完成。

```text
root (completed) ──→ trigger ──→ left ──┐
       │                 └────→ right ─┼──→ join ──→ tail
       └──→ sibling         co-parent ─┘

independent                 other (另一 assessment)
```

在 `2026-09-03T10:30:00+08:00` 对 `trigger` 产生 `task_missed`，
并在调用 A 前将它的状态更新为 `missed`。预期集合精确为
`{trigger, left, right, join, tail}`。

| 任务 | 结果 | 原因 / 依赖路径 |
|---|---|---|
| `trigger` | 纳入 | missed 事件直接引用的未完成任务 |
| `left`、`right` | 纳入 | 分别直接依赖 `trigger` |
| `join` | 纳入一次 | 经 `trigger → left → join` 和 `trigger → right → join` 可达 |
| `tail` | 纳入 | 经 `trigger → left/right → join → tail` 到达第三层下游 |
| `root` | 排除 | 已完成，且属于上游 |
| `co-parent` | 排除 | 虽然也是 `join` 的前置任务，但不是 `trigger` 的下游；影响不反向传播 |
| `sibling` | 排除 | 与 `trigger` 共享祖先，不依赖 `trigger` |
| `independent`、`other` | 排除 | 与 `trigger` 无依赖路径，不因属于同一或另一 assessment 被纳入 |

同样的图若对 `trigger` 产生 `task_completed`，先将它更新为 completed，
预期为 `{left, right, join, tail}`。测试同时覆盖 pending、scheduled、
in_progress、missed 的下游、正反输入顺序、重复调用，以及输入任务和事件不被修改。

### completed 与叶子边界

在基础图上追加 `trigger → done-leaf (completed)` 和
`trigger → done-bridge (completed) → after-bridge (pending)`：

- `done-leaf` 和 `done-bridge` 均排除；`after-bridge` 因依赖路径可达而纳入。
- missed 集合为 `{trigger, left, right, join, tail, after-bridge}`；
  completed 集合为 `{left, right, join, tail, after-bridge}`。
- 这是 A 的图分析边界用例：信任传入的完成状态，先遍历下游，再排除 completed。
  completed 不会截断遍历；此样例不表示正常的按依赖顺序执行历史。
- 在基础图中将叶子 `tail` 标记 missed，只返回 `{tail}`；标记 completed，返回空集合。

### 真实调用链与复验

集成测试从基础图开始，`root` completed、其他任务 scheduled，任务各 30 分钟，
deadline 为当天 18:00。初始排期为 root 08:00、co-parent 08:30、trigger 09:00、
left 09:30、right 10:00、join 11:00、tail 11:30、sibling 15:00、
independent 15:30、other 16:00；保留 10:30–11:00 的 hard 课程。

一次 `POST /replan` 经真实 State、Agent、Pipeline 和 Scheduler，测试记录器只观察
并透传调用：确认 A 收到已应用的 missed 状态，B 收到精确候选集合，事件时钟正确传入。
在这个固定场景里，上述五个候选任务全部移动；root、co-parent、sibling、independent、
other 保持原排期，root 仍 completed。新排期满足事件时间、依赖、deadline 和 hard
约束，完整结果写回状态，事件只保存一次。

A 的返回值是「需要重新评估的候选集合」，不等于所有场景中的实际移动集合。
尤其 calendar 仍返回全部未完成任务，B 通过 `preserve_valid_affected=True`
保留有效排期，并按实际冲突扩展必要的依赖影响。

```bash
.venv/bin/python -m pytest tests/test_replan_impact.py tests/test_agent_workflow.py tests/test_replan_acceptance.py -q
.venv/bin/python -m pytest -q
```

## D 的调用顺序

1. 保存当前 `schedule`，禁用重复点击，创建一次操作的 event ID。
2. 调用 `replan(event, signal)` 或 `changeCalendar(change, signal)`。
3. 使用 `compareSchedules(before, result.scheduled_tasks)` 得到 added/moved/removed。
4. 保留 `result.unscheduled_tasks`，然后 `getDashboardData(signal)` 刷新所有集合。
5. 展示事件、变化和未排期原因。不同日期的变动也需能看见，不能只依赖 Today's Plan。

HTTP 200 + 非空 `unscheduled_tasks` 是可展示的部分成功，不是 API 异常。
State 提交前还会核对结果完整性：每个未完成任务必须且只能出现在完整排期或
`unscheduled_tasks` 之一；重复排期、矛盾结果或静默遗漏会返回 500，并回滚本次操作。
若写请求已经成功而后续 GET 失败，应提示“已更新，刷新失败”，只重试 GET，
不要重新创建事件。写请求超时则检查事件历史中的原 ID；409 后也先刷新，不盲目生成新 ID。

生成计划、完成/错过任务、日历提交及恢复操作共享前端操作锁，覆盖写入和随后读取的整个过程。
界面统一禁用冲突入口，处理函数还通过同步锁防止同一轮渲染前的重复调用。
已保存但刷新失败时，先恢复读取，再允许新的写操作；生成计划后的读取失败同样只重试 GET。

已有任务或排期时，按钮显示 `Regenerate Plan`，确认提示明确说明将替换任务和排期、
重置包括已完成工作在内的任务进度。取消确认不会发送请求；成功重建后清除旧重排结果和恢复入口。

## 浏览器联合验收

`frontend/tests/replan.test.cjs` 通过真实浏览器连接隔离的 FastAPI、Agent、Scheduler 和 Vite，
复用共同验收 JSON。测试固定浏览器时间；跨日用例仅在隔离测试状态中延长 deadline。
重新生成用例先运行真正的 `/plan`，再完成任务并重新生成，避免混用样例 ID 与生成任务 ID。
测试服务的 `/test/reset` 只定义于 `frontend/tests/acceptance_server.py`，不会进入产品 API。

在已安装后端依赖的仓库中，从 `frontend/` 运行：

```bash
# 浏览器验收的可选依赖，不修改项目 manifest 或 lockfile。
npm install --no-save --package-lock=false playwright@1.62.1
npx playwright install chromium
npm run test:e2e
```

默认 Python 为根目录 `.venv/bin/python`；可通过 `STUDYFLOW_TEST_PYTHON` 指定。
也可用 `STUDYFLOW_TEST_BROWSER` 指向本机 Chrome 可执行文件，代替下载 Chromium。
测试使用随机本地端口、独立内存状态和临时浏览器上下文，结束后关闭服务。

验收覆盖：missed 及下游移动、日历新增/修改、无法排期的原因、completed 保留、跨日展示、
重新生成确认/取消与操作互斥、Plan/Replan 写入成功后只重试读取、写入失败后的原事件重试，
以及响应丢失后通过事件历史恢复且不重复提交。

正常运行模式的额外验收使用默认 `create_app(clock=...)`，将系统时间固定在 mock 日历之后的
9 月 4 日，确认生成计划后 Today's Plan 显示当天任务。默认 API 每次排期读取当前新加坡时间，
不会继续沿用旧 mock 或上次计划的起始日期。

2026-09-04 本地复验：后端 173 项测试、Chrome 浏览器 11 项验收全部通过；
前端 TypeScript 检查和生产构建通过。此结果覆盖 mock + 确定性 Agent/Scheduler 的
9 月 3 日核心闭环，不等同于真实云服务验证或团队人工签收。

## 当前边界

- 前端交互已接入并提供可重复运行的浏览器联合验收；团队人工签收仍需各成员确认。
- `POST /plan` 仍是重新生成计划，不能用作 Replan 后的刷新或保留执行进度的入口。
- 状态是单进程内存；重启清空，无定时观察、数据库或多用户隔离。
- 已完成任务和 hard 排期不可移动。新增日历与它们冲突时返回 422 并保持旧状态。
- `unscheduled_tasks` 是本次返回结果，没有单独的历史持久化接口。

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

| 成员 | 已提供的基线 | 当前实现与验证 |
|---|---|---|
| A | `find_affected_task_ids(event, tasks)`；输入已应用状态变化；missed 排除已完成任务，包含未完成下游 | 已补齐复杂图回归和真实调用链测试，见下方 A 验收；calendar 仍返回未完成候选集合 |
| B | `reschedule_tasks(..., *, replanning_start=None, preserve_valid_affected=False)` | 已覆盖事件时间、跨日依赖、冲突、有效排期保留、无空档及连续重排 |
| C | `PlanningState.replan()`；两个写接口共用事务；请求 schema 与错误响应 | 已覆盖重复提交、原子回滚、部分成功与结果完整性检查 |
| D | `replan()`、`changeCalendar()`、`compareSchedules()`、`ApiError`、包含日历的 `getDashboardData()` | 已接入完成/错过、日历新增/修改、跨日期变化、错误与未排期展示；浏览器验收见下方 |

B 的两个参数都是本次调用的输入，不要修改共享 Scheduler 实例的时钟。
C 总是传 `replanning_start=event.timestamp`；calendar、new assessment 和
assessment updated 事件额外传 `preserve_valid_affected=True`。这些事件会提供
较宽的候选集合，但不代表候选任务必须全部移动。所有实现和测试替身必须接受这些参数。
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

### 新增／更新 Assessment 的 B 侧约定

- C 在调用 Pipeline/B 前先暂存新的 `Assessment` 和 A/C 已协调好的 `Task[]`；B 不读取
  provider payload，也不负责判断 description 是否改变。
- `new_assessment` 的新任务没有旧 placement，因此会在 `event.timestamp` 之后加入现有
  计划；其他 assessment 的有效 placement 继续占用原 slot。
- 仅修改 deadline 时保持 task ID、依赖、duration、status。deadline 延长不会移动有效
  placement；deadline 缩短会重排越界 placement，并仅沿依赖传播必要移动。
- 要求改变并重新拆解时，C/A 必须合并 completed task，不能把它重置或删除；已移除的
  未完成 task 对应的旧 placement 应在调用 B 前从输入 schedule 清理。B 会拒绝引用未知
  task 的旧 placement，避免把状态拼接错误静默当作一次成功重排。
- completed placement 和有效 hard placement 始终保留。如果新 deadline 或 calendar
  约束会让 immutable placement 非法，本次更新必须失败并回滚，不能为迁就更新而移动它。
- 返回值仍是完整 `SchedulingResult`。每个未完成 task 必须恰好出现在
  `scheduled_tasks` 或 `unscheduled_tasks` 之一；排不下是可提交的部分成功，不得静默丢弃。

### Preserved 的稳定判定（D 可直接实现）

以操作前完整 schedule 与成功响应的完整 `scheduled_tasks` 建立 `task_id` 唯一索引，
按以下互斥规则分类：

| 分类 | 判定 |
|---|---|
| `Preserved` | 前后都有相同 `task_id`，`start_time`、`end_time` 表示相同绝对时刻，且 `flexibility` 相同 |
| `Moved` | 前后都有相同 `task_id`，但上述任一排期属性不同 |
| `Added` | 只在新 schedule 中出现 |
| `Removed` | 只在旧 schedule 中出现，且本轮没有同 task 的 `UnscheduledTask` |
| `Unscheduled` | 成功响应的 `unscheduled_tasks` 中出现；若旧 schedule 有该 task，应优先显示为 Unscheduled 而不是普通 Removed |

`ScheduledTask.id` 是 placement 记录 ID，不作为 moved/preserved 的判定字段；序列化 offset
不同但绝对时刻相同（例如 `10:00+08:00` 与 `02:00Z`）仍算未移动。比较前后两个完整结果，
不根据数组顺序或界面当前日期过滤。该规则只用于派生展示，不向 canonical models 或 API
response 增加字段。

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

## 9 月 4 日 A：异常处理与 Assessment 交接

本轮交付边界为 **A 内修复 + 已验证的现有接口组合约定**，不代表已完成
Assessment 写入 API、自动重拆替换或前端 fallback 原因展示，也不代表四人已签收。
不修改五个 canonical models、公共 ID 算法、Agent/Scheduler 接口或 HTTP response shape。

### 已实现的 Agent 防线

- 分类和拆解结果在 Agent 内再次验证；provider 返回 Pydantic 实例也不能绕过嵌套字段验证。
  错误字段、空 Task[]、不可解析结构、非法值、自依赖、重复步骤/依赖、未知依赖和环均拒绝。
- LLM 草稿的时长和优先级要求真正的整数，拒绝布尔值、字符串和浮点数；不改变 canonical Task。
  任一 LLM 阶段失败时使用完整 fallback，不让部分坏结果进入 Scheduler。
- Canvas description 缺失/null 仍由既有 adapter 转为 `""`；Agent 接收 canonical Assessment，
  不给 schema 新增可空字段。空白或信息不足使用通用准备步骤，先确认要求；不猜题目、技术栈、
  grading rules、demo 或 design note。模板时间是估计，不是课程事实。
- Presentation 按 `is_group` 区分个人和组队；materials/notes 使用通用措辞。
  Exam/Midterm 仅生成准备工作。模板的 step key、ID 生成方式、依赖结构和时长保持不变。
- 原有下游闭包语义不变：只沿依赖正向传播，穿过 completed 后继续遍历，再排除 completed。
  本轮额外保存本次遍历的一条确定性见证路径用于日志，不再调用 LLM 推测原因。

结构/图验证不等于自然语言事实核验；LLM 输出的语义真实性仍需源要求或人工核对。
`description=provided` 仅表示非空，不代表要求完整。

### new_assessment：已验证的调用前提，不是新增端点

C 的接线需在暂存状态中完成以下流程，A 的返回类型保持原样：

1. 规范化并验证新 Assessment，检查它的 ID 未被已有 Assessment 占用。
2. 调用 `classify_assessment(new)`，将已验证类型用于 `decompose_assessment(classified)`。
3. 将生成的 Task[] 合入旧集合；保留旧任务、completed、排期和事件。
   校验完整图、跨集合引用及重复 ID，不重复添加同一 Assessment 的任务。
4. 调用现有 `PlanningPipeline.replan(event, assessments, tasks, calendar, schedule)`。
   A 选出新 Assessment 的未完成任务；B 按事件时间安排，保留其他有效排期。
5. C 负责最终事务与事件去重；无法排期使用原有 `unscheduled_tasks`，不能静默丢弃新任务。

`tests/test_assessment_agent_handoff.py` 用测试内暂存状态和真实 Agent/Pipeline/State/Scheduler
验证上述调用组合，包括四种类型、provider 失败、时间不够时的明确失败结果。
测试初始化暂存状态不等于生产 assessment upsert 事务；该事务仍待 C 接线。
裸 `/replan` 不执行步骤 1–3；`/plan` 会重建全量任务，不能用来冒充保留进度的新增入口。

### assessment_updated：影响范围与保留策略

- A 只有 `PlanningEvent + Task[]`，没有前后 Assessment；无法判断哪个要求字段变化。
  当前确定性约定是返回该 Assessment **全部未完成任务**。同 Assessment 的独立任务也在候选中，
  这是 assessment 级保守范围；不要套用 task event 的“只影响下游”规则。
- completed、其他 Assessment 排除；全 completed 或没有任务时返回空集合。
  A 无法区分“Assessment 不存在”和“存在但无任务”；Assessment 引用存在性由 C 校验。
- 仅 deadline/unlock 等时间约束变化：C 暂存新 Assessment，保留 Task 身份、内容、依赖、完成状态，
  再交 A/B；不重新分类或拆解。若新约束与 completed/hard 历史冲突，B 拒绝，C 应回滚整个更新。
  当前测试验证的是输入更新后的重排边界，不宣称已有 Assessment 写入事务。
- 要求变化且需要重拆：**本轮不自动替换旧 Task[]**。保留原任务/完成状态/排期/事件，
  由 C 阻断自动替换并提示需要确认；该阻断是待 C 接线的约定，不是新上线的 API 行为。
  不通过任务名或相同 step key 推断新任务已完成；相同 ID 也不证明要求语义相同。
- 四人同步前不实施删除/合并：completed 可能依赖旧未完成任务，历史事件也可能引用旧任务。
  仅保留 completed 后删除其余任务仍会破坏引用。未来替换必须共同确定新旧身份映射、
  旧任务/事件的保留或迁移、completed 语义、依赖重连及 hard 排期处理，不能重置进度掩盖问题。

### Agent Activity：证据来源与可用文案

`backend.agents.workflow` 使用 Python 日志记录实际分支：正常决策为 INFO，fallback 为 WARNING。
日志是诊断输出，不是新增公共接口或持久化 Activity 模型；不从前端解析服务端日志。
INFO 是否展示由 C 的日志配置决定；测试可以通过 `--log-cli-level=INFO` 查看。

| 实际证据 | 可用的简短原因 |
|---|---|
| `template_default` | 按 assessment 类型使用准备模板；用时为估计，请先确认要求 |
| `validated_llm` | 结构化拆解已通过字段与依赖校验；任务按这些前置依赖准备 |
| `provider_output_unavailable` | 模型服务未提供可用结构化结果，已使用确定性 fallback |
| `invalid_structure` | 模型结果字段或值不合法，已使用确定性 fallback |
| `invalid_dependencies` | 模型生成的依赖图无效，已使用确定性 fallback |
| `dependency_candidates` + 实际路径 | 此未完成任务沿依赖路径受到引用任务影响，需要重新评估 |
| `assessment_candidates` | 重新评估这项 assessment 的未完成工作；事件未提供要求差异 |
| `calendar_candidates` | 重新检查未完成任务与所提供日历的兼容性 |

分类 fallback 保留已规范化类型；拆解 fallback 使用模板。`template_fallback` 记录最终模板输出，
前面的 WARNING 指明真实失败阶段。没有配置 LLM 的正常模板路径不误报为 provider 故障。
日志包含操作、assessment/event/task ID、计数和真实依赖边/路径；不包含 description、
provider 生成的任务正文、完整响应或原始异常消息。见证路径可能穿过 completed，
但 completed 不作为受影响候选输出；分叉汇合只记录一条可复现的路径，并非声称只有一条路径。

D 现在可以使用事件类型/reference、Task 依赖和请求前后排期支持的文案，但必须区分：

- “事件已记录”不等于“已重排”；观察专用 `/planning-events` 不调用 A/B。
- “依赖上需要重新评估”不等于“排期已移动”；实际移动以成功响应前后的 schedule diff 为准。
- 只有当前任务图时，只能描述当前依赖，不得重建并宣称历史事件当时的完整原因。
- 单凭事件/Task/SchedulingResult 不能推断 LLM 或 fallback 路径；无证据时不展示具体原因。
  不把原因塞入 Task.name、PlanningEvent.reference_id 或 Scheduler 的失败 message。

### B/C/D 待对齐与专项复验

- **B**：候选范围不等于移动集合；本轮不改变 Scheduler 参数，assessment 事件仍沿用
  `preserve_valid_affected=False`。只保证无关的有效排期可保留，不承诺 assessment 候选最小移动。
- **C**：确认 Assessment 输入/旧新版本比较与暂存事务，接线前不得宣称新增/更新已经端到端支持；
  确认需重拆时的用户提示、历史引用保护，以及日志的请求关联/最终事务成功状态。
- **D**：依据上表及实际可见证据调整 Activity；需显示运行时 fallback 原因时，与 C 先提交
  原因传输、请求关联、成功/失败语义的合同提案给四人确认。本轮没有新增解释字段或端点。

```bash
.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_agent_boundaries.py tests/test_bedrock_llm.py tests/test_replan_impact.py tests/test_assessment_agent_handoff.py tests/test_planning_pipeline.py tests/test_replan_acceptance.py -q
.venv/bin/python -m pytest -q
```

专项覆盖输出验证、三类工作流（Exam/Midterm 分别测试）、复杂依赖原因、Assessment 交接和真实调用链。
不需要凭据或付费 LLM 请求；本轮未执行真实云服务或前端浏览器验收。

2026-09-04 本轮 A 复验：上述专项命令 **300 passed**，完整后端 **386 passed**，
`git diff --check` 通过。相对本轮开始的 173 项后端基线新增 213 项参数化/聚焦测试。
默认运行集成测试改为按实际依赖关系选取任务，不再把名称中的 `slides` 当作稳定标识。

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

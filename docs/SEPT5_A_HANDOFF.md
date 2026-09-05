# 2026-09-05 A：Agent / Workflow 收尾与演示交接

日期：2026-09-05（Asia/Singapore）。本文件记录当前代码与本轮实测；不将 PLAN 或旧交接中的历史完成项视为证据。

## 1. 实际完成与边界

本轮增加 `tests/test_sept5_agent_demo.py` 的 34 项验收，未发现必须修复的 Agent 算法或模板缺陷，保留现有运行时实现。没有修改前端、Scheduler、schemas、API shape、公共 fixtures 或他人文件；未接新外部服务。

| 事项 | 当前证据与结论 |
|---|---|
| 三类 assessment 新增 | 真实 POST `/assessment-changes` → State 分类/拆解 → Agent 影响分析 → Scheduler → 原子保存；Presentation、Exam、Midterm、Coding Assignment 均通过 |
| 名称/分钟/优先级/依赖 | HTTP 生成结果经过 canonical Task 与图验证；名称非空、分钟严格正整数、priority 1–5；新任务与确定性 Agent 输出一致，排期后状态为 scheduled |
| 缺失信息 | 空白与部分描述可生成通用准备步骤；模板先确认要求，不推断题目、技术栈、评分规则或缺失提交物 |
| LLM 异常 | 新增入口实测 provider 异常、分类失败、布尔时长、循环依赖；失败结果不会混入模板任务。原有专项还覆盖未知依赖、自依赖、重复 key/依赖、额外字段、空结果、构造/篡改 Pydantic 实例等 |
| HTTP 非法输入 | 未支持的 type、description=null、无时区 deadline、额外字段返回 422；五个集合不变，不进入 Agent 拆解 |
| missed slides | 新增真实 Presentation，完成 requirements/outline，再 missed materials；精确候选为 materials、notes、rehearsal，三项实际移动；其余排期保留 |
| 无法排下 | deadline 只剩 1 分钟，200 + 五条明确 unscheduled；旧排期保留，新任务及事件保存；不是“全部安排成功” |
| 去重与状态 | 成功后重试同一新增/错过事件返回 409，状态不再变化；历史事件保留，missed 成功排期后恢复 scheduled |
| 前端支持 | `changeAssessment` 客户端存在，App 尚未调用；提供请求示例、结果刷新约定和文案，未宣称新增界面验收完成 |

当前实现与历史 `REPLAN_HANDOFF.md` 的差异：C 已提供 `/assessment-changes`；requirements 更新会重新分类拆解并保护完成历史及其祖先，冲突时拒绝；assessment 重排目前传 `preserve_valid_affected=True`。旧文档中“待接线”“不自动替换”“False”的段落仅代表当时约定。详见当前 `docs/API_CONTRACT.md` 及 `backend/services/state.py`、`assessment_changes.py`、`planning.py`；本轮不改这些跨线文件。

## 2. 可直接使用的新增请求与真实任务示例

以下三组完整 JSON 可作为 POST `/assessment-changes` 的请求体；Exam/Midterm 共用准备模板，另测 `midterm` 枚举。它们是明确标注的模拟输入，不是实际课程要求。

时间固定为 2026-09-05 09:00+08:00，deadline 为 9 月 7 日 18:00。不要把固定模拟事件时间直接当作真实用户观察时间。任务表由本轮离线真实 HTTP 入口返回后的 GET `/tasks` 生成，不来自手写预期任务数组。

分钟为个人专注准备时间估计，不代表考核时长或保证完成所需时间。现有优先级是 1–5 的相对调度权重，5 较高，不能越过前置依赖。现有模板无明显结构问题：Presentation 270 分钟，Exam/Midterm 390 分钟，Coding 315 分钟；不因主观偏好重新调参。Speaker notes 90 分钟包含写作和复核；考试练习/模拟为 180 分钟的现有连续任务，若空档不足会明确未排期，本轮不新增拆分功能。

Presentation 使用通用 materials/notes 名称；本例源描述明确要求 slides，故演示可以称其为 slides。ID 不含可供搜索的 slides 文本，不按名称匹配或混用公共 fixture 的 `task-slides`。

### presentation

```json
{
  "assessment": {
    "id": "sept5-presentation",
    "course_code": "DEMO1000",
    "title": "September 5 presentation demo",
    "description": "Prepare an individual presentation with slides and speaker notes.",
    "type": "presentation",
    "unlock_at": null,
    "deadline": "2026-09-07T18:00:00+08:00",
    "weightage": null,
    "is_group": false,
    "group_size": null
  },
  "event": {
    "id": "add-sept5-presentation",
    "event_type": "new_assessment",
    "reference_id": "sept5-presentation",
    "timestamp": "2026-09-05T09:00:00+08:00"
  }
}
```

| Task ID | 实际任务名称 | 分钟 | 优先级 | 前置 Task ID |
|---|---|---:|---:|---|
| `task-9842c581-c3d2-5dfc-8bf7-d57db08422b6` | Confirm presentation requirements and missing details | 30 | 3 | 无 |
| `task-374e1d11-c4a4-52bc-8b69-57dca7902b9d` | Create the presentation storyline and outline | 30 | 3 | `task-9842c581-c3d2-5dfc-8bf7-d57db08422b6` |
| `task-5675b716-3694-530a-a10d-881ec0220a2e` | Prepare and review presentation materials | 60 | 4 | `task-374e1d11-c4a4-52bc-8b69-57dca7902b9d` |
| `task-aece6aca-eb87-5f76-8c57-7a154c744816` | Write and review speaker notes | 90 | 4 | `task-5675b716-3694-530a-a10d-881ec0220a2e` |
| `task-c8eb53d4-b88f-579d-aa57-f3f0806870aa` | Run a timed rehearsal and revise | 60 | 5 | `task-aece6aca-eb87-5f76-8c57-7a154c744816` |

### exam

```json
{
  "assessment": {
    "id": "sept5-exam",
    "course_code": "DEMO1000",
    "title": "September 5 exam demo",
    "description": "Prepare for the exam. Confirm the assessed topics with the instructor.",
    "type": "exam",
    "unlock_at": null,
    "deadline": "2026-09-07T18:00:00+08:00",
    "weightage": null,
    "is_group": false,
    "group_size": null
  },
  "event": {
    "id": "add-sept5-exam",
    "event_type": "new_assessment",
    "reference_id": "sept5-exam",
    "timestamp": "2026-09-05T09:00:00+08:00"
  }
}
```

| Task ID | 实际任务名称 | 分钟 | 优先级 | 前置 Task ID |
|---|---|---:|---:|---|
| `task-b6a3ac57-40ea-5da3-813d-cea171895431` | Confirm assessment scope and learning outcomes | 30 | 4 | 无 |
| `task-61476298-74bf-522e-9887-37a2adae91d5` | Consolidate notes and topic summaries | 120 | 4 | `task-b6a3ac57-40ea-5da3-813d-cea171895431` |
| `task-ac33ce4c-1f81-5677-a5d7-15b7c75c3025` | Complete practice problems and a mock exam | 180 | 5 | `task-61476298-74bf-522e-9887-37a2adae91d5` |
| `task-b422d140-d91c-55c3-9226-aa0f0050a35d` | Complete a final review of weak topics | 60 | 5 | `task-ac33ce4c-1f81-5677-a5d7-15b7c75c3025` |

### coding_assignment

```json
{
  "assessment": {
    "id": "sept5-coding_assignment",
    "course_code": "DEMO1000",
    "title": "September 5 coding assignment demo",
    "description": "Implement the assignment and test it against the provided specification.",
    "type": "coding_assignment",
    "unlock_at": null,
    "deadline": "2026-09-07T18:00:00+08:00",
    "weightage": null,
    "is_group": false,
    "group_size": null
  },
  "event": {
    "id": "add-sept5-coding_assignment",
    "event_type": "new_assessment",
    "reference_id": "sept5-coding_assignment",
    "timestamp": "2026-09-05T09:00:00+08:00"
  }
}
```

| Task ID | 实际任务名称 | 分钟 | 优先级 | 前置 Task ID |
|---|---|---:|---:|---|
| `task-8ebda761-d6e7-5410-bb55-b87db7fb6793` | Confirm the assignment specification and missing requirements | 15 | 2 | 无 |
| `task-fd936ea8-a7b2-555f-9c22-65dd2c744cd7` | Design the implementation and interfaces | 30 | 3 | `task-8ebda761-d6e7-5410-bb55-b87db7fb6793` |
| `task-a263eb96-1d58-5f9c-8f94-8e606af4d3c7` | Implement the assignment requirements | 120 | 3 | `task-fd936ea8-a7b2-555f-9c22-65dd2c744cd7` |
| `task-0291b18b-f141-5e95-b628-b493890f0546` | Write automated tests for the implementation | 60 | 3 | `task-a263eb96-1d58-5f9c-8f94-8e606af4d3c7` |
| `task-025d6cb0-6ac8-5c41-86e7-55c344ee2024` | Debug edge cases and review the implementation | 60 | 4 | `task-0291b18b-f141-5e95-b628-b493890f0546` |
| `task-d6fabe02-4628-5ed9-8e8d-b6ae281e2c65` | Run final checks and submit the assignment | 30 | 5 | `task-025d6cb0-6ac8-5c41-86e7-55c344ee2024` |

Midterm 复现：请求中的 assessment `id` 改为 `sept5-midterm`、`type` 改为 `midterm`、title 改为 `September 5 midterm demo`、description 改为 `Prepare for the midterm. Confirm the assessed topics with the instructor.`，event.id 改为 `add-sept5-midterm`，reference_id 同步；其他字段相同。其四个任务名称、时长、优先级与 Exam 相同，但 Task ID 按 assessment ID 独立生成。

Task ID 由 assessment ID + step key 确定性生成。此规则不表示不同 LLM 输出必定得到相同步骤，也不表示 requirements 更新后的事件级新 ID 可视为旧完成任务。新增 API 不返回 Task[]；D 必须在成功后 GET 刷新五个集合，并保留本次响应中的 unscheduled_tasks。

## 3. missed slides 实测与重排范围

复现入口：`test_added_presentation_missed_materials_replans_real_downstream_only`。本测试自己的隔离初始状态含：旧完成工作 08:00–08:30、无关安排 16:00–16:30、hard 课程 12:00–13:00。不得将以下排期当作任意真实日历的保证。

1. 09:00 新增上方 Presentation。
2. 分别在原任务结束时，通过 `/replan` 完成 requirements 与 outline。
3. 11:30 对第三步 materials 的实际 UUID 发送 task_missed 到 `/replan`，不要先 POST `/planning-events`。
4. 比较成功前后的完整排期，随后刷新五个集合；不调用 `/plan` 刷新。

| 准备步骤 | 原排期（9 月 5 日） | 重排后 | 原因 |
|---|---|---|---|
| Confirm requirements | 09:00–09:30 | 不变，completed | 完成工作不进入候选 |
| Create outline | 09:30–10:00 | 不变，completed | 上游不反向传播 |
| Prepare materials（本例 slides） | 10:00–11:00 | 13:00–14:00 | missed 本体；11:30 后不足 60 分钟便遇到 hard 课程 |
| Write speaker notes（script） | 13:00–14:30 | 14:00–15:30 | 依赖 materials |
| Rehearsal | 14:30–15:30 | 16:30–17:30 | 依赖 notes；保留 16:00–16:30 无关安排 |

三项候选在这个场景中都移动；一般情况下候选仅表示需要重新评估，不等于已经移动。旧完成工作与无关任务不变，所有新排期在事件之后、deadline 之前，不重叠 hard 课程或彼此。

原有 `test_replan_impact.py` 另验证分叉/汇合、三层下游、同祖先 sibling、汇合 co-parent、同 assessment 独立任务、其他 assessment。仅沿依赖正向传播；遍历可以穿过 completed 节点，但最终排除 completed，本身不是正常执行历史的示范。不要据此删除完成历史或反向重排上游。

## 4. Agent Activity：可见证据与替换文案

文案采用英文供当前英文界面直接使用，中文用于团队说明。由 D 修改前端；A 本轮仅提供交接。事件列表单靠 event_type 无法证明重排已执行，当前 `Progress observed and plan updated`、`Requirements were reviewed`、`Availability was re-evaluated` 有过度推断风险。

| 可见证据/展示位置 | 建议英文 | 中文含义与限制 |
|---|---|---|
| 历史 task_completed 事件 | Task completion recorded. | 已记录完成事件；不由事件单独宣称计划更新 |
| 历史 task_missed 事件 | Missed task recorded. | 已记录错过任务；不宣称已移动 |
| 历史 new_assessment 事件 | Assessment addition recorded. | 已记录新增 |
| 历史 assessment_updated 事件 | Assessment update recorded. | 已记录更新；可能只改 deadline，不能说要求已审阅 |
| 历史 calendar_changed 事件 | Calendar change recorded. | 已记录日历变动；不由事件单独证明新时间写入 |
| 新增成功且 GET tasks 刷新成功 | Prepared {N} tasks with time estimates and prerequisite links. | N 来自该 assessment 的实际 Task[]；不是已全部排下的承诺 |
| 当前任务图/详情 | This task depends on {prerequisite names}. | 只描述当前图；不能反推历史事件当时的图 |
| 本次 missed 操作保存的事前图 | {downstream names} depend on this task and need reassessment. | 由事前图正向遍历并排除 completed；含 missed 本体的候选与下游清单区分 |
| 成功写入 + 前后完整排期比较 | {N} tasks moved; {M} placements stayed the same. | 按 task_id 与绝对起止时刻比较；新增/移除另列，不能用数组顺序或 placement ID 变化代替 |
| 200 + 非空 unscheduled_tasks | Plan updated with {N} tasks still unscheduled. | 保留 reason/message 并显示；不显示全部安排成功 |
| 写入成功，后续 GET 失败 | Changes saved. Refresh to see the latest plan. | 只重试读取；不要重复新建事件 |
| 静态工作原理说明 | If model output is unavailable or invalid, StudyFlow can use a validated preparation template. | 是系统能力介绍，不能充当某次运行的 fallback 通知 |

下列原因**仅在后端日志有证据**；目前 PlanningEvent、Task、SchedulingResult 不传输它们，D 不应从任务数量、名称、空描述或缺少日志猜测，也不解析服务端日志。

| 日志事实 | 可用说明（日志/受控演示旁白） |
|---|---|
| `template_default` | No model is configured. Using the assessment-type preparation template. |
| `validated_llm`（decomposition） | Model-generated tasks passed field and dependency checks. |
| `provider_output_unavailable` | Model output was unavailable. Using the deterministic fallback for this stage. |
| `invalid_structure` | Model output failed field validation. Using the deterministic fallback for this stage. |
| `invalid_dependencies` | Model dependencies were invalid. Using the preparation template. |

分类 fallback 保留输入的合法规范化类型；拆解阶段失败则整组改用模板。分类失败不保证随后拆解一定走模板，两阶段独立。正常未配置 LLM 不叫“模型故障”。空描述不强制绕开已配置 LLM；prompt 要求确认缺失信息，模板则提供通用步骤。结构合法不证明自然语言事实真实，不能说“AI 已验证课程要求”。日志不向前端承诺事务最终成功。

## 5. 给 D 的 PPT 文案与短视频稿

交付为可复制内容，不是已制作的 PPTX 或已录制视频。

### 第 1 页：From a deadline to executable preparation

- Deadline 告诉学生何时交付；StudyFlow 将它转成带估时和前置关系的准备工作。
- Presentation：确认要求 → 大纲 → 材料 → 讲稿备注 → 排练。
- Exam/Midterm：确认范围 → 整理笔记 → 练习与模拟 → 查漏补缺。
- Coding：确认规格 → 设计 → 实现 → 测试 → 调试复核 → 检查提交。
- 画面：展示上方真实任务表的名称、分钟和依赖；正式考试本身不是准备任务。

### 第 2 页：Agent interpretation with deterministic checks

- 规范化 Assessment 输入；可配置模型做分类与结构化拆解。
- 字段校验 → step key 转稳定 Task ID → 引用及依赖图校验。
- 时长为正整数分钟；优先级 1–5；不允许无效依赖或环。
- LLM 不可用或输出不合法时可确定性降级；未配置模型时直接使用模板。
- 画面：Assessment → Agent → validated Task[] → Scheduler；不把 Agent 画成直接写日历的模块。

### 第 3 页：Plan → Act → Observe → Replan

- Plan：任务拆解后，Scheduler 安排可用时间。
- Act/Observe：学生标记完成或错过；本 MVP 由显式事件触发，不宣称后台自动监测行为。
- Replan：missed materials → notes → rehearsal 的未完成依赖链需要重新评估。
- Scheduler 保留完成与无关有效安排，避开 hard 课程；无法安排则明确解释失败。
- 画面：第 3 节的前后时间对比，分别标出“候选”和“实际移动”。

### 第 4 页：Honest and resilient demo

- 模板保证离线演示可运行，结构验证不等于对课程事实的证明。
- 缺失要求先确认，不猜技术栈、题目或额外提交物。
- API 返回未排期任务，系统不会靠静默丢失工作宣称成功。
- 当前限制：单进程内存、显式事件、无本轮新增外部集成；前端未取得每次 fallback 的原因。

### 约 80–90 秒中文讲解稿

**0–15 秒｜Assessment 与任务列表**
“学生收到的通常只有截止日期，却还需要知道从哪一步开始。StudyFlow 把考核拆成可执行的准备工作。这里新增的是一项明确要求幻灯片和讲稿备注的个人展示。”

**15–35 秒｜任务链与分钟数**
“系统生成确认要求、大纲、材料、讲稿备注和排练。每一步都有估计分钟数和前置依赖。这些时间是准备估计，不是课程给出的事实。考试与编程作业也有各自的准备流程。”

**35–65 秒｜missed 与前后时间对比**
“现在模拟学生错过材料准备。Agent 沿依赖链找出讲稿备注和排练也需要重新评估。Scheduler 再安排时间，避开中午的固定课程。已经完成的大纲和无关安排保留。这里能看到三项工作的新时间；候选任务并不在每个场景都必须移动。”

**65–90 秒｜校验与 fallback 图**
“模型输出必须经过字段和依赖校验。模型不可用或返回无效结果时，系统可以使用确定性准备模板。本次离线演示使用模板，不代表调用了在线模型。若截止前没有足够时间，系统会明确列出未安排任务。这就是从计划、执行、观察到重排的闭环。”

讲稿默认离线模板演示；若 D 改用真实 LLM，必须自行验证并调整最后一段。不要在未跑过的界面上声称动态 fallback 提示已经上线。

## 6. D/C 明确待办与验收样例

| 负责人 | 具体问题 | 建议与验收标准 |
|---|---|---|
| D | App 未接新增 Assessment 控件，api.ts 已有 changeAssessment | 复用现有操作锁发送完整请求；200 后刷新五集合并保留 unscheduled。三类 + Midterm 各新增一次，旧完成任务/排期不被重建；不使用 `/plan` 代替新增 |
| D | Activity 由 event_type 固定宣称计划更新或要求复核 | 使用第 4 节事件级中性文案；仅成功响应和实际 diff 支持结果说明。POST `/planning-events` 的 task 事件只能显示记录，不能显示已重排；仅 deadline 更新不能写“要求已审阅” |
| D | 文案必须区分候选、移动、部分成功 | 固定第 3 节场景显示三项移动；1 分钟 deadline 用例显示五项未排期，旧排期仍显示。completed、历史事件、跨日变化保持可见 |
| D/C | 当前 API 无运行时 fallback 原因字段 | 本冻结期使用静态说明和离线演示旁白，不新增合同。验收：断开 fake provider 时 API 仍返回合法结果，UI 不声称知道具体 fallback 原因 |
| C | 旧交接部分内容已落后于实现 | 由 C 核对并更新旧文档的 assessment 写入、requirements 重拆和 preserve_valid_affected 说明；以当前 HTTP 新增、时间更新、requirements 更新/冲突测试作为证据，勿继续写入口不存在 |
| D/C | 重试与模拟环境必须一致 | 写入成功 GET 失败只重读；结果未知先查原 event ID；409 不盲目生成新 ID。演示时钟标注模拟、使用实际任务 UUID。reset 若用现有端点，需启用已有 demo 环境开关并确认五集合恢复，A 本轮不新增 UI |

上述前端改动、共享文档更新和团队联合签收仍待负责人执行。本轮不据后端测试宣称浏览器通过；没有需要 A 越界修改的已复现运行时缺陷。

## 7. 测试记录

- 计划阶段基线：Agent + Pipeline + Replan + September4 集成共 **319 passed**。
- 本轮新增专属测试首次执行：**34 passed**。
- 最终专项与相关 HTTP 集成：**378 passed in 1.89s**（以下命令；包含上述 34 项）。
- `git diff --check` 及两个新增文件的 `git diff --no-index --check /dev/null <文件>` 均通过。

```bash
.venv/bin/python -m pytest tests/test_agent_workflow.py tests/test_agent_boundaries.py tests/test_bedrock_llm.py tests/test_replan_impact.py tests/test_assessment_agent_handoff.py tests/test_sept5_agent_demo.py tests/test_planning_pipeline.py tests/test_replan_acceptance.py tests/test_september4_integration.py tests/test_api_pipeline_integration.py tests/test_api.py tests/test_default_runtime.py -q
git diff --check
```

覆盖真实本地 FastAPI、State、Agent、Scheduler；LLM 使用 fake/raw provider，无凭据或付费请求。未运行真实 Bedrock、Canvas/Calendar 网络连接，未做前端浏览器验收，未录制视频或制作 PPTX。未把历史完整后端测试计数当作本轮完整回归结果。

# StudyFlow 9 月 1 日—9 月 7 日开发计划

> 来源：Codex 任务「梳理项目结构与数据模型」中最后一次完整的调整版计划。
> 来源任务 ID：`01a058a4-976c-7033-a913-e66299399bc1`；来源回合 ID：`01a05a91-98d9-7582-af88-0f14e8793180`。
> 整理日期：2026-09-04；日期以 Asia/Singapore 为准。
>
> 版本说明：采用调整后的节点——9 月 2 日 Plan、9 月 3 日 Replan、9 月 4 日集成与异常处理；不是较早“9 月 4 日完成 Replan”的版本。
> 下方原计划保留当时表述。“当前已经完成”“尚未完成”和 40 项测试均是制定计划时的历史快照，不代表今日状态；计划条目不等于完成证明。
> 现行接口与实现细节以 DATA_MODELS、API_CONTRACT 和 REPLAN_HANDOFF 等文档为准；原计划中的接口草案不得直接当作当前调用说明。

总体目标：

```text
9 月 1 日：公共基线 + 四线启动
9 月 2 日：Plan 全链路
9 月 3 日：Replan 全链路
9 月 4 日：集成与异常处理
9 月 5 日：产品完成与演示准备
9 月 6 日：代码冻结、部署、录制
9 月 7 日：最终提交
```

最终演示主线：

```text
导入 Presentation
→ Agent 理解要求并拆解任务
→ Scheduler 根据日历生成计划
→ 用户错过 slides
→ Agent 判断 script/rehearsal 受影响
→ Scheduler 保留有效安排并重新排期
→ Dashboard 展示调整原因和新计划
```

---

## 当前已经完成

公共基础已经具备：

- 五个 Pydantic 数据模型；
- schema 验证和 dependency graph 检查；
- 共享 mock assessments、tasks、calendar、schedule、events；
- Agent、Scheduler、PlanningPipeline 接口；
- FastAPI API 骨架；
- 架构、API、数据模型文档；
- 40 项自动测试；
- `/plan` baseline mock 返回；
- `/replan` 稳定接口占位；
- 本地开发 CORS。

尚未完成：

- 真正的 Agent；
- 真正的 Scheduler；
- 动态 `/plan`；
- 动态 `/replan`；
- Canvas/Calendar adapter；
- Dashboard；
- 部署、PPT 和视频。

---

# 9 月 1 日：公共基线 + 四线核心开发

## 第一阶段：提交公共基线

任何人开始开发前，先完成：

1. 检查仓库改动；
2. 运行：

```bash
python -m pytest -q
```

3. 确认 40 项测试通过；
4. 提交公共基线；
5. 推送到共享仓库；
6. 所有人拉取相同版本；
7. 创建个人开发分支。

公共基线提交：

```text
Build StudyFlow backend foundation
```

建议分支：

```text
agent-workflow
scheduler-engine
backend-integrations
frontend-dashboard
```

如果由 Codex 创建：

```text
codex/agent-workflow
codex/scheduler-engine
codex/backend-integrations
codex/frontend-dashboard
```

## A：Agent / Workflow

今天实现：

- `AgentWorkflow.classify_assessment()`；
- `AgentWorkflow.decompose_assessment()`；
- Presentation workflow；
- Midterm/Exam workflow；
- Coding Assignment workflow；
- 结构化 LLM 输出；
- Pydantic 验证；
- 确定性模板 fallback。

推荐 Presentation：

```text
Extract requirements
→ Build outline
→ Create slides
→ Write script
→ Rehearse
```

推荐 Midterm：

```text
Review scope
→ Consolidate notes
→ Practice problems
→ Mock exam
→ Review mistakes
```

推荐 Coding Assignment：

```text
Read specification
→ Design solution
→ Implement
→ Write tests
→ Debug/refine
→ Submit
```

今天验收：

- 三种 assessment 都能输出合法 `Task[]`；
- Task ID 稳定；
- duration、priority、dependency 完整；
- dependency graph 无环；
- LLM 不可用时仍可用模板生成。

## B：Scheduling / Calendar

今天实现：

- available slot 生成；
- 工作时间范围配置；
- CalendarBlock 冲突检查；
- hard block 不可移动；
- task duration 放置；
- dependency 基础排序；
- deadline 基础检查；
- `SchedulingResult`；
- `UnscheduledTask` 失败原因。

今天验收：

- 能读取现有 mock tasks 和 calendar；
- 能生成不冲突的 `ScheduledTask[]`；
- 不覆盖 hard blocks；
- 所有安排早于 assessment deadline；
- 无法排期时不静默丢失任务。

## C：Data Integration / Backend

今天实现：

- mock Canvas provider payload；
- Canvas mock → `Assessment` 转换；
- mock Calendar loader；
- 当前 planning state 的内存存储；
- Agent 和 Scheduler 注入准备；
- API 错误处理结构。

今天验收：

```text
mock Canvas JSON
→ adapter
→ Assessment[]
→ Pydantic validation
```

真实 Canvas OAuth 暂时不做。

## D：Frontend / Demo

今天实现：

- 前端项目初始化；
- API client；
- Dashboard layout；
- Upcoming Assessments；
- Today’s Plan；
- Agent Activity；
- loading/error/empty 状态基础组件。

今天验收：

- 能调用现有 FastAPI；
- 能显示 mock assessments；
- 能显示 baseline schedule；
- 能显示 planning events；
- 页面不依赖硬编码的本地数组。

## 9 月 1 日结束标准

- 四个人都从相同公共 commit 开发；
- A 能生成 Task；
- B 能生成基础 Schedule；
- C 能转换 mock Canvas；
- D 能展示现有 API 数据；
- 每个人至少有一个可评审提交或 PR；
- 完整测试仍然通过。

---

# 9 月 2 日：打通真实 Plan 全链路

当天唯一核心目标：

```text
Mock Canvas
→ Assessment[]
→ AgentWorkflow
→ Task[]
→ validate_task_graph()
→ Scheduler
→ ScheduledTask[]
→ POST /plan
→ Dashboard
```

## A

- 完善分类和 prompt；
- 处理缺少 description、unlock time 等情况；
- 保证结构化输出稳定；
- 为三种 workflow 添加测试；
- 输出简短的任务拆解解释，供 Agent Activity 使用。

## B

- 完整实现 dependency-aware scheduling；
- 确保 dependency 的前置任务先完成；
- 处理多个 assessment 的优先级；
- 检查任务时长和 scheduled duration；
- 返回明确失败原因：
  - `no_available_slot`
  - `deadline_constraint`
  - `dependency_conflict`
  - `invalid_input`

## C

- 将真实 A/B 实现接入 `PlanningPipeline`；
- 把 `POST /plan` 从 baseline fixture 改为动态计算；
- 保存生成的 tasks 和 schedule；
- 保留 mock baseline 作为 fallback；
- 确保 API 返回与 `API_CONTRACT.md` 一致。

## D

- 添加 Generate Plan 按钮；
- 显示动态生成结果；
- 将 ScheduledTask 与 Task、Assessment 信息组合展示；
- 增加生成中状态；
- 展示无法排期的任务和原因。

## 9 月 2 日结束标准

用户从前端点击 Generate Plan 后，可以看到动态生成的任务和排期。

---

# 9 月 3 日：完成 Replan 全链路

这是项目最核心的一天。

目标：

```text
PlanningEvent
→ Agent 判断受影响任务
→ Scheduler 重排受影响任务
→ 保留 completed 和 unaffected schedule
→ API 返回新计划
→ Dashboard 展示变化
```

## A

实现：

- `find_affected_task_ids()`；
- 下游 dependency closure；
- `task_completed`；
- `task_missed`；
- `calendar_changed`；
- `new_assessment`；
- `assessment_updated`。

关键验收：

```text
task-presentation-slides missed
→ affected:
  task-presentation-slides
  task-presentation-script
  task-presentation-rehearsal
```

## B

实现：

- `reschedule_tasks()`；
- 保留 completed task；
- 保留 unaffected valid placement；
- 只移动必要的 soft/flexible placement；
- 不移动 hard placement；
- 重新检查 dependency；
- 重新检查 deadline；
- 没有可行方案时返回失败原因。

## C

- 将 `POST /replan` 接入 `PlanningPipeline.replan()`；
- POST event 后更新任务状态；
- 保存新 schedule；
- 防止重复 event；
- 支持重置 demo state；
- 保留 event history。

## D

增加：

- Complete 按钮；
- Missed 按钮；
- Replan 操作；
- 新旧时间对比；
- “moved / preserved / unscheduled” 状态；
- Agent Activity 解释；
- 成功和失败反馈。

## 9 月 3 日结束标准

完整演示必须跑通：

```text
slides missed
→ script/rehearsal affected
→ schedule recalculated
→ unaffected tasks preserved
→ frontend shows new plan
```

---

# 9 月 4 日：集成和异常处理

重点不再是增加主功能，而是处理真实边界情况。

## A

测试：

- description 不完整；
- LLM 返回错误字段；
- LLM 返回循环依赖；
- 不同 assessment 类型；
- task event 找不到引用；
- 多层 dependency。

## B

测试：

- 没有可用空档；
- deadline 太近；
- hard block 占满；
- 多任务竞争同一个 slot；
- dependency 无法满足；
- 日历事件临时变化；
- schedule 中已有 completed task。

## C

完善：

- API 422、409、501/业务错误；
- state reset；
- 日志；
- health check；
- CORS；
- OpenAPI 文档；
- clean startup；
- API 与 fixture 一致性。

如果 mock 全链路已经稳定，可以尝试真实 Google Calendar 读取；如果上午仍未跑通，则放弃真实 OAuth。

## D

完善：

- 响应式布局；
- 时间格式；
- 状态颜色；
- 空数据；
- API 错误；
- 无法排期提示；
- 计划生成动画；
- 重排变化高亮；
- Demo reset 按钮。

## 集成场景

当天至少验证：

1. 初次生成计划；
2. 完成任务；
3. 错过任务；
4. Calendar changed；
5. 添加新 Assessment；
6. 无法在 deadline 前排下。

## 9 月 4 日结束标准

系统在正常场景和主要异常场景下都不会崩溃，并能给出可理解的反馈。

---

# 9 月 5 日：产品完成与演示准备

当天开始进入 feature freeze，只允许小功能和体验优化。

## 产品工作

- 修复全链路 bug；
- 优化 Agent Activity 文案；
- 优化任务名称和时长；
- 优化 Dashboard 视觉；
- 确保 demo reset 稳定；
- 完善 README；
- 确保干净环境可以启动；
- 准备部署或本地演示方案。

## Demo 工作

D 主导，但所有人参与提供内容：

- 项目问题陈述；
- Plan → Act → Observe → Replan；
- 系统架构；
- Agent workflow；
- Scheduler constraints；
- Replanning 示例；
- Dashboard 演示；
- 技术栈；
- Hackathon 价值点。

## 视频脚本

建议控制为：

```text
20 秒：学生面对多个 deadline 的问题
30 秒：导入 assessment
40 秒：Agent 拆任务
40 秒：Scheduler 排期
50 秒：错过 slides 后自动重排
30 秒：架构和总结
```

## 9 月 5 日结束标准

- 产品功能完整；
- 主演示流程稳定；
- PPT 完成初稿；
- 视频脚本完成；
- 部署方案确认；
- 不再增加核心功能。

---

# 9 月 6 日：代码冻结、部署和录制

建议 12:00 正式代码冻结。

冻结后只允许：

- 修复阻塞演示的问题；
- 修改文案；
- 修改样式；
- 修复部署；
- 更新文档；
- 补充测试。

必须完成：

1. 从干净环境安装依赖；
2. 运行全部后端测试；
3. 运行前端测试和 production build；
4. 完整演示至少三遍；
5. 录制主视频；
6. 录制备用视频；
7. 完成 PPT；
8. 检查仓库可见性；
9. 检查 README；
10. 准备离线 fallback；
11. 创建 release candidate。

离线 fallback 至少包含：

- 本地 mock 数据；
- 不依赖 Canvas OAuth；
- LLM 失败时使用模板 workflow；
- 预生成 demo baseline；
- 已录制备用视频。

---

# 9 月 7 日：最终提交

当天不做新功能。

只处理：

- 严重 bug；
- 提交平台内容；
- 视频上传；
- PPT 导出；
- 仓库权限；
- 部署链接；
- 项目介绍；
- 最终检查。

建议提前至少三小时提交。

最终检查：

```text
□ Repository 可以访问
□ README 启动命令正确
□ API 可以启动
□ Frontend 可以启动
□ Demo 数据可以重置
□ Plan 可以运行
□ Replan 可以运行
□ 视频链接可以播放
□ PPT 可以打开
□ 提交表单完整
```

---

# MVP 与降级顺序

## 必须完成

- 三种 assessment；
- Agent 拆任务；
- duration、priority、dependency；
- mock Canvas；
- mock Calendar；
- 动态 Plan；
- task missed；
- dependency-aware Replan；
- Dashboard；
- Agent Activity；
- 完整视频。

## 有时间再做

- 真实 LLM 解释优化；
- Google Calendar 读取；
- Canvas API；
- 更复杂的动画；
- 多套 demo 数据。

## 直接放弃或最后考虑

- Canvas OAuth；
- Google Calendar 写回；
- 用户登录；
- 数据库；
- 多用户；
- 通用聊天机器人；
- 复杂云基础设施。

---

# 协作规则

- 每天结束前至少进行一次集成。
- 每个 PR 只包含一个清晰功能。
- 非简单 commit 必须有正文，说明改了什么及原因。
- Commit subject 使用祈使语气、首字母大写、不加句号。
- 合并前必须检查 staged diff 并运行相关测试。
- 不得未经同步修改：
  - `backend/schemas/`
  - shared mock ID
  - `AgentWorkflow`
  - `Scheduler`
  - API response shape
- 公共合同必须同步更新代码、文档、fixture 和测试。
- `main` 始终保持可运行。
- 不允许所有人等到 9 月 5 日或 6 日才第一次合并。

最终关键节点：

```text
9 月 1 日：四条开发线全部启动
9 月 2 日：Plan 全链路完成
9 月 3 日：Replan 全链路完成
9 月 4 日：异常场景稳定
9 月 5 日：产品和演示内容完成
9 月 6 日：代码冻结并录制
9 月 7 日：提交
```


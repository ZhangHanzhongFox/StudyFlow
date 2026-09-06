# 9 月 6 日 A/B：演示场景验证与交接

> 后续 C/D 代码、文档与自动验收已完成，见 [最终技术记录](demo/VALIDATION_SEPT6.md)。本页保留 A/B 交接时的范围和发现；文末给 D 的 PPT/脚本修正已经落实到 September 6 新版材料。当前现场流程以 [RUNBOOK](demo/RUNBOOK.md) 为准。

## 结论与交付边界

2026-09-06 Asia/Singapore 实测。A/B 的离线任务拆解、影响范围、重排约束、备用场景、技术旁白核对已经完成。没有修改 Agent/Scheduler 算法、共享模型、默认 provider fixtures、前端或 PPT。

默认实时数据能够生成完整计划，但 **Generate Plan 后立即 Missed 不会保证移动**。本次 08:00、14:00、23:00 和实际 13:45:11 四个时钟样本，均生成 15 项任务，立即 Missed 均为 0 项移动。这是未来排期仍然有效，不是调度失败。

分别从初始状态重新生成计划，明确模拟前两步完成、材料结束后 5 分钟观察 Missed，四个样本均为材料、讲稿、排练三项移动，其他排期保留。这些完成/错过时间是模拟事件，不代表已经真实学习过。

因此，D 不应录制“默认启动 → Reset → 直接 Missed → 必然三项移动”。C/D 仍需完成默认 UI 流程验收与脚本定稿，A/B 的通过不代替四人签收或代码冻结。

## A：实际任务与能力说明

完整名称、稳定 ID、分钟、优先级、依赖、实际前后排期见 [任务与重排对照](demo/ab-evidence/TASKS_AND_MOVES.md)。原始 HTTP 读写证据见 [默认运行结果](demo/ab-evidence/default.json)。

| 类型 | 任务数 | 准备估时总计 | 工作流 |
|---|---:|---:|---|
| Presentation | 5 | 270 分钟 | 确认要求 → 故事线与大纲 → 材料 → 讲稿备注 → 排练 |
| Exam / Midterm | 4 | 390 分钟 | 确认范围 → 整理笔记 → 练习与模拟 → 查漏补缺 |
| Coding Assignment | 6 | 315 分钟 | 确认规格 → 设计 → 实现 → 测试 → 调试复核 → 检查提交 |

默认 mocks 的考试类型为 midterm；exam 的分类、拆解及异常覆盖由现有 `test_sept5_agent_demo.py` 等测试同时验证，不能称默认数据里另有第四份 exam。

任务 ID 从 assessment ID 和步骤生成，不按 `task-slides` 定位动态任务。Presentation 的第三步实际名称是 `Prepare and review presentation materials`，第四步是 `Write and review speaker notes`。本备用输入明确写了 slides 和 speaker notes，所以旁白可以对应为 slides / script。

本轮确认了名称非空、估时正整数、优先级 1–5、依赖图合法，默认输出与离线 Agent 模板一致。完整回归还覆盖缺少描述、模型异常、无效字段、循环依赖、未排期和回滚。

### D 可直接使用的旁白

> StudyFlow reads normalized assessments and turns each one into preparation steps with time estimates and prerequisite links. In this offline demonstration, we use validated templates. An optional model adapter can provide structured classification and decomposition, with template fallback when output is unavailable or invalid.

> Students report completion or missed work. For this presentation, the materials task is a prerequisite for speaker notes and rehearsal. A missed observation makes that unfinished dependency chain eligible for replanning; it does not mean every task must move.

> The scheduler checks dependencies, deadlines, study hours and hard calendar commitments. It preserves completed work and unrelated valid placements where possible, and returns an explicit reason for work that cannot fit.

时长是专注准备估计，不是考试时长或保证。没有真实 Canvas/Google 同步，没有自动监测学习行为；本轮未做 Bedrock 付费调用。任务/事件 API 没有模型推理字段，不从事件名称猜测模型为什么这样做。

## B：稳定备用场景

沿用 9 月 5 日已验证场景结构，以独立 `ab-*` ID 和 9 月 6 日模拟日期，通过真实新增考核与完成事件入口生成状态；未替换共享历史 fixture。备用初始状态是 **Missed 之前**，已有完成工作，适合展示恢复能力，不充当默认空状态启动演示。

- 模拟观察时间：2026-09-06 11:30 +08:00。
- Presentation 前两步已通过完成事件标记 completed。
- 材料原安排为 10:00–11:00，观察时已经错过。
- hard 课程固定 12:00–13:00。
- 另一考核含已完成的 08:00–08:30 工作、无关的 16:00–16:30 安排。
- deadline 为 9 月 7 日 18:00；本例没有未排期任务。

| 工作 | 重排前 | 重排后 | 解释 |
|---|---|---|---|
| 确认要求 | 09:00–09:30 | 保留 completed | 已完成 |
| 大纲 | 09:30–10:00 | 保留 completed | 已完成 |
| 材料 | 10:00–11:00 | 13:00–14:00 | 11:30 后不足 60 分钟便遇到 hard 课程 |
| 讲稿备注 | 13:00–14:30 | 14:00–15:30 | 等材料完成 |
| 排练 | 14:30–15:30 | 16:30–17:30 | 等讲稿完成，保留无关 16:00–16:30 安排 |
| 旧完成工作 | 08:00–08:30 | 原样保留 | 完成历史 |
| 无关工作 | 16:00–16:30 | 原样保留 | 无关有效安排 |

精确候选范围为材料、讲稿、排练；本例恰好三项都移动、四项保留。独立校验了排期时长、unlock/deadline、前置任务结束时间、hard block 和排期之间的冲突、候选未丢失、重复事件 409 后状态不变，以及完成状态保留。

备用旁白：

> This is a simulated September 6 observation at 11:30. The materials session ended at 11:00 without completion. The hard lecture stays at noon, so materials move to 13:00, speaker notes to 14:00, and rehearsal to 16:30. Completed work and the independent 16:00 session stay in place.

### C 可复制的独立启动与重放命令

仓库根目录，使用已安装 requirements 的环境。先确认 8766 未被其他服务占用：

```bash
.venv/bin/python -m uvicorn scripts.sept6_ab_demo:fallback_app --factory --host 127.0.0.1 --port 8766 --workers 1
```

该入口使用导出的 [fallback.json](demo/ab-evidence/fallback.json)，通过公共模型验证加载。固定 scheduler 时钟仅在这个显式备用入口中使用；正常 `backend.main:app` 不变。无模型请求，不要作为生产服务部署。

第二个终端，仍在仓库根目录：

```bash
curl --fail-with-body -X POST http://127.0.0.1:8766/demo/reset
curl --fail-with-body http://127.0.0.1:8766/tasks
curl --fail-with-body http://127.0.0.1:8766/schedule
curl --fail-with-body -X POST http://127.0.0.1:8766/replan -H 'Content-Type: application/json' --data-binary @docs/demo/ab-evidence/missed-request.json
curl --fail-with-body http://127.0.0.1:8766/schedule
curl --fail-with-body -X POST http://127.0.0.1:8766/demo/reset
```

Reset 恢复此服务的预置 before 状态；重放同一请求前先 Reset，否则预期返回 409。这里不要先 Generate Plan，它会改变备用快照。

这是 API/静态对照备用路径，尚非默认前端的一键切换场景。现有 UI 发真实当前时间，不能直接用普通 Missed 按钮代替这里的 11:30 请求。也不要假设外部 curl 后刷新页面能恢复 UI 的旧排期比较；D 可以使用导出的前后表格作为备用画面。需要在 UI 显示动态对比时，应由 C/D 接好独立环境和明确模拟观察机制，再单独验收。

### 重新验证并导出原始证据

```bash
.venv/bin/python -m scripts.sept6_ab_demo
.venv/bin/python -m pytest tests/test_sept6_ab_demo.py -o addopts='' -q
.venv/bin/python -m pytest -o addopts='' -q
```

导出命令只运行进程内隔离 HTTP app，不会连接或 Reset 正在使用的后端。它更新三个 JSON；`TASKS_AND_MOVES.md` 是本轮证据的人读快照，重新导出后若时间/代码改变应同步该表。脚本针对 9 月 6 日排期验收，fixture deadline 过后可能正确失败，不能无限期当作实时健康检查。请使用普通 Python，不用会关闭断言的 `-O`。

## 现有 PPT / 视频文案核对，交给 D 修改

已读取 10 页 PPT 的文本与 presenter notes；本轮只做事实核对，不声称完成视觉复核，也没有修改 PPTX。

| 位置 | 发现 | 建议替换 |
|---|---|---|
| PPT 第 3 页 | `Affected work moves` 过强；立即 Missed 实测未移动 | `Affected work is reassessed and moved when needed` |
| PPT 第 6 页 | `AI interprets` 易被当成本轮真实模型调用 | 配合说明 `Templates in this offline demo; model-assisted interpretation is optional` |
| PPT 第 6 页 | `Refresh all planning views atomically` 混淆服务事务与五次 GET | `Commit planning changes atomically, then refresh all dashboard views` |
| PPT 第 7 页及其备注 | Reset 后直接看任务并 Missed；缺 Generate Plan，未说明观察时间 | 默认流程加入 Generate Plan；重排场景引用已验证的观察条件 |
| PPT 第 9 页 | 412 后端测试是旧版本结果 | 当前版本 464 passed；前端 8/18 与构建仅保留“历史记录”标签，待 D 本轮重跑后更新 |
| VIDEO_SCRIPT 0:25–1:50 / RUNBOOK golden path | 同样缺生成步骤并预期点击后移动 | 插入生成与任务依赖讲解；不要承诺过早 Missed 必定移动 |

## 本轮验证结果

- 4 项新增 A/B 验收通过；全部后端 **464 passed，1 个上游弃用警告**。
- 默认运行 4 个时钟样本，均 15 项合法任务/排期；立即 Missed 为 0 moved，明确模拟结束后 Missed 为 3 moved；Reset 恢复默认空任务基线。
- 备用场景：3 moved / 4 preserved / 0 unscheduled，export → factory → replan → reset → replay 一致。
- 在独立 Uvicorn `127.0.0.1:8766` 通过真实 HTTP 连续重排/Reset **3 轮**，逐项比对五集合；检查结束后该进程已停止。
- 全量回归同时覆盖原有 LLM 失败/非法结构、日历变化、无法排期、完成/无关保留、事务回滚等情况。
- 本轮没有运行前端测试、浏览器操作或真实模型调用，也未替团队签署联合验收。

## 交给 C/D 的剩余工作

1. C：将本地启动与备用步骤纳入统一运行手册，确认冻结候选版本和环境。
2. D：按上表更新 PPT/脚本，补默认空状态浏览器验收，选择用静态对照还是明确模拟观察展示备用场景。
3. 全体：默认 UI 联调、同版本三遍演练、冻结和签收仍待进行。A/B 没有发现必须修改核心算法的缺陷，本轮不扩大功能范围。

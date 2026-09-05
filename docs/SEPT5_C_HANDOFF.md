# 9 月 5 日 C 交接：后端、干净启动与 9 月 6 日演示

日期：2026-09-05，Asia/Singapore。基于 `origin/main` 的 `a79c9ff`，工作分支
`feature/c-sept5-demo-readiness`。本轮未修改五个 canonical models、共享 fixtures/ID、
A/B 核心实现或 D 前端文件。没有数据库、登录、真实 OAuth、Calendar 写回或外网部署。

## 1. 已有能力与本轮增量

已有的 `/demo/reset`、`/assessment-changes`、事务锁、输入规范化和错误回滚继续复用，
没有重复实现。默认动态启动会加载 **3 assessments、0 tasks、8 calendar blocks、
0 scheduled tasks、0 planning events**；`POST /plan` 后才拆解并排期。

本轮增加：

- `backend/demo_check.py`：需要显式 `--allow-reset` 的本机 HTTP 演示检查，三次完整循环，
  校验五集合、重复请求、三类考核、deadline 部分失败及 reset 后重放。
- `tests/test_sept5_backend_readiness.py`：9 月 5/6 日各 08:00、14:00、23:00 日期矩阵，
  非空启动基线的重复 reset、HTTP 日志不记录请求正文或查询参数，共 8 项。
- HTTP 最终状态/耗时和内部失败类型日志；`backend/logging.json` 提供可直接启动的日志配置。
- 修正一个集成测试调用边界：已暂存 assessment/tasks 的 B 场景调用内部
  `PlanningState.replan`，继续验证原有具体排期和保留断言；HTTP 新增考核仍走
  `/assessment-changes`。没有为了通过测试放开 `/replan` 对裸考核事件的 422 限制。
- README、API_CONTRACT、INTEGRATIONS、REPLAN_HANDOFF 同步当前运行方式。

## 2. D 可直接使用的接口

### 环境与启动

先按 [README](../README.md#local-setup) 安装。仓库根目录，已激活 Python venv：

```bash
STUDYFLOW_ENV=demo STUDYFLOW_ENABLE_DEMO_RESET=1 STUDYFLOW_LLM_PROVIDER=none python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-config backend/logging.json --no-access-log
```

| 配置 | 演示值及边界 |
|---|---|
| `STUDYFLOW_ENV` | `demo`；`development` 也允许 reset，默认 `production` 不允许 |
| `STUDYFLOW_ENABLE_DEMO_RESET` | 必须为 `1`，且满足上一行；仅设置此项不能在 production 启用 |
| `STUDYFLOW_LLM_PROVIDER` | `none`：确定性模板，不调用模型，不需要 AWS/LLM 凭据 |
| worker / host | 一个进程、`127.0.0.1`；无持久化、无鉴权，不作为公开多用户服务 |
| 前端 | `npm ci` 后 `npm run dev -- --host 127.0.0.1 --strictPort` |
| API 地址 | Vite 的 `/api` 代理至 `127.0.0.1:8000`；`VITE_API_BASE_URL` 保持未设置 |

前端用同源代理无需增加 CORS 配置。直接跨源调用时，现有默认允许来源为
`http://localhost:3000`、`http://localhost:5173`；若换成其他 hostname/port，
须通过 `create_app(allowed_origins=...)` 配置精确来源，不要假设 `127.0.0.1` 等于 `localhost`。

### 完整 reset

```bash
curl -i -X POST http://127.0.0.1:8000/demo/reset
```

无请求 body；成功 HTTP 200：

```json
{"status":"reset"}
```

恢复的是**当前进程启动时**捕获的全部五个集合，而不是另一次 Plan，也不是固定假设所有集合为空。
注入非空基线时也逐集合恢复。reset 不追加新事件，旧事件会被清除或恢复为启动基线，
所以基线以外的旧事件 ID 在 reset 后可重用。重复调用结果相同。
候选基线验证完成后才原子替换；错误 fixture 返回 500 `demo_reset_failed`，原状态不变。
路由未启用时 HTTP 404，OpenAPI 中也不存在；重启服务后配置才生效。

D 已有 `resetDemo(signal)`：先确认用户意图，持有公共写锁，成功后调用
`getDashboardData(signal)` 刷新五集合，并清除页面上的旧 Moved/Preserved/Unscheduled 对比。
刷新失败只重试 GET，不要自动再执行 reset。不要把 Regenerate Plan 改名当作 reset。

### 新增 Assessment：可复制的 9 月 6 日演示样例

下面时间是**明确的 9 月 6 日 09:00 演示观察时间**，不是服务器时钟设置。
真实按钮应使用 `new Date().toISOString()` 作为事件时间；其他日期使用时须更新 deadline。

```bash
curl -i http://127.0.0.1:8000/assessment-changes \
  -H 'Content-Type: application/json' \
  --data '{"event":{"id":"event-sept6-new-presentation","event_type":"new_assessment","timestamp":"2026-09-06T09:00:00+08:00","reference_id":"assessment-sept6-demo"},"assessment":{"id":"assessment-sept6-demo","course_code":"DEMO101","title":"Demo presentation","description":"Prepare slides and rehearse the presentation.","type":"presentation","unlock_at":null,"deadline":"2026-09-14T18:00:00+08:00","weightage":null,"is_group":false,"group_size":null}}'
```

使用完整 canonical Assessment，不传原始 Canvas payload，不传局部 PATCH，不增加字段。
三类 `type` 为 `presentation`、`exam`、`coding_assignment`；测试其他类型时也应更换
assessment ID、event ID 和 reference_id，避免有意触发重复冲突。
事件 `reference_id` 必须等于 assessment.id。

成功 HTTP 200 返回**完整结果**的原 `SchedulingResult`，而非只返回新增任务。
下面仅示意结构和单条记录，真实 ID/时间及数组长度由本次状态决定：

```json
{
  "scheduled_tasks": [
    {"id":"scheduled-example","task_id":"task-example","start_time":"2026-09-06T10:00:00+08:00","end_time":"2026-09-06T11:00:00+08:00","flexibility":"flexible"}
  ],
  "unscheduled_tasks": []
}
```

### 更新 deadline／要求

先 GET `/assessments` 获取完整当前对象；保留其 ID 和其他字段，修改目标字段，包装为同样的
`{event, assessment}`。新事件类型为 `assessment_updated`，使用新的事件 ID。
例如在以上新增之后提交更紧的 deadline：

```bash
curl -i http://127.0.0.1:8000/assessment-changes \
  -H 'Content-Type: application/json' \
  --data '{"event":{"id":"event-sept6-tight-deadline","event_type":"assessment_updated","timestamp":"2026-09-06T09:00:00+08:00","reference_id":"assessment-sept6-demo"},"assessment":{"id":"assessment-sept6-demo","course_code":"DEMO101","title":"Demo presentation","description":"Prepare slides and rehearse the presentation.","type":"presentation","unlock_at":null,"deadline":"2026-09-06T09:01:00+08:00","weightage":null,"is_group":false,"group_size":null}}'
```

该例应产生无法排下的任务：HTTP **200 部分成功**，`unscheduled_tasks` 包含
`task_id`、`reason`、`message`；不要把 HTTP 200 渲染成“全部完成”。允许的 reason 为
`no_available_slot`、`deadline_constraint`、`dependency_conflict`、`invalid_input`。

仅 deadline/unlock_at/weightage 改变：复用任务 ID、依赖、状态，重新检查排期。
title/description/type/course_code/is_group/group_size 改变：重新拆解该考核，
保留 completed 及其依赖历史，新增工作不会自动继承“已完成”。未完成旧任务若有观察历史、
正在进行，或有 hard 保护，可能返回 409 `assessment_conflict`；本轮不扩展复杂进度迁移。

D 调用已有 `changeAssessment(change, signal)`，写成功后刷新全部五集合。
不要先 POST `/planning-events`，也不要把 new/update 的裸事件 POST 到 `/replan`。
前后通过 `compareSchedules` 对比：同 task_id、相同绝对 start/end 时间且 flexibility
不变才是 Preserved；placement ID 改变本身不算 Moved。Unscheduled 必须保留写响应，
单独 GET `/schedule` 不能恢复上一轮未排期原因。

### 错误和重试约定

| HTTP | 意义 | 前端动作 |
|---|---|---|
| 200 + unscheduled 非空 | 有效部分排期已保存，实体和事件也已提交 | 刷新状态并展示每项原因 |
| 422 | 非法/额外字段、无时区时间、未知引用、不可满足的不可变约束 | 保留输入，显示校验详情，不自动重试 |
| 409 `duplicate_event_id` | 该事件已经提交，未重复执行 | GET events 确认原 ID，然后刷新，不换 ID 盲重试 |
| 409 `assessment_conflict` | 重复新增实体或受保护工作冲突 | 刷新实体，要求用户/团队选择如何处理 |
| 404 reset | 非 demo 或开关未生效 | 隐藏/禁用演示能力并提示启动配置 |
| 501 `replanning_not_implemented` | 显式注入无 pipeline 的测试/兼容模式 | 检查服务启动方式；默认动态 app 不应返回此状态 |
| 500 | 内部失败、无效 pipeline 输出或 reset fixture 失败；事务回滚 | 显示失败、保留旧视图；必要时读状态确认后再重试 |

业务错误通常为 `{"detail":{"code":"...","message":"..."}}`；请求模型校验为 FastAPI
标准 `detail` 数组。现有 `ApiError` 已兼容二者。网络断开不是回滚证明：请求可能已提交，
先 GET events 查找原 event ID；同一逻辑尝试保留原 ID。写互斥持续到读取刷新结束。
五次 GET 不是跨多用户的版本化快照，本地单用户演示用现有写锁，勿增加后台写入。

## 3. 实际验证证据

不是沿用 412/11 的旧数字。本次初跑 main 是 **451 通过、1 失败**；失败为上述
“已暂存实体测试走裸事件 HTTP”边界不匹配。修正该测试并新增 8 项后：

| 检查 | 实际结果 |
|---|---|
| 干净 Python 依赖安装 | `pip install -r requirements.txt` 成功；`pip check` 无依赖问题 |
| 全部后端 | `python -m pytest -o addopts='' -q`：**460 passed**，2 个上游弃用警告 |
| 前端干净依赖 | 独立 source/frontend 中 `npm ci` 成功，119 packages，audit 0 vulnerabilities |
| 前端单元测试 | `npm test`：**8 passed** |
| 浏览器回归 | `npm run test:e2e` 对应 Node 测试入口：**13 passed，0 failed** |
| 前端生产构建 | `npm run build`：两套 TypeScript 检查与 Vite build 通过 |
| 实际服务启动 | 隔离 Uvicorn 监听 `127.0.0.1:8765`；health、OpenAPI、Plan 均通过真实 HTTP |
| 实际 HTTP 连续演示 | `python -m backend.demo_check --base-url http://127.0.0.1:8765 --allow-reset`：3 轮每轮生成 15 项排期，新增三类考核、收紧 deadline、重复/非法请求、reset/replay 均通过 |
| reset 最终状态 | 3 assessments / 0 tasks / 8 calendar blocks / 0 schedule / 0 events，与启动快照完全相同 |
| 前端独立启动 | Vite 本地 5175 端口返回 HTML HTTP 200；它不是联调证明，前后端联调由上述浏览器测试单独启动配套代理完成 |

隔离方式：`/private/tmp/studyflow-sept5-clean.reNiuD` 中新建 venv，用 `git archive HEAD`
导出无 `.venv`/`node_modules` 的源代码，再覆盖本轮修改的代码和测试；不修改现有开发环境。
从声明的 requirements 和 frontend lockfile 安装，未依赖开发 venv 的已安装包。
在本机允许的网络/本地端口权限下安装成功；没有被网络限制跳过安装或启动。

实测工具：Python 3.12.14、Node 24.19.0、npm 11.6.0；FastAPI 0.141.1、
Pydantic 2.13.5、httpx 0.28.1、pytest 8.4.2、Uvicorn 0.52.4、boto3 1.43.89。
浏览器用可用的 Playwright 1.62.1 runtime，并在隔离目录下载 Chromium 151.0.7922.34。
仓库目前没有把 Playwright 声明为 frontend 依赖，所以 README 明确给出可选安装命令；
此次没有改变 D 的 package.json/lockfile。Python 依赖仍是已有兼容范围，并未新增锁文件。
两个警告来自 Starlette/httpx TestClient 和 AnyIO 旧别名，不影响本次结果；freeze 时不为
消除警告额外引入新 HTTP SDK。

覆盖来源：

- `tests/test_september4_integration.py`：三类新增、deadline 部分成功、要求重拆保留
  completed、未知/重复/非法输入、异常 Agent/运行失败回滚、错误 reset fixture、生产禁用、
  health/OpenAPI/CORS preflight；继续全部运行，没有替换成仅 happy path 的 smoke。
- `tests/test_replan_acceptance.py`：统一 `data/scenarios/replan_acceptance.json`，
  missed 多层依赖、日历变化、completed/无关保留、无效 Scheduler 输出回滚。
- 新日期矩阵：provider mocks + 默认动态 pipeline，每个时刻三轮复演，新增排期不早于
  注入的观察时间，五集合逐项相等；另测**五集合均非空**的启动基线 reset。
- 浏览器 13 项覆盖现有 Complete/Missed/Calendar/Preserved/跨日/失败恢复及正常实时时钟。
  **并未验证尚未接入的 reset/Assessment UI 控件**，不能冒充 D 或四人人工签收。

## 4. 演示日期与时钟方案

默认 provider fixtures 的 midterm、presentation、coding deadline 分别是
9 月 10 日 14:00、9 月 12 日 16:00、9 月 14 日 23:59（+08:00）。
9 月 5、6 日在 08:00 / 14:00 / 23:00 均可完成初次 Plan，**没有调整 fixture/ID**。
正常 `/plan` 继续读取当次 Singapore 当前时间，晚于学习窗口则排到下一有效日期；
因此 9 月 6 日深夜 Today’s Plan 为空不等于失败，应查看完整跨日排期。

`data/scenarios/replan_acceptance.json` 是 9 月 3 日历史验收，不作为当日产品时钟。
`create_app(clock=...)` 仅用于注入式测试。此次没有新增生产冻结时钟环境变量。

为了无需等任务自然到期就演示“错过之后移动”，`demo_check` 把 missed 观察时间明确模拟为
选中任务原 end_time 之后 5 分钟，并打印 `simulated_missed_at`。本机实测是
`2026-09-06T15:35:00+08:00`。这只设置该条事件的观察时间，不修改系统时间或正常 `/plan`。
该检查完成后必 reset；录制若采用模拟观察，讲解中同样明确说明。真实 UI 事件继续使用
当前时间，不承诺点击“Missed”必定把尚未开始的未来任务移到另一个时间。

## 5. 9 月 6 日可执行本地演示方案

首选本地 mock + 无 LLM 凭据，不要求部署外网。

1. 团队合入后在冻结版本确认分支和工作区，在线完成 README 的 Python venv、`npm ci`、
   可选浏览器依赖安装；不要录制开始才安装。保存当日 commit ID 和测试结果。
2. 两个终端按第 2 节启动 demo API 和前端。使用一个 worker，不带 `--reload`，
   不启动第二个共享 demo 后端。打开 UI、`/docs` 和后端日志。
3. `curl http://127.0.0.1:8000/health` 应为 `{"status":"ok","data_mode":"mock"}`；
   `/openapi.json` 应包含 `/demo/reset` 和 `/assessment-changes`。
4. 在**可清空的演示进程**运行以下检查；它会清除现有演示进度，最终回到启动状态：

   ```bash
   python -m backend.demo_check --base-url http://127.0.0.1:8000 --allow-reset
   ```

5. 主录制从 UI Generate Plan 开始；Complete → Missed → 日历新增/修改 → 展示
   Moved/Preserved/Unscheduled 与跨日排期。用后台 GET/写响应核对，不用第二次 Plan 刷新。
6. D 控件已完成则在 UI 演示新增/更新和 reset；未完成则在 `/docs` 的 Try it out 或第 2 节
   curl 展示真实后端操作，刷新 UI，并明确这部分 UI 待接入。deadline 09:01 的例子展示
   无法排期，而不是错误地展示全部成功。
7. reset 成功后五集合刷新，重新 Generate Plan，确认能复演；由 A/B/C/D 各自确认后录制备份视频。

Fallback：

- 无网/无凭据：预先装好依赖；启动时指定 `STUDYFLOW_LLM_PROVIDER=none`，运行全链路 mock。
  重启会恢复启动状态，须提醒观众/操作者进度不持久保存。
- 已启用 Bedrock但请求失败/结构不合法：现有 A 逻辑校验并回退模板；不要编造缺失要求。
  为避免现场等待网络超时，主录制直接用 `none`；没有真实模型调用也要如实标注。
- 页面操作未完成：保留上述 API 演示通路，不把 API 验收写成完整 UI 验收。
- 服务启动失败：按 README 查 venv/端口/配置；保留当前可工作的 venv 和离线依赖，
  不在现场切数据库、OAuth 或新增云服务。依赖下载需要事先联网，离线模式不等于离线安装。

如果团队坚持部署：先另行确认平台、精确前端来源/代理、HTTPS、是否开放 demo reset 和
无鉴权风险；本轮只交付 localhost 方案，**没有实际发布或验证云部署**。

## 6. 可直接放进 PPT 的内容

### Slide 1 — 系统架构：从考核到可执行计划

```text
Canvas-shaped mocks / Calendar-shaped mocks
                   ↓ 边界规范化
React Dashboard → FastAPI → 五个 canonical Pydantic models
                   ↓
      PlanningState 原子事务 → PlanningPipeline
                               ├─ A：分类、任务拆解、影响分析
                               └─ B：依赖、deadline、hard 日历约束排期
                   ↓ 校验并整体保存
      Assessment / Task / CalendarBlock / ScheduledTask / PlanningEvent
                   ↓
          完整结果 + 未排期原因 → Dashboard
```

讲解：用户完成/错过任务或修改考核/日历触发重新计划。当前是用户显式观察，不是后台自动
监测现实中的任务完成。保留 completed 和无关有效安排；失败不能留下半更新状态。

### Slide 2 — 技术栈与可靠性

- Python 3.12 / FastAPI / Pydantic v2 / Uvicorn；React 19 / TypeScript / Vite。
- 五个共享模型；provider 数据在边界规范化，业务不依赖供应商 payload。
- 单进程内存状态、事务锁、提交前引用/依赖/排期校验；不声称有数据库持久化。
- 422 非法输入，409 重复/冲突，500 失败回滚；200 可为带原因的部分排期。
- Sept 5 自动验证：460 后端、8 前端单元、13 浏览器；生产构建通过。

### Slide 3 — 启动与演示恢复

- 本机两个服务：API 8000，UI 5173，经 `/api` 代理联通；一个 worker。
- mock 运行无需 Canvas/Google OAuth 或 LLM 凭据。
- Demo reset 独立入口，需 demo 环境 + 显式开关，恢复启动五集合；不是 Regenerate Plan。
- 9 月 5–6 日可按真实当前时间排期；晚间显示跨日计划，不通过篡改产品时钟制造结果。

### Slide 4 — Fallback 与范围诚实

- 主演示选择确定性模板；模型接入为可选模块，非法输出先验证再 fallback。
- 信息不全不编造考核要求；排不下显示明确原因，不静默丢弃。
- 无真实 Calendar 写回、无多用户/持久化、无本轮云部署。
- UI 新入口仍待 D 联调；后端有 API 操作与三轮 reset/replay 作为演示备用路径。

## 7. 待团队确认，不阻塞 C 交付

- D：接入 reset 确认/互斥/刷新/失败恢复和最小 Assessment 表单；沿用现有 client，
  用共同验收 fixture 和上面的日期样例增加 UI 自动测试/人工验收。当前 Preserved 已存在。
- A/B：确认保守的要求变更 409 规则；主录制选择哪个任务和观察时间能清楚展示下游移动。
  不把过早的 missed 事件误判为 Scheduler 没移动的 bug。
- D/展示负责人：选定真实当前观察还是显式模拟观察，录制前核对跨日视图；Agent 原因仍在
  后端日志，不假设 API 已增加原因字段。
- 全体：确认冻结 commit、本地演示可接受、PPT/视频担当及人工签收；若要外网另行评估。
- C：本轮已完成后端和干净启动证据，未尝试新的真实 Google Calendar/OAuth/LLM 请求，
  未改变 shared schemas、fixtures、默认时钟或现有 response shape。

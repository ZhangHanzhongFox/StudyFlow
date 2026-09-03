import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  CalendarPlus,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Code2,
  Presentation,
  RefreshCw,
  RotateCcw,
  Sparkles,
  TriangleAlert,
  WandSparkles,
  XCircle,
} from "lucide-react";
import {
  ApiError,
  changeCalendar,
  compareSchedules,
  generatePlan,
  getDashboardData,
  replan,
} from "./api";
import type {
  Assessment,
  CalendarChangeRequest,
  PlanningEvent,
  ScheduledTask,
  SchedulingResult,
  Task,
} from "./types";

type DashboardData = Awaited<ReturnType<typeof getDashboardData>>;

const typeLabels: Record<Assessment["type"], string> = {
  presentation: "Presentation",
  exam: "Exam",
  midterm: "Midterm",
  coding_assignment: "Coding assignment",
  quiz: "Quiz",
};

const eventCopy: Record<PlanningEvent["event_type"], { label: string; detail: string }> = {
  task_completed: { label: "Task completed", detail: "Progress observed and plan updated" },
  task_missed: { label: "Task missed", detail: "Schedule impact detected" },
  new_assessment: { label: "Assessment added", detail: "New deadline entered the plan" },
  assessment_updated: { label: "Assessment updated", detail: "Requirements were reviewed" },
  calendar_changed: { label: "Calendar changed", detail: "Availability was re-evaluated" },
};

function sameLocalDay(left: Date, right: Date) {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate();
}

function relativeDeadline(deadline: string, now: Date) {
  const days = Math.ceil((new Date(deadline).getTime() - now.getTime()) / 86_400_000);
  if (days < 0) return "Past due";
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `${days} days left`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function formatEventTime(value: string, now: Date) {
  const date = new Date(value);
  if (sameLocalDay(date, now)) return `Today, ${formatTime(value)}`;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

function formatScheduleDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function eventId(prefix: string) {
  const unique = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `event-${prefix}-${unique}`;
}

function calendarId() {
  const unique = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `calendar-${unique}`;
}

function apiErrorMessage(reason: unknown) {
  if (reason instanceof ApiError) return `${reason.message} (${reason.code})`;
  return "The API could not be reached. Your existing plan has not been replaced.";
}

type OperationState = "idle" | "loading" | "success" | "error" | "refresh_error";

interface ScheduleChanges {
  added: ScheduledTask[];
  removed: ScheduledTask[];
  moved: Array<{ before: ScheduledTask; after: ScheduledTask }>;
  trigger: string;
}

function TypeIcon({ type }: { type: Assessment["type"] }) {
  if (type === "presentation") return <Presentation size={19} />;
  if (type === "coding_assignment") return <Code2 size={19} />;
  return <BookOpen size={19} />;
}

function LoadingState() {
  return (
    <div className="dashboard-grid" aria-label="Loading dashboard">
      {[0, 1, 2].map((column) => (
        <section className="panel skeleton-panel" key={column}>
          <div className="skeleton skeleton-title" />
          {[0, 1, 2].map((row) => <div className="skeleton skeleton-row" key={row} />)}
        </section>
      ))}
    </div>
  );
}

function EmptyState({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return (
    <div className="empty-state">
      <span className="empty-icon">{icon}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}

export default function App() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [planState, setPlanState] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [planError, setPlanError] = useState<string | null>(null);
  const [planResult, setPlanResult] = useState<SchedulingResult | null>(null);
  const [changeSummary, setChangeSummary] = useState<string | null>(null);
  const [operationState, setOperationState] = useState<OperationState>("idle");
  const [operationMessage, setOperationMessage] = useState<string | null>(null);
  const [operationResult, setOperationResult] = useState<SchedulingResult | null>(null);
  const [scheduleChanges, setScheduleChanges] = useState<ScheduleChanges | null>(null);
  const [pendingRefresh, setPendingRefresh] = useState<{
    result: SchedulingResult;
    before: ScheduledTask[];
    trigger: string;
  } | null>(null);
  const [pendingAction, setPendingAction] = useState<{
    request: PlanningEvent | CalendarChangeRequest;
    trigger: string;
    before: ScheduledTask[];
  } | null>(null);
  const [calendarSelection, setCalendarSelection] = useState("new");
  const [calendarTitle, setCalendarTitle] = useState("");
  const [calendarStart, setCalendarStart] = useState("");
  const [calendarEnd, setCalendarEnd] = useState("");
  const [calendarFlexibility, setCalendarFlexibility] = useState<"hard" | "soft" | "flexible">("hard");
  const now = useMemo(() => new Date(), []);

  const load = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getDashboardData(controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("We couldn’t reach the StudyFlow API. Check that the backend is running, then try again.");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  useEffect(() => load(), [load]);

  const upcoming = useMemo(
    () => [...(data?.assessments ?? [])]
      .filter((assessment) => new Date(assessment.deadline) >= now)
      .sort((a, b) => new Date(a.deadline).getTime() - new Date(b.deadline).getTime()),
    [data, now],
  );
  const todaysPlan = useMemo(
    () => [...(data?.schedule ?? [])]
      .filter((task) => sameLocalDay(new Date(task.start_time), now))
      .sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()),
    [data, now],
  );
  const activity = useMemo(
    () => [...(data?.planningEvents ?? [])]
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()),
    [data],
  );
  const tasksById = useMemo(
    () => new Map((data?.tasks ?? []).map((task) => [task.id, task])),
    [data],
  );
  const operationLoading = operationState === "loading";

  const applyPlanningResult = useCallback(async (
    result: SchedulingResult,
    before: ScheduledTask[],
    trigger: string,
  ) => {
    try {
      const controller = new AbortController();
      const refreshed = await getDashboardData(controller.signal);
      const comparison = compareSchedules(before, result.scheduled_tasks);
      const previousByTask = new Map(before.map((item) => [item.task_id, item]));

      setData(refreshed);
      setOperationResult(result);
      setScheduleChanges({
        ...comparison,
        moved: comparison.moved.flatMap((after) => {
          const previous = previousByTask.get(after.task_id);
          return previous ? [{ before: previous, after }] : [];
        }),
        trigger,
      });
      setOperationMessage(
        `${comparison.moved.length} moved · ${comparison.added.length} added · ${comparison.removed.length} removed`,
      );
      setPendingRefresh(null);
      setPendingAction(null);
      setOperationState("success");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setOperationResult(result);
      setPendingRefresh({ result, before, trigger });
      setOperationMessage("The change was saved, but the latest dashboard state could not be refreshed.");
      setOperationState("refresh_error");
    }
  }, []);

  const submitPlanningAction = useCallback(async (
    request: PlanningEvent | CalendarChangeRequest,
    trigger: string,
  ) => {
    if (!data || operationLoading) return;

    const before = data.schedule;
    const controller = new AbortController();
    setOperationState("loading");
    setOperationMessage(trigger);
    setPendingRefresh(null);
    setPendingAction({ request, trigger, before });
    setOperationResult(null);
    setScheduleChanges(null);

    try {
      const result = "calendar_block" in request
        ? await changeCalendar(request, controller.signal)
        : await replan(request, controller.signal);
      await applyPlanningResult(result, before, trigger);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setOperationMessage(apiErrorMessage(reason));
      setOperationState("error");
    }
  }, [applyPlanningResult, data, operationLoading]);

  const retryPendingAction = useCallback(async () => {
    if (!pendingAction || operationLoading) return;
    const controller = new AbortController();
    const submittedEvent = "calendar_block" in pendingAction.request
      ? pendingAction.request.event
      : pendingAction.request;
    setOperationState("loading");
    setOperationMessage("Checking whether the previous submission was already saved…");

    try {
      const refreshed = await getDashboardData(controller.signal);
      const alreadySaved = refreshed.planningEvents.some((event) => event.id === submittedEvent.id);
      if (!alreadySaved) {
        setOperationState("idle");
        await submitPlanningAction(pendingAction.request, pendingAction.trigger);
        return;
      }

      const comparison = compareSchedules(pendingAction.before, refreshed.schedule);
      const previousByTask = new Map(pendingAction.before.map((item) => [item.task_id, item]));
      setData(refreshed);
      setScheduleChanges({
        ...comparison,
        moved: comparison.moved.flatMap((after) => {
          const previous = previousByTask.get(after.task_id);
          return previous ? [{ before: previous, after }] : [];
        }),
        trigger: pendingAction.trigger,
      });
      setOperationResult(null);
      setOperationMessage("The original action was already saved; the dashboard is now refreshed. Its one-time unscheduled result is no longer available.");
      setPendingAction(null);
      setOperationState("success");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setOperationMessage("Could not verify the previous submission. Nothing was submitted again; retry this check safely.");
      setOperationState("error");
    }
  }, [operationLoading, pendingAction, submitPlanningAction]);

  const handleTaskAction = useCallback((task: Task, action: "task_completed" | "task_missed") => {
    const event: PlanningEvent = {
      id: eventId(action === "task_missed" ? "task-missed" : "task-completed"),
      event_type: action,
      timestamp: new Date().toISOString(),
      reference_id: task.id,
    };
    void submitPlanningAction(
      event,
      action === "task_missed" ? `${task.name} was marked missed` : `${task.name} was completed`,
    );
  }, [submitPlanningAction]);

  const handleCalendarSelection = useCallback((value: string) => {
    setCalendarSelection(value);
    const block = data?.calendarBlocks.find((item) => item.id === value);
    if (!block) {
      setCalendarTitle("");
      setCalendarStart("");
      setCalendarEnd("");
      setCalendarFlexibility("hard");
      return;
    }
    const toLocalInput = (iso: string) => {
      const date = new Date(iso);
      const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
      return local.toISOString().slice(0, 16);
    };
    setCalendarTitle(block.title);
    setCalendarStart(toLocalInput(block.start_time));
    setCalendarEnd(toLocalInput(block.end_time));
    setCalendarFlexibility(block.flexibility);
  }, [data]);

  const handleCalendarSubmit = useCallback((formEvent: React.FormEvent) => {
    formEvent.preventDefault();
    if (!calendarTitle.trim() || !calendarStart || !calendarEnd) return;

    const blockId = calendarSelection === "new" ? calendarId() : calendarSelection;
    const event: PlanningEvent & { event_type: "calendar_changed" } = {
      id: eventId("calendar-changed"),
      event_type: "calendar_changed",
      timestamp: new Date().toISOString(),
      reference_id: blockId,
    };
    const change: CalendarChangeRequest = {
      event,
      calendar_block: {
        id: blockId,
        title: calendarTitle.trim(),
        start_time: new Date(calendarStart).toISOString(),
        end_time: new Date(calendarEnd).toISOString(),
        flexibility: calendarFlexibility,
      },
    };
    void submitPlanningAction(change, `${calendarTitle.trim()} changed the calendar`);
  }, [calendarEnd, calendarFlexibility, calendarSelection, calendarStart, calendarTitle, submitPlanningAction]);

  const handleGeneratePlan = useCallback(async () => {
    const controller = new AbortController();
    const previousSchedule = new Map(
      (data?.schedule ?? []).map((task) => [task.task_id, task]),
    );

    setPlanState("loading");
    setPlanError(null);
    setChangeSummary(null);

    try {
      const result = await generatePlan(controller.signal);
      const refreshed = await getDashboardData(controller.signal);
      const latestSchedule = new Map(
        refreshed.schedule.map((task) => [task.task_id, task]),
      );
      const added = refreshed.schedule.filter((task) => !previousSchedule.has(task.task_id)).length;
      const moved = refreshed.schedule.filter((task) => {
        const previous = previousSchedule.get(task.task_id);
        return previous
          && (previous.start_time !== task.start_time || previous.end_time !== task.end_time);
      }).length;
      const removed = [...previousSchedule.keys()].filter((taskId) => !latestSchedule.has(taskId)).length;

      setData(refreshed);
      setPlanResult(result);
      setChangeSummary(
        `${refreshed.schedule.length} scheduled · ${added} added · ${moved} moved · ${removed} removed`,
      );
      setPlanState("success");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setPlanError("StudyFlow couldn’t generate and refresh the plan. Check the API, then retry.");
      setPlanState("error");
    }
  }, [data]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="StudyFlow home">
          <span className="brand-mark"><Sparkles size={19} /></span>
          <span>StudyFlow</span>
        </a>
        <div className="agent-status"><span /> Agent active</div>
      </header>

      <main id="top">
        <div className="intro">
          <div>
            <p className="eyebrow">{new Intl.DateTimeFormat(undefined, { weekday: "long" }).format(now)} · Your adaptive study workspace</p>
            <h1>Your study day, made clear.</h1>
            <p>Your plan is balanced. Here’s what the agent is watching today.</p>
          </div>
          <div className="intro-actions">
            <div className="loop-card" aria-label="StudyFlow agent loop">
              <span>Plan</span><ArrowRight size={14} /><span>Act</span><ArrowRight size={14} />
              <span>Observe</span><ArrowRight size={14} /><strong>Replan</strong>
            </div>
            <button
              className="generate-button"
              type="button"
              onClick={handleGeneratePlan}
              disabled={planState === "loading" || loading || Boolean(error)}
            >
              {planState === "loading" ? <RefreshCw className="spin" size={16} /> : <WandSparkles size={16} />}
              {planState === "loading" ? "Generating…" : planState === "success" ? "Generate again" : "Generate Plan"}
            </button>
          </div>
        </div>

        <section className={`change-notice ${planState}`} aria-live="polite">
          <span className="change-notice-icon">
            {planState === "error" ? <TriangleAlert size={18} /> : planState === "loading" ? <RefreshCw className="spin" size={18} /> : <RotateCcw size={18} />}
          </span>
          <div>
            <strong>{planState === "success" ? "Plan updated" : planState === "error" ? "Plan update failed" : planState === "loading" ? "Agent is generating your plan" : "Plan changes"}</strong>
            <p>
              {planState === "success" && changeSummary
                ? changeSummary
                : planState === "error"
                  ? planError
                  : planState === "loading"
                    ? "Tasks, dependencies, and available time are being evaluated."
                    : "Generate a plan to see scheduled, moved, and unscheduled work here."}
            </p>
          </div>
          {planState === "error" && (
            <button type="button" onClick={handleGeneratePlan}><RefreshCw size={14} /> Retry</button>
          )}
        </section>

        {data && (
          <section className={`replan-notice ${operationState}`} aria-live="polite">
            <div className="replan-notice-heading">
              <span className="change-notice-icon">
                {operationState === "loading" ? <RefreshCw className="spin" size={18} /> : operationState === "error" || operationState === "refresh_error" ? <TriangleAlert size={18} /> : <RotateCcw size={18} />}
              </span>
              <div>
                <strong>{operationState === "loading" ? "Replanning…" : operationState === "success" ? "Replan complete" : operationState === "error" ? "Replan failed" : operationState === "refresh_error" ? "Saved — refresh needed" : "Replan activity"}</strong>
                <p>{operationMessage ?? "Complete, miss, or change a calendar block to see exactly what moves."}</p>
              </div>
              {operationState === "refresh_error" && pendingRefresh && (
                <button type="button" onClick={() => void applyPlanningResult(pendingRefresh.result, pendingRefresh.before, pendingRefresh.trigger)}>
                  <RefreshCw size={14} /> Retry refresh
                </button>
              )}
              {operationState === "error" && pendingAction && (
                <button type="button" onClick={() => void retryPendingAction()}>
                  <RefreshCw size={14} /> Retry action
                </button>
              )}
            </div>
            {scheduleChanges && operationState === "success" && (
              <div className="schedule-changes">
                {scheduleChanges.moved.map(({ before, after }) => (
                  <article key={`moved-${after.task_id}`}>
                    <span className="change-kind">Moved</span>
                    <strong>{tasksById.get(after.task_id)?.name ?? "Task details unavailable"}</strong>
                    <p><del>{formatScheduleDateTime(before.start_time)}–{formatTime(before.end_time)}</del><ArrowRight size={13} /><ins>{formatScheduleDateTime(after.start_time)}–{formatTime(after.end_time)}</ins></p>
                    <small>Triggered by: {scheduleChanges.trigger}</small>
                  </article>
                ))}
                {scheduleChanges.added.map((item) => (
                  <article key={`added-${item.task_id}`}>
                    <span className="change-kind added">Added</span>
                    <strong>{tasksById.get(item.task_id)?.name ?? "Task details unavailable"}</strong>
                    <p>{formatScheduleDateTime(item.start_time)}–{formatTime(item.end_time)}</p>
                  </article>
                ))}
                {scheduleChanges.removed.map((item) => (
                  <article key={`removed-${item.task_id}`}>
                    <span className="change-kind removed">Removed</span>
                    <strong>{tasksById.get(item.task_id)?.name ?? "Task details unavailable"}</strong>
                    <p>Previous slot: {formatScheduleDateTime(item.start_time)}–{formatTime(item.end_time)}</p>
                  </article>
                ))}
                {scheduleChanges.moved.length === 0 && scheduleChanges.added.length === 0 && scheduleChanges.removed.length === 0 && (
                  <p className="no-schedule-changes">No schedule slots needed to move. Task, calendar, and activity state were still refreshed.</p>
                )}
              </div>
            )}
            {operationResult && operationResult.unscheduled_tasks.length > 0 && (
              <div className="operation-failures">
                <strong><TriangleAlert size={15} /> {operationResult.unscheduled_tasks.length} task(s) could not be scheduled</strong>
                {operationResult.unscheduled_tasks.map((failure) => (
                  <article key={failure.task_id}>
                    <b>{tasksById.get(failure.task_id)?.name ?? "Task details unavailable"}</b>
                    <span>{failure.reason.replaceAll("_", " ")}</span>
                    <p>{failure.message}</p>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {data && (
          <details className="action-drawer">
            <summary><CalendarPlus size={17} /> Add or edit calendar block</summary>
            <div className="calendar-editor">
              <form onSubmit={handleCalendarSubmit}>
                <label>Calendar entry<select value={calendarSelection} onChange={(event) => handleCalendarSelection(event.target.value)} disabled={operationLoading}>
                  <option value="new">New calendar block</option>
                  {data.calendarBlocks.map((block) => <option key={block.id} value={block.id}>{block.title}</option>)}
                </select></label>
                <label>Title<input required value={calendarTitle} onChange={(event) => setCalendarTitle(event.target.value)} placeholder="Extra lecture" disabled={operationLoading} /></label>
                <div className="calendar-time-fields">
                  <label>Starts<input required type="datetime-local" value={calendarStart} onChange={(event) => setCalendarStart(event.target.value)} disabled={operationLoading} /></label>
                  <label>Ends<input required type="datetime-local" value={calendarEnd} onChange={(event) => setCalendarEnd(event.target.value)} disabled={operationLoading} /></label>
                </div>
                <label>Flexibility<select value={calendarFlexibility} onChange={(event) => setCalendarFlexibility(event.target.value as "hard" | "soft" | "flexible")} disabled={operationLoading}>
                  <option value="hard">Hard — cannot move</option><option value="soft">Soft</option><option value="flexible">Flexible</option>
                </select></label>
                <button className="calendar-submit" type="submit" disabled={operationLoading || !calendarTitle.trim() || !calendarStart || !calendarEnd}>
                  {operationLoading ? <RefreshCw className="spin" size={15} /> : <CalendarPlus size={15} />}{calendarSelection === "new" ? "Add & replan" : "Update & replan"}
                </button>
              </form>
              <div className="calendar-list"><strong>Current calendar</strong>{data.calendarBlocks.map((block) => <button type="button" key={block.id} onClick={() => handleCalendarSelection(block.id)}><span>{block.title}</span><small>{formatScheduleDateTime(block.start_time)} · {block.flexibility}</small></button>)}</div>
            </div>
          </details>
        )}

        {loading && !data ? <LoadingState /> : error ? (
          <div className="error-state" role="alert">
            <span><TriangleAlert size={24} /></span>
            <div><strong>Dashboard unavailable</strong><p>{error}</p></div>
            <button type="button" onClick={load}><RefreshCw size={16} /> Try again</button>
          </div>
        ) : data ? (
          <div className="dashboard-grid">
            <section className="panel assessments-panel">
              <div className="section-heading">
                <div><span className="section-icon green"><CalendarDays size={18} /></span><h2>Upcoming Assessments</h2></div>
                <span className="count">{upcoming.length}</span>
              </div>
              <p className="section-subtitle">Deadlines the agent is planning toward</p>
              <div className="card-list">
                {upcoming.length === 0 ? (
                  <EmptyState icon={<CheckCircle2 size={22} />} title="All clear" detail="No upcoming assessments right now." />
                ) : upcoming.map((assessment) => (
                  <article className="assessment-card" key={assessment.id}>
                    <div className={`type-icon ${assessment.type}`}><TypeIcon type={assessment.type} /></div>
                    <div className="assessment-copy">
                      <div className="meta-row"><span>{assessment.course_code}</span><span>·</span><span>{typeLabels[assessment.type]}</span></div>
                      <h3>{assessment.title}</h3>
                      <div className="deadline-row">
                        <span>{new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(assessment.deadline))}</span>
                        <span className="deadline-pill">{relativeDeadline(assessment.deadline, now)}</span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel plan-panel">
              <div className="section-heading">
                <div><span className="section-icon amber"><Clock3 size={18} /></span><h2>Today’s Plan</h2></div>
                <span className="count">{todaysPlan.length}</span>
              </div>
              <p className="section-subtitle">Focused work fitted around your commitments</p>
              <div className="timeline">
                {todaysPlan.length === 0 ? (
                  <EmptyState icon={<Clock3 size={22} />} title="No sessions today" detail="Your schedule is open for the day." />
                ) : todaysPlan.map((task, index) => (
                  <article className="timeline-item" key={task.id}>
                    <div className="time-column"><strong>{formatTime(task.start_time)}</strong><span>{formatTime(task.end_time)}</span></div>
                    <div className="timeline-rail"><span className={index === 0 ? "current" : ""} /></div>
                    <div className="task-copy">
                      <h3>{tasksById.get(task.task_id)?.name ?? "Task details unavailable"}</h3>
                      <div className="task-meta"><span className={`flexibility ${task.flexibility}`}>{task.flexibility}</span><span className={`task-status ${tasksById.get(task.task_id)?.status ?? "pending"}`}>{tasksById.get(task.task_id)?.status ?? "pending"}</span></div>
                    </div>
                  </article>
                ))}
              </div>
              {planResult && planResult.unscheduled_tasks.length > 0 && (
                <div className="unscheduled-section" role="status">
                  <div className="unscheduled-heading">
                    <TriangleAlert size={16} />
                    <h3>Needs scheduling attention</h3>
                    <span>{planResult.unscheduled_tasks.length}</span>
                  </div>
                  <div className="unscheduled-list">
                    {planResult.unscheduled_tasks.map((failure) => (
                      <article key={failure.task_id}>
                        <strong>{tasksById.get(failure.task_id)?.name ?? "Task details unavailable"}</strong>
                        <span>{failure.reason.replaceAll("_", " ")}</span>
                        <p>{failure.message}</p>
                      </article>
                    ))}
                  </div>
                </div>
              )}
              <details className="task-actions">
                <summary>Task status & actions <span>{data.tasks.length}</span></summary>
                <div className="task-action-list">
                  {data.tasks.map((task) => (
                    <article key={task.id}>
                      <div><strong>{task.name}</strong><span className={`task-status ${task.status}`}>{task.status.replaceAll("_", " ")}</span></div>
                      <div className="task-buttons">
                        <button type="button" onClick={() => handleTaskAction(task, "task_completed")} disabled={operationLoading || task.status === "completed"}><CheckCircle2 size={13} /> Complete</button>
                        <button className="missed" type="button" onClick={() => handleTaskAction(task, "task_missed")} disabled={operationLoading || task.status === "completed" || task.status === "missed"}><XCircle size={13} /> Missed</button>
                      </div>
                    </article>
                  ))}
                </div>
              </details>
            </section>

            <section className="panel activity-panel">
              <div className="section-heading">
                <div><span className="section-icon violet"><Sparkles size={18} /></span><h2>Agent Activity</h2></div>
                <span className="live-dot" title="Live" />
              </div>
              <p className="section-subtitle">How your plan adapts as circumstances change</p>
              <div className="activity-list">
                {activity.length === 0 ? (
                  <EmptyState icon={<Sparkles size={22} />} title="Nothing to report" detail="Agent observations will appear here." />
                ) : activity.map((event) => (
                  <article className={`activity-item ${event.event_type}`} key={event.id}>
                    <span className="activity-marker" />
                    <div><h3>{eventCopy[event.event_type].label}</h3><p>{eventCopy[event.event_type].detail}</p><time>{formatEventTime(event.timestamp, now)}</time></div>
                  </article>
                ))}
              </div>
            </section>
          </div>
        ) : null}
      </main>
      <footer>StudyFlow observes your progress and protects every deadline.</footer>
    </div>
  );
}

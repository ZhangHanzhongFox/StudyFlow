import type {
  Assessment,
  CalendarBlock,
  CalendarChangeRequest,
  PlanningEvent,
  ScheduledTask,
  SchedulingResult,
  Task,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson<T>(
  path: string,
  signal: AbortSignal,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const validationMessage = Array.isArray(detail)
      ? detail.map((issue) => {
        const location = Array.isArray(issue?.loc) ? issue.loc.join(".") : "";
        return typeof issue?.msg === "string" ? `${location ? `${location}: ` : ""}${issue.msg}` : "";
      }).filter(Boolean).join("; ")
      : "";
    throw new ApiError(
      response.status,
      detail?.code ?? (response.status === 422 ? "validation_error" : "request_failed"),
      validationMessage || detail?.message || (typeof detail === "string" ? detail : `Request failed with status ${response.status}`),
    );
  }
  return response.json() as Promise<T>;
}

export async function getDashboardData(signal: AbortSignal) {
  const [assessments, tasks, schedule, planningEvents, calendarBlocks] = await Promise.all([
    requestJson<Assessment[]>("/assessments", signal),
    requestJson<Task[]>("/tasks", signal),
    requestJson<ScheduledTask[]>("/schedule", signal),
    requestJson<PlanningEvent[]>("/planning-events", signal),
    requestJson<CalendarBlock[]>("/calendar-blocks", signal),
  ]);

  return { assessments, tasks, schedule, planningEvents, calendarBlocks };
}

export function generatePlan(signal: AbortSignal): Promise<SchedulingResult> {
  return requestJson<SchedulingResult>("/plan", signal, { method: "POST" });
}

// D: use the shared operation lock and confirmation before resetting.
// A 404 means the server has not enabled this demo-only capability.
export function resetDemo(signal: AbortSignal): Promise<{ status: string }> {
  return requestJson("/demo/reset", signal, { method: "POST" });
}

export function changeAssessment(
  change: { event: PlanningEvent; assessment: Assessment },
  signal: AbortSignal,
): Promise<SchedulingResult> {
  return requestJson("/assessment-changes", signal, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(change),
  });
}

// Submit each observation once. Do not first POST it to /planning-events.
export function replan(event: PlanningEvent, signal: AbortSignal): Promise<SchedulingResult> {
  return requestJson<SchedulingResult>("/replan", signal, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(event),
  });
}

export function changeCalendar(
  change: CalendarChangeRequest,
  signal: AbortSignal,
): Promise<SchedulingResult> {
  return requestJson<SchedulingResult>("/calendar-changes", signal, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(change),
  });
}

export function compareSchedules(before: ScheduledTask[], after: ScheduledTask[]) {
  const previous = new Map(before.map((item) => [item.task_id, item]));
  const latest = new Map(after.map((item) => [item.task_id, item]));
  const unchanged = (old: ScheduledTask, item: ScheduledTask) =>
    Date.parse(old.start_time) === Date.parse(item.start_time)
    && Date.parse(old.end_time) === Date.parse(item.end_time)
    && old.flexibility === item.flexibility;
  return {
    added: after.filter((item) => !previous.has(item.task_id)),
    moved: after.filter((item) => {
      const old = previous.get(item.task_id);
      return old && !unchanged(old, item);
    }),
    preserved: after.filter((item) => {
      const old = previous.get(item.task_id);
      return old && unchanged(old, item);
    }),
    removed: before.filter((item) => !latest.has(item.task_id)),
  };
}

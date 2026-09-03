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
    throw new ApiError(
      response.status,
      detail?.code ?? (response.status === 422 ? "validation_error" : "request_failed"),
      detail?.message ?? `Request failed with status ${response.status}`,
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
  return {
    added: after.filter((item) => !previous.has(item.task_id)),
    moved: after.filter((item) => {
      const old = previous.get(item.task_id);
      return old && (Date.parse(old.start_time) !== Date.parse(item.start_time)
        || Date.parse(old.end_time) !== Date.parse(item.end_time));
    }),
    removed: before.filter((item) => !latest.has(item.task_id)),
  };
}

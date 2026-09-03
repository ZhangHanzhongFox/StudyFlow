import type {
  Assessment,
  PlanningEvent,
  ScheduledTask,
  SchedulingResult,
  Task,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

async function requestJson<T>(
  path: string,
  signal: AbortSignal,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, signal });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getDashboardData(signal: AbortSignal) {
  const [assessments, tasks, schedule, planningEvents] = await Promise.all([
    requestJson<Assessment[]>("/assessments", signal),
    requestJson<Task[]>("/tasks", signal),
    requestJson<ScheduledTask[]>("/schedule", signal),
    requestJson<PlanningEvent[]>("/planning-events", signal),
  ]);

  return { assessments, tasks, schedule, planningEvents };
}

export function generatePlan(signal: AbortSignal): Promise<SchedulingResult> {
  return requestJson<SchedulingResult>("/plan", signal, { method: "POST" });
}

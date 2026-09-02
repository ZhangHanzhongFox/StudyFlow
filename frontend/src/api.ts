import type { Assessment, PlanningEvent, ScheduledTask } from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { signal });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getDashboardData(signal: AbortSignal) {
  const [assessments, schedule, planningEvents] = await Promise.all([
    getJson<Assessment[]>("/assessments", signal),
    getJson<ScheduledTask[]>("/schedule", signal),
    getJson<PlanningEvent[]>("/planning-events", signal),
  ]);

  return { assessments, schedule, planningEvents };
}

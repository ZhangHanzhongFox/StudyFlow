import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Code2,
  Presentation,
  RefreshCw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { getDashboardData } from "./api";
import type { Assessment, PlanningEvent, ScheduledTask } from "./types";

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

function readableTaskId(taskId: string) {
  return taskId
    .replace(/^task-/, "")
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function formatEventTime(value: string, now: Date) {
  const date = new Date(value);
  if (sameLocalDay(date, now)) return `Today, ${formatTime(value)}`;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
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
          <div className="loop-card" aria-label="StudyFlow agent loop">
            <span>Plan</span><ArrowRight size={14} /><span>Act</span><ArrowRight size={14} />
            <span>Observe</span><ArrowRight size={14} /><strong>Replan</strong>
          </div>
        </div>

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
                    <div className="task-copy"><h3>{readableTaskId(task.task_id)}</h3><span className={`flexibility ${task.flexibility}`}>{task.flexibility}</span></div>
                  </article>
                ))}
              </div>
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

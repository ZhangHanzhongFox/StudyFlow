export type AssessmentType =
  | "presentation"
  | "exam"
  | "midterm"
  | "coding_assignment"
  | "quiz";

export interface Assessment {
  id: string;
  course_code: string;
  title: string;
  description: string;
  type: AssessmentType;
  unlock_at: string | null;
  deadline: string;
  weightage: number | null;
  is_group: boolean;
  group_size: number | null;
}

export interface ScheduledTask {
  id: string;
  task_id: string;
  start_time: string;
  end_time: string;
  flexibility: "hard" | "soft" | "flexible";
}

export type PlanningEventType =
  | "task_completed"
  | "task_missed"
  | "new_assessment"
  | "assessment_updated"
  | "calendar_changed";

export interface PlanningEvent {
  id: string;
  event_type: PlanningEventType;
  timestamp: string;
  reference_id: string;
}

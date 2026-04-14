// Types mirror the FastAPI backend dataclasses. Kept hand-written and
// narrow — only the fields the UI actually reads. Expand as needed.

export type CallOutcome =
  | "in_progress"
  | "no_answer"
  | "voicemail"
  | "transferred"
  | "callback_requested"
  | "wrong_number"
  | "disconnected"
  | "completed"
  | "failed"
  | "demo_scheduled"
  | "not_interested"
  | "gatekeeper_only";

export type CallStatus = "in_progress" | "called" | "failed";

export type CallDisposition =
  | "in_progress"
  | "transferred"
  | "voicemail_left"
  | "no_answer"
  | "hung_up"
  | "callback_requested"
  | "wrong_number"
  | "completed"
  | "disconnected_number"
  | "technical_error"
  | "demo_scheduled"
  | "not_interested"
  | "gatekeeper_only";

export interface TranscriptEntry {
  speaker: "ai" | "patient" | "system";
  text: string;
  timestamp: string;
}

export interface JudgeScores {
  opening_quality: number;
  discovery_quality: number;
  tool_use_correctness: number;
  objection_handling: number;
  closing_quality: number;
  overall: number;
}

export interface JudgeNotes {
  missed_opportunities: string[];
  ai_errors: string[];
  recommended_prompt_edits: string[];
}

export interface CapturedContact {
  name: string | null;
  title: string | null;
  email: string | null;
  phone: string | null;
}

export interface ObjectionEntry {
  objection: string;
  ai_response_quality: number;
}

export type GtmDisposition =
  | "meeting_booked"
  | "hot_lead_no_booking"
  | "warm_interest"
  | "qualifying_signal_no_commitment"
  | "not_now_try_later"
  | "budget_cycle_gate"
  | "wrong_target_path_captured"
  | "dead_end_at_firm"
  | "not_interested_polite"
  | "competing_solution_satisfied"
  | "do_not_recontact"
  | "bad_data"
  | "no_conversation"
  | "technical_failure"
  | "needs_human_review";

export interface CallLog {
  call_id: string;
  patient_id: string;
  patient_name: string;
  firm_name: string | null;
  phone: string;
  lead_state: string | null;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number;
  outcome: CallOutcome;
  call_status: CallStatus;
  call_disposition: CallDisposition;
  mock_mode: boolean;
  transcript: TranscriptEntry[];
  // Autocaller capture
  pain_point_summary: string | null;
  interest_level: number | null;
  is_decision_maker: boolean | null;
  was_gatekeeper: boolean;
  gatekeeper_contact: Record<string, string> | null;
  demo_booking_id: string | null;
  demo_scheduled_at: string | null;
  demo_meeting_url: string | null;
  followup_email_sent: boolean;
  // Recording
  recording_path: string | null;
  recording_duration_seconds: number | null;
  has_recording: boolean;
  // Error
  error_code: string | null;
  error_message: string | null;
  // Phase A: judge + GTM
  judge_score: number | null;
  judge_scores: JudgeScores | null;
  judge_notes: JudgeNotes | null;
  judged_at: string | null;
  prompt_version: string | null;
  prompt_text: string | null;
  tools_snapshot: unknown[] | null;
  gtm_disposition: GtmDisposition | null;
  follow_up_action: string | null;
  follow_up_when: string | null;
  follow_up_owner: string | null;
  follow_up_note: string | null;
  call_summary: string | null;
  signal_flags: string[] | null;
  pain_points_discussed: string[] | null;
  objections_raised: ObjectionEntry[] | null;
  captured_contacts: CapturedContact[] | null;
  dm_reachability: string | null;
  dnc_reason: string | null;
}

export interface Lead {
  patient_id: string;
  name: string;
  phone: string;
  firm_name: string | null;
  state: string | null;
  practice_area: string | null;
  email: string | null;
  title: string | null;
  tags: string[];
  attempt_count: number;
  last_attempt_at: string | null;
  last_outcome: string | null;
  priority_bucket: number;
}

export interface DispatcherDecision {
  timestamp: string;
  decision: string;
  detail: string;
  state: string;
}

export interface DispatcherStatus {
  state: "stopped" | "idle" | "dispatched" | "call_active";
  dispatched_patient_id: string | null;
  running: boolean;
  recent_decisions: DispatcherDecision[];
  batch: {
    target: number | null;
    placed: number;
    started_at: string | null;
    remaining: number | null;
  };
  config: {
    poll_interval: number;
    dispatch_timeout: number;
    max_attempts: number;
    min_hours_between: number;
    cooldown_seconds?: number;
  };
}

export interface SystemStatus {
  queue_state: unknown;
  active_call: CallLog | null;
  statistics: Record<string, unknown>;
}

// WebSocket events pushed from /ws/dashboard
export type DashboardEvent =
  | { type: "initial_state"; queue_state: unknown; active_call: CallLog | null; statistics: Record<string, unknown> }
  | { type: "queue_update"; queue_state: unknown; decision: DispatcherDecision | null }
  | { type: "call_started"; call: CallLog }
  | { type: "call_ended"; call: CallLog }
  | { type: "status_update"; status: string; call_id?: string }
  | { type: "transcript_update"; kind: "ai_delta" | "patient" | "ai"; text: string; call_id?: string }
  | { type: "ping" }
  | { type: "pong" };

export const categoryLabels: Record<string, string> = {
  on_time_completed: "按期完成",
  late_completed: "延期完成",
  pending_verification: "待核对",
  confirmed_overdue_unfinished: "已核实逾期未完成",
  not_due: "尚未到期",
  excluded: "已排除",
};
export interface Counts {
  due_total: number;
  total_nodes: number;
  on_time_completed: number;
  late_completed: number;
  pending_verification: number;
  confirmed_overdue_unfinished: number;
  not_due: number;
  excluded: number;
  on_time_rate_pct: string | null;
  completion_verification_coverage_pct: string | null;
}
export interface Evidence {
  milestone_id: string;
  milestone_code: string;
  milestone_name: string;
  node_type_code: string;
  department: string;
  plan_item_id: string;
  planned_date: string;
  actual_date: string | null;
  deviation_days: number | null;
  category: string;
  reason: string;
  source_ref: string;
  date_kind: string;
  verified_actual_id: string | null;
  actual_records: {
    id: string;
    actual_date: string | null;
    completion_flag: boolean | null;
    evidence_ref: string;
    verification_status: string;
    submitted_by: string;
    verified_by: string | null;
    verified_at: string | null;
  }[];
}
export interface Metric {
  project_id: string;
  project_code: string;
  project_name: string;
  as_of_date: string;
  plan_version_id: string;
  plan_version_label: string;
  computed_at: string;
  source_digest: string;
  sample: boolean;
  formula: { boundary: string; score: string; version: string };
  counts: Counts;
  groups: (Counts & { node_type_code: string })[];
  evidence: Evidence[];
  quality: { unconfirmed_plan_dates: number };
}
export interface Snapshot {
  id: string;
  as_of_date: string;
  source_digest: string;
  created_at: string;
  payload_json: Metric;
}
export interface MetricSummary {
  groups: (Counts & { node_type_code: string })[];
  counts: Counts;
  formula: Metric["formula"];
  as_of_date: string;
  projects: Metric[];
  unavailable: { project_id: string; project_code: string; reason: string }[];
}
export interface AIConfig {
  provider: string;
  external_enabled: boolean;
  configured: boolean;
  mode_label: string;
}
export interface Report {
  id: string;
  project_id: string;
  metric_snapshot_id: string;
  report_type: string;
  generator_type: string;
  review_status: string;
  content: string;
  contains_finance: boolean;
  editor_ids: string[];
  row_version: number;
  generated_at: string;
  validation_json: { label: string; content_digest: string };
  fact_bundle_json: {
    source_digest: string;
    metric_payload: Metric;
    facts: { id: string; text: string }[];
  };
  reviews: {
    decision: string;
    comment: string;
    reviewer_id: string;
    reviewed_at: string;
  }[];
}
export interface FinancialAccess {
  user_id: string;
  can_read: boolean;
  can_write: boolean;
  can_verify: boolean;
}
export interface FinancialPlan {
  id: string;
  record_code: string;
  direction: string;
  planned_date: string;
  planned_amount: string;
  currency: string;
  source_ref: string;
  date_source_kind: string;
}
export interface FinancialActual {
  id: string;
  record_code: string;
  direction: string;
  actual_date: string;
  actual_amount: string;
  currency: string;
  evidence_ref: string;
  verification_status: string;
  submitted_by: string;
  row_version: number;
}
export interface FinanceSummary {
  as_of_date: string;
  completeness_note: string;
  plans: FinancialPlan[];
  actuals: FinancialActual[];
  groups: {
    currency: string;
    direction: string;
    planned_total: string;
    planned_due_total: string;
    verified_actual_total: string | null;
    verified_count: number;
    unverified_count: number;
  }[];
}
export const businessToday = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
export const reportStatus: Record<string, string> = {
  draft: "草稿",
  pending_review: "待审核",
  returned: "已退回",
  approved: "已批准",
};

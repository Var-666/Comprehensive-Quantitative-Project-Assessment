export interface Project {
  id: string;
  project_code: string;
  project_name: string;
  project_type: string | null;
  project_status: string;
  owner_id: string | null;
  department_id: string | null;
  owner_name: string | null;
  department_name: string | null;
  attention_note: string | null;
  planned_start: string | null;
  planned_end: string | null;
  current_plan_version_id: string | null;
  current_plan_label: string | null;
  milestone_count: number;
  row_version: number;
  updated_at: string;
  data_source: string;
}
export interface Plan {
  id: string;
  version_label: string;
  status: string;
  row_version: number;
  change_reason: string;
  created_at: string;
  source_ref: string | null;
  editor_ids: string[];
}
export interface PlanItem {
  id: string;
  milestone_name: string;
  node_type_code: string;
  plan_version_id: string;
  planned_date: string;
  date_kind: string;
  department_id: string | null;
  owner_id: string | null;
  source_ref: string | null;
  change_reason: string;
}
export interface Actual {
  id: string;
  actual_date: string | null;
  completion_flag: boolean | null;
  verification_status: string;
  evidence_ref: string;
  is_current: boolean;
  submitted_at: string;
  submitted_by: string;
  comment: string | null;
}
export interface Milestone {
  id: string;
  project_id: string;
  milestone_code: string;
  milestone_name: string;
  node_type_code: string;
  row_version: number;
  department_name: string | null;
  plan_item: PlanItem;
  actual_records: Actual[];
  current_actual: Actual | null;
  verification_status: string;
  history?: PlanItem[];
  audit_events?: Audit[];
}
export interface Audit {
  id: string;
  action: string;
  actor_id: string;
  occurred_at: string;
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown>;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface ImportRow {
  id: string;
  sheet_name: string;
  source_row_number: number;
  raw_json: Record<string, unknown>;
  normalized_json: Record<string, unknown> | null;
  row_status: string;
  validation_errors_json: { field: string; message: string; code: string }[];
}
export interface Batch {
  id: string;
  filename: string;
  status: string;
  preview_hash: string;
  valid_rows: number;
  error_rows: number;
  rows: ImportRow[];
  result_json: { inserted: number; skipped: number } | null;
}
export const statuses: Record<string, string> = {
  draft: "草稿",
  not_started: "待启动",
  active: "进行中",
  completed: "已完成",
  archived: "已归档",
  effective: "已生效",
  superseded: "历史版本",
  not_submitted: "未提交",
  submitted: "待核实",
  verified: "已核实",
  returned: "已退回",
  disputed: "有争议",
  valid: "合法",
  error: "错误",
  duplicate: "重复",
  inserted: "已写入",
  committed: "已导入",
};

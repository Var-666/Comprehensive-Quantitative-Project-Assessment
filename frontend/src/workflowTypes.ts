export interface ConfigRecord {
  id: string;
  status: string;
  row_version: number;
  version_label: string;
  source_ref: string;
  created_by: string;
  editor_ids: string[];
  approval_ref?: string;
  approved_by?: string;
}
export interface ActionItem {
  id?: string;
  item_code: string;
  title: string;
  completion_criteria: string;
  default_department_id: string | null;
  materials_required_json: string[];
}
export interface ActionTemplate extends ConfigRecord {
  template_code: string;
  title: string;
  node_type_code: string;
  applicability_json: { project_type?: string | null };
  items: ActionItem[];
}
export interface Calendar extends ConfigRecord {
  calendar_code: string;
  timezone_name: string;
  start_date: string;
  end_date: string;
  days?: { calendar_date: string; is_workday: boolean; reason: string }[];
}
export interface ReminderRule extends ConfigRecord {
  rule_code: string;
  node_type_code: string;
  days_before: number;
  day_basis: string;
  recipient_role_code: string;
  calendar_id: string | null;
  catch_up_days: number;
}
export interface ActionLink {
  id: string;
  plan_item_id: string;
  status: string;
  snapshot_json: ActionItem & { template_code: string; version_label: string };
}
export interface FactSnapshot {
  project_code: string;
  project_name: string;
  milestone_id: string;
  milestone_code: string;
  milestone_name: string;
  planned_date: string;
  plan_version: string;
  trigger_date: string;
  source_ref: string;
  days_before: number;
  day_basis: string;
  rule_code: string;
  rule_version: string;
  recipient_name: string;
  generation_mode: string;
  sample: boolean;
  actions: ActionItem[];
}
export interface Notice {
  id: string;
  project_id: string;
  title: string;
  body: string;
  status: string;
  row_version: number;
  draft_version: number;
  editor_ids: string[];
  fact_snapshot_json: FactSnapshot;
  reviews: {
    decision: string;
    comment: string;
    draft_version: number;
    reviewed_at: string;
    reviewer_id: string;
  }[];
  deliveries: { channel: string; attempt_state: string; finished_at: string }[];
}
export interface TaskFeedback {
  id: string;
  comment: string;
  evidence_ref: string;
  claimed_completion: boolean;
  submitted_by: string;
  submitted_at: string;
  status: string;
  verification?: {
    decision: string;
    comment: string;
    reviewer_id: string;
  } | null;
}
export interface TaskRecord {
  id: string;
  project_id: string;
  title: string;
  assignee_id: string | null;
  due_date: string;
  status: string;
  row_version: number;
  requires_review: boolean;
  review_reason: string | null;
  action_snapshot_json: ActionItem;
  feedback: TaskFeedback[];
  milestone_completion?: {
    milestone_id: string;
    milestone_name: string;
    row_version: number;
    completed_tasks: number;
    total_tasks: number;
    ready: boolean;
    can_confirm: boolean;
    reason: string;
    actual_date: string | null;
  };
}
export interface InboxRecord {
  id: string;
  notification_id: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}
export interface ScanRow {
  project_id: string;
  milestone_code?: string;
  milestone_name?: string;
  planned_date?: string;
  trigger_date?: string;
  eligible: boolean;
  skipped_reason: string | null;
  recipient_user_id?: string;
}
export const workflowLabels: Record<string, string> = {
  draft: "草稿",
  pending_review: "待人工审核",
  approved: "已批准",
  retired: "已停用",
  returned: "已退回",
  approved_pending_send: "审核通过待发送",
  sent: "已站内发布",
  invalidated: "已失效",
  unassigned: "待分派",
  todo: "待处理",
  in_progress: "处理中",
  submitted: "反馈待核实",
  verified_done: "已核实完成",
  cancelled: "已取消",
  verified: "已核实",
  disputed: "有异议",
  accepted: "核实接受",
  calendar_day: "自然日",
  workday: "工作日",
  admin: "项目管理员",
  editor: "项目编辑",
  reviewer: "项目审核人",
  viewer: "项目只读成员",
  CONFIGURATION_PENDING: "动作或规则待配置/批准",
  CALENDAR_NOT_APPROVED: "企业日历未批准",
  CALENDAR_OUT_OF_RANGE: "日历覆盖范围不足",
  CALENDAR_INCOMPLETE: "日历日期缺失",
  VERIFIED_COMPLETED: "节点已核实完成",
  MILESTONE_CANCELLED: "节点已取消",
  OUTSIDE_TRIGGER_WINDOW: "不在配置的触发/追补窗口",
  ALREADY_GENERATED: "已生成，已防止重复",
  RECIPIENT_NOT_CONFIGURED: "未配置可用接收人",
  PROJECT_INACTIVE_OR_NO_EFFECTIVE_PLAN: "项目关闭或尚无生效计划",
  PLAN_NOT_EFFECTIVE: "计划尚未生效",
  PLAN_SOURCE_MISSING: "节点计划缺少来源",
};
export const label = (value: string) => workflowLabels[value] || value;

export interface NextAction {
  recommendation_id: string;
  project_id: string | null;
  project_code: string | null;
  project_name: string | null;
  action_type: string;
  business_type: string;
  title: string;
  description: string;
  reason_code: string;
  priority: number;
  target_path: string | null;
  button_label: string;
  actionable: boolean;
  blocked_reason: string;
  stage: string;
  status: string;
  due_date: string | null;
}
export interface Workbench {
  as_of: string;
  primary: NextAction;
  secondary: NextAction[];
  projects: { project_id: string; project_code: string; stage: string }[];
}

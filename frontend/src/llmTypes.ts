export interface LLMTestResult {
  ok: boolean;
  code: string;
  message: string;
  http_status: number | null;
  service_status: string;
  authentication_status: string;
  model_list_status: string;
  model_call_status: string;
  tested_at: string;
  revision: number;
  model_count?: number;
  invalid_entry_count?: number;
}
export interface LLMConfiguration {
  id: string;
  source: "database" | "environment" | "defaults";
  legacy_warning?: string | null;
  local_http_credentials_enabled: boolean;
  service_name: string;
  base_url: string;
  adapter: string;
  mode: "mock" | "maas";
  enabled: boolean;
  timeout_seconds: number;
  key_configured: boolean;
  credential_source: string;
  credential_updated_at: string | null;
  revision: number;
  endpoint_revision: number;
  row_version: number;
  updated_at: string | null;
  encryption_ready: boolean;
  environment_available: boolean;
  selections: { default?: string; analysis?: string; notification?: string };
  last_connection_test: LLMTestResult | null;
  last_models_refresh: LLMTestResult | null;
}
export interface LLMModel {
  id: string;
  model_id: string;
  display_name: string;
  source: "discovered" | "manual";
  enabled: boolean;
  selectable: boolean;
  verification_status: "untested" | "available" | "failed";
  tested_revision: number | null;
  last_discovered_at: string | null;
  last_tested_at: string | null;
  last_test_result: LLMTestResult | null;
  row_version: number;
}
export const llmState: Record<string, string> = {
  unknown: "尚未验证",
  reachable: "可连接",
  failed: "测试未通过",
  forbidden: "无操作权限",
  unsupported: "接口可能不支持",
  invalid: "响应格式待适配",
  available: "实际调用通过",
  untested: "尚未测试",
  incomplete: "输出被截断，尚未完成",
  empty: "列表为空",
  not_tested: "尚未执行",
  accepted_for_models_endpoint: "列表接口认证通过",
  accepted_for_chat_endpoint: "调用接口认证通过",
  unsupported_or_unverified: "接口支持情况待确认",
};
export const displayTime = (value: string | null | undefined) =>
  value
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        dateStyle: "short",
        timeStyle: "medium",
        hour12: false,
      }).format(new Date(value))
    : "无记录";

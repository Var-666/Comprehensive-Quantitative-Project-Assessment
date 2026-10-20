<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useAuth } from "../store";
import {
  displayTime,
  llmState,
  type LLMConfiguration,
  type LLMModel,
  type LLMTestResult,
} from "../llmTypes";
import Modal from "../components/Modal.vue";
const auth = useAuth(),
  configuration = ref<LLMConfiguration>(),
  models = ref<LLMModel[]>([]),
  loading = ref(true),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  modal = ref(""),
  keyInput = ref(""),
  showKey = ref(false),
  removeConfirmed = ref(false),
  replaceEnvironment = ref(false),
  result = ref<LLMTestResult>(),
  defaultOpen = ref(false),
  auditTab = ref("events"),
  auditRows = ref<Record<string, unknown>[]>([]);
const autoTesting = ref(false),
  stopAutoTesting = ref(false),
  autoProgress = reactive({ completed: 0, total: 0, model: "" });
let pageActive = true;
onBeforeUnmount(() => {
  pageActive = false;
  stopAutoTesting.value = true;
});
const form = reactive({
  service_name: "企业 MaaS 网关（自定义）",
  base_url: "https://maas-api.cmhk.com/v1",
  adapter: "openai_compatible",
  mode: "mock",
  enabled: false,
  timeout_seconds: 20,
});
const manual = reactive({ model_id: "", display_name: "" });
const isHTTPS = window.location.protocol === "https:";
const canManageCredentials = computed(
  () =>
    isHTTPS ||
    (configuration.value?.local_http_credentials_enabled &&
      ["127.0.0.1", "localhost", "[::1]"].includes(window.location.hostname)),
);
const canAdmin = computed(() => !!auth.user?.is_system_admin);
const available = computed(() => models.value.filter((m) => m.selectable));
const defaultModel = computed(() =>
  models.value.find((m) => m.id === configuration.value?.selections.default),
);
const stateText = computed(() =>
  configuration.value?.mode === "mock"
    ? "Mock · 不调用模型"
    : configuration.value?.enabled
      ? "实际调用已启用"
      : "实际调用未启用",
);
const baseChanged = computed(
  () =>
    configuration.value &&
    form.base_url.trim() !== configuration.value.base_url,
);
function acceptConfig(c: LLMConfiguration) {
  configuration.value = c;
  for (const k of [
    "service_name",
    "base_url",
    "adapter",
    "mode",
    "enabled",
    "timeout_seconds",
  ] as const)
    Object.assign(form, { [k]: c[k] });
}
function close() {
  if (busy.value) return;
  if (modal.value === "service" && configuration.value)
    acceptConfig(configuration.value);
  modal.value = "";
  keyInput.value = "";
  showKey.value = false;
  removeConfirmed.value = false;
  replaceEnvironment.value = false;
}
async function load(initial = false) {
  if (initial) loading.value = true;
  error.value = "";
  try {
    const [c, m] = await Promise.all([
      api<LLMConfiguration>("/settings/llm"),
      api<LLMModel[]>("/settings/llm/models"),
    ]);
    acceptConfig(c);
    models.value = m;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
}
async function run(action: () => Promise<void>) {
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await action();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function saveService() {
  await run(async () => {
    const c = await api<LLMConfiguration>("/settings/llm", {
      method: "PUT",
      headers: versionHeader(configuration.value?.row_version || 0),
      body: json({ ...form, replace_environment: replaceEnvironment.value }),
    });
    acceptConfig(c);
    models.value = await api<LLMModel[]>("/settings/llm/models");
    modal.value = "";
    success.value = "服务配置已保存，后续业务请求自动读取生效配置。";
  });
}
function keyModal() {
  keyInput.value = "";
  showKey.value = false;
  replaceEnvironment.value = false;
  error.value = "";
  modal.value = "key";
}
async function saveKey() {
  await run(async () => {
    try {
      const c = await api<LLMConfiguration>("/settings/llm/credential", {
        method: "PUT",
        headers: versionHeader(configuration.value?.row_version || 0),
        body: json({
          api_key: keyInput.value,
          replace_environment: replaceEnvironment.value,
        }),
      });
      acceptConfig(c);
      models.value = await api<LLMModel[]>("/settings/llm/models");
      modal.value = "";
      success.value = "密钥已加密保存；模型需使用当前凭据重新测试。";
    } finally {
      keyInput.value = "";
      showKey.value = false;
    }
  });
}
async function removeKey() {
  await run(async () => {
    const c = await api<LLMConfiguration>("/settings/llm/credential", {
      method: "DELETE",
      headers: versionHeader(configuration.value?.row_version || 0),
    });
    acceptConfig(c);
    models.value = await api<LLMModel[]>("/settings/llm/models");
    modal.value = "";
    removeConfirmed.value = false;
    success.value = "已移除密钥并停止后续实际调用，不会回退使用旧环境Key。";
  });
}
async function testConnection(refresh = false) {
  await run(async () => {
    if (baseChanged.value)
      throw new Error("请先保存服务地址，再测试或获取模型。");
    const r = await api<{
      config: LLMConfiguration;
      result: LLMTestResult;
      models?: LLMModel[];
    }>(`/settings/llm/${refresh ? "models/refresh" : "test-connection"}`, {
      method: "POST",
      headers: versionHeader(configuration.value?.row_version || 0),
    });
    acceptConfig(r.config);
    if (r.models) models.value = r.models;
    result.value = r.result;
    if (refresh && r.result.ok) {
      await verifyPendingModels();
      return;
    }
    modal.value = "result";
    if (r.result.ok) success.value = r.result.message;
    else error.value = r.result.message;
  });
}
async function requestModelTest(m: LLMModel) {
  const r = await api<{ model: LLMModel; result: LLMTestResult }>(
    `/settings/llm/models/${m.id}/test`,
    { method: "POST", headers: versionHeader(m.row_version) },
  );
  models.value = models.value.map((old) => (old.id === m.id ? r.model : old));
  return r.result;
}
async function verifyPendingModels() {
  if (!pageActive) return;
  const pending = models.value.filter((m) => m.enabled && !m.selectable);
  Object.assign(autoProgress, {
    completed: 0,
    total: pending.length,
    model: "",
  });
  stopAutoTesting.value = false;
  autoTesting.value = true;
  let passed = 0;
  try {
    for (const m of pending) {
      if (stopAutoTesting.value || !pageActive) break;
      autoProgress.model = m.display_name;
      const r = await requestModelTest(m);
      autoProgress.completed++;
      if (r.ok) passed++;
      if (
        [
          "LLM_AUTH_FAILED",
          "LLM_RATE_LIMITED",
          "LLM_NETWORK_ERROR",
          "LLM_TIMEOUT",
          "LLM_UPSTREAM_ERROR",
          "LLM_CREDENTIAL_MISSING",
          "LLM_CREDENTIAL_DECRYPT_FAILED",
        ].includes(r.code)
      ) {
        error.value = `自动验证暂停：${r.message}`;
        stopAutoTesting.value = true;
      }
    }
    const prefix = stopAutoTesting.value ? "自动验证已停止" : "自动验证完成";
    success.value = `${prefix}：已测试 ${autoProgress.completed}/${pending.length} 个，${passed} 个通过，${autoProgress.completed - passed} 个未通过；跳过 ${models.value.length - pending.length} 个已验证或已禁用模型。`;
  } catch (e) {
    success.value = `自动验证已中断：已完成 ${autoProgress.completed}/${pending.length} 个，已完成的结果已保存。`;
    throw e;
  } finally {
    autoTesting.value = false;
  }
}
function addModel() {
  Object.assign(manual, { model_id: "", display_name: "" });
  error.value = "";
  modal.value = "manual";
  defaultOpen.value = false;
}
async function saveModel() {
  await run(async () => {
    await api("/settings/llm/models", {
      method: "POST",
      headers: versionHeader(configuration.value?.row_version || 0),
      body: json({
        model_id: manual.model_id,
        display_name: manual.display_name || null,
      }),
    });
    await load();
    modal.value = "";
    success.value = "已保存手动模型，尚未验证可用。";
  });
}
async function testModel(m: LLMModel) {
  await run(async () => {
    const r = await requestModelTest(m);
    result.value = r;
    modal.value = "result";
    if (r.ok) success.value = r.message;
    else error.value = r.message;
  });
}
async function chooseDefault(id: string | null) {
  await run(async () => {
    acceptConfig(
      await api<LLMConfiguration>("/settings/llm/default-model", {
        method: "PUT",
        headers: versionHeader(configuration.value?.row_version || 0),
        body: json({ model_config_id: id }),
      }),
    );
    defaultOpen.value = false;
    success.value = "默认模型已保存。";
  });
}
async function chooseScenario(
  scenario: "analysis" | "notification",
  event: Event,
) {
  const id = (event.target as HTMLSelectElement).value;
  await run(async () => {
    const choices = {
      analysis: configuration.value?.selections.analysis || null,
      notification: configuration.value?.selections.notification || null,
      [scenario]: id || null,
    };
    acceptConfig(
      await api<LLMConfiguration>("/settings/llm/scenario-models", {
        method: "PUT",
        headers: versionHeader(configuration.value?.row_version || 0),
        body: json(choices),
      }),
    );
    success.value = "业务场景模型已保存。";
  });
}
async function toggleModel(m: LLMModel) {
  await run(async () => {
    const updated = await api<LLMModel>(`/settings/llm/models/${m.id}`, {
      method: "PUT",
      headers: versionHeader(m.row_version),
      body: json({ enabled: !m.enabled }),
    });
    models.value = models.value.map((old) => (old.id === m.id ? updated : old));
    success.value = "模型启用状态已保存。";
  });
}
const deleting = ref<LLMModel>();
async function deleteModel() {
  if (!deleting.value) return;
  await run(async () => {
    await api(`/settings/llm/models/${deleting.value!.id}`, {
      method: "DELETE",
      headers: versionHeader(deleting.value!.row_version),
    });
    models.value = models.value.filter((m) => m.id !== deleting.value?.id);
    deleting.value = undefined;
    success.value = "手动模型已删除。";
  });
}
async function importEnvironment() {
  await run(async () => {
    acceptConfig(
      await api<LLMConfiguration>("/settings/llm/import-environment", {
        method: "POST",
        headers: versionHeader(configuration.value?.row_version || 0),
        body: json({ confirmed: true }),
      }),
    );
    models.value = await api<LLMModel[]>("/settings/llm/models");
    modal.value = "";
    success.value =
      "旧环境配置已加密迁移，尚未启用实际调用；请测试模型并选择默认模型。";
  });
}
async function toggleService() {
  form.mode = "maas";
  form.enabled = !configuration.value?.enabled;
  await saveService();
}
async function showAudit(tab = "events") {
  auditTab.value = tab;
  await run(async () => {
    auditRows.value = await api<Record<string, unknown>[]>(
      `/settings/llm/${tab === "events" ? "audit-events" : "call-logs"}`,
    );
    modal.value = "audit";
  });
}
onMounted(() => {
  if (canAdmin.value) void load(true);
  else loading.value = false;
});
</script>
<template>
  <div class="page-title llm-heading">
    <div>
      <h1>系统设置</h1>
      <p>大模型服务配置与调用策略 · 仅授权管理员可修改</p>
    </div>
    <button
      v-if="canAdmin"
      class="primary"
      :disabled="busy || loading || !configuration"
      @click="saveService"
    >
      保存配置
    </button>
  </div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <p v-if="!canAdmin" class="notice warning">
    仅系统管理员可访问大模型配置，请联系管理员。
  </p>
  <p v-else-if="loading" class="empty">正在加载大模型服务配置…</p>
  <template v-else-if="configuration"
    ><div class="notice llm-principle">
      <strong>配置原则</strong
      ><span
        >API Key 仅由后端加密保存；前端不回显旧密钥，不写入浏览器存储。{{
          configuration.source === "environment"
            ? "当前沿用旧环境配置，须显式迁移或确认接管。"
            : "服务连接和模型调用分别验证。"
        }}</span
      >
    </div>
    <p v-if="configuration.legacy_warning" class="notice warning">
      {{ configuration.legacy_warning }}
    </p>
    <div class="llm-columns">
      <section class="card llm-card llm-service">
        <div class="llm-section-title">
          <h3>服务接入配置</h3>
          <span class="badge">{{
            configuration.key_configured ? "已配置凭据" : "未完成配置"
          }}</span>
        </div>
        <div class="llm-provider-row">
          <div>
            <strong>{{ configuration.service_name }}</strong
            ><small>协议：OpenAI 兼容接口（兼容性待实际验证）</small>
          </div>
          <button
            :disabled="busy"
            @click="
              modal = 'service';
              replaceEnvironment = false;
            "
          >
            管理服务
          </button>
        </div>
        <label
          >API Base URL<input
            v-model="form.base_url"
            type="url"
            maxlength="500"
            :disabled="busy"
        /></label>
        <div class="llm-key-row">
          <label
            >API Key
            <div class="llm-key-status">
              {{
                configuration.key_configured
                  ? "已配置 · 不可查看旧密钥"
                  : "尚未配置 · 请录入后进行连接测试"
              }}<small v-if="configuration.credential_updated_at"
                >更新于
                {{ displayTime(configuration.credential_updated_at) }}</small
              >
            </div></label
          ><button :disabled="busy" @click="keyModal">设置 / 更换 Key</button>
        </div>
        <div class="llm-connection-actions">
          <button
            class="primary"
            :disabled="busy"
            @click="testConnection(false)"
          >
            {{ busy ? "处理中…" : "测试连接" }}</button
          ><button :disabled="busy" @click="testConnection(true)">
            刷新模型列表</button
          ><small
            >上次测试：{{
              displayTime(configuration.last_connection_test?.tested_at)
            }}</small
          >
        </div>
        <div class="llm-footnote">
          保存后仅显示“已配置”及更新时间，不返回完整密钥。地址变更会清除旧凭据并隔离旧模型。
        </div>
      </section>
      <section class="card llm-card llm-default">
        <div class="llm-section-title">
          <h3>默认模型与用途</h3>
          <span class="badge">{{ defaultModel ? "已选择" : "尚未选择" }}</span>
        </div>
        <label>系统默认模型</label>
        <div class="llm-model-select">
          <button
            class="llm-select-trigger"
            :disabled="busy"
            :aria-expanded="defaultOpen"
            aria-controls="default-model-options"
            @click="defaultOpen = !defaultOpen"
          >
            {{ defaultModel?.display_name || "先连接服务并获取模型列表"
            }}<span>选择 ▾</span>
          </button>
          <div
            v-if="defaultOpen"
            id="default-model-options"
            class="llm-model-options"
          >
            <strong>选择默认模型</strong>
            <p v-if="!available.length" class="llm-footnote">
              没有可用的已验证模型<br />请配置Key并刷新模型列表，或手动填写授权模型ID后测试。
            </p>
            <button
              v-for="m in available"
              :key="m.id"
              @click="chooseDefault(m.id)"
            >
              {{ m.display_name }}<small>{{ m.model_id }}</small></button
            ><button v-if="defaultModel" @click="chooseDefault(null)">
              取消默认模型
            </button>
            <div class="actions">
              <button :disabled="busy" @click="testConnection(true)">
                刷新列表</button
              ><button @click="addModel">手动添加模型</button>
            </div>
          </div>
        </div>
        <h4>应用场景</h4>
        <label class="llm-scenario"
          >项目阶段智能分析<select
            :value="configuration.selections.analysis || ''"
            :disabled="busy"
            @change="chooseScenario('analysis', $event)"
          >
            <option value="">跟随默认模型</option>
            <option
              v-for="m in models.filter(
                (m) =>
                  m.selectable || m.id === configuration?.selections.analysis,
              )"
              :key="m.id"
              :value="m.id"
              :disabled="!m.selectable"
            >
              {{ m.display_name }}
            </option>
          </select></label
        ><label class="llm-scenario"
          >通知与工作安排草稿<select
            :value="configuration.selections.notification || ''"
            :disabled="busy"
            @change="chooseScenario('notification', $event)"
          >
            <option value="">跟随默认模型</option>
            <option
              v-for="m in models.filter(
                (m) =>
                  m.selectable ||
                  m.id === configuration?.selections.notification,
              )"
              :key="m.id"
              :value="m.id"
              :disabled="!m.selectable"
            >
              {{ m.display_name }}
            </option>
          </select></label
        >
        <div class="llm-enable-row">
          <div>
            <strong>AI 功能启用状态</strong><small>{{ stateText }}</small>
          </div>
          <button
            class="llm-toggle"
            role="switch"
            :aria-checked="
              configuration.enabled && configuration.mode === 'maas'
            "
            aria-label="启用实际模型调用"
            :disabled="busy"
            @click="toggleService"
          >
            <img
              v-if="!configuration.enabled || configuration.mode === 'mock'"
              src="/icons/toggle-off.svg"
              alt="未启用"
            /><span v-else class="llm-toggle-on">已启用</span>
          </button>
        </div>
        <small class="muted"
          >模型选择即时保存；业务调用仍需用户本次同意外送。</small
        >
      </section>
    </div>
    <section class="card llm-model-card">
      <div class="llm-model-title">
        <div>
          <h3>可用模型</h3>
          <p>
            刷新后自动测试未验证的已启用模型，每次最多128个输出token；已验证模型跳过。基础测试验证短文本调用，报告还须通过结构化输出和事实引用校验。
          </p>
        </div>
        <div class="actions">
          <button :disabled="busy" @click="testConnection(true)">
            刷新模型</button
          ><button class="primary" :disabled="busy" @click="addModel">
            ＋ 手动添加模型
          </button>
        </div>
      </div>
      <div v-if="autoTesting" class="notice" role="status" aria-live="polite">
        正在自动验证 {{ autoProgress.completed }}/{{ autoProgress.total }}：{{
          autoProgress.model
        }}
        <button @click="stopAutoTesting = true" :disabled="stopAutoTesting">
          {{ stopAutoTesting ? "等待当前测试结束…" : "停止后续测试" }}
        </button>
      </div>
      <div class="table-wrap">
        <table class="llm-table">
          <thead>
            <tr>
              <th>模型 ID</th>
              <th>显示名称</th>
              <th>来源</th>
              <th>基础调用验证</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in models" :key="m.id">
              <td>
                {{ m.model_id
                }}<small
                  v-if="m.id === configuration.selections.default"
                  class="block active"
                  >系统默认模型</small
                >
              </td>
              <td>{{ m.display_name }}</td>
              <td>
                {{ m.source === "manual" ? "手动录入" : "接口发现"
                }}<small class="block muted"
                  >最近获取 {{ displayTime(m.last_discovered_at) }}</small
                >
              </td>
              <td>
                <span class="badge">{{ llmState[m.verification_status] }}</span
                ><small class="block muted"
                  >{{ m.enabled ? "已启用" : "已禁用" }} ·
                  {{ displayTime(m.last_tested_at) }}</small
                >
                <small
                  v-if="m.last_test_result && !m.last_test_result.ok"
                  class="block muted"
                >
                  {{ m.last_test_result.message }}
                </small>
              </td>
              <td>
                <div class="actions">
                  <button :disabled="busy || !m.enabled" @click="testModel(m)">
                    测试模型</button
                  ><button :disabled="busy" @click="toggleModel(m)">
                    {{ m.enabled ? "禁用" : "启用" }}</button
                  ><button
                    v-if="m.source === 'manual'"
                    :disabled="busy"
                    @click="deleting = m"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!models.length" class="empty llm-model-empty">
        <strong>暂未获取到可用模型</strong>
        <p>
          API Key 和服务连接确认后再刷新；未获取到列表时请手动录入准确的模型
          ID。
        </p>
      </div>
      <p v-if="configuration.last_models_refresh" class="llm-footnote">
        最近获取：{{
          displayTime(configuration.last_models_refresh.tested_at)
        }}
        · {{ configuration.last_models_refresh.message }}
      </p>
    </section>
    <div class="llm-security">
      <strong>安全与权限</strong
      ><span
        >配置保存、连接测试、模型刷新和删除均由后端鉴权；密钥不会通过
        GET、日志或报表明文返回。</span
      ><button class="text-button" :disabled="busy" @click="showAudit()">
        操作审计
      </button>
    </div></template
  ><button v-else-if="canAdmin && !loading" @click="load(true)">
    重新加载配置
  </button>
  <Modal
    v-if="modal === 'key' && configuration"
    title="配置 API Key"
    subtitle="密钥仅服务端接收，保存后不可查看完整内容"
    class="llm-key-modal"
    :busy="busy"
    @close="close"
  >
    <div class="notice">
      <strong
        >当前状态：{{
          configuration.key_configured ? "已配置" : "未配置"
        }}</strong
      >
      <p>服务地址：{{ configuration.base_url }}</p>
    </div>
    <form id="llm-key-form" @submit.prevent="saveKey">
      <label
        >新的 API Key *
        <div class="llm-password">
          <input
            v-model="keyInput"
            :type="showKey ? 'text' : 'password'"
            autocomplete="new-password"
            required
            maxlength="8192"
            :disabled="!canManageCredentials || busy"
            placeholder="请输入 API Key，输入过程以密码形式遮挡"
          /><button
            class="text-button"
            type="button"
            @click="showKey = !showKey"
          >
            {{ showKey ? "隐藏" : "显示" }}
          </button>
        </div></label
      >
      <div class="llm-modal-facts">
        <h3>安全处理要求</h3>
        <p>• 后端加密存储；加密主密钥由部署环境或受控密钥文件提供。</p>
        <p>• 页面仅显示“已配置”及更新时间，不可回显、复制旧 Key。</p>
        <p>• 更换和移除密钥需要系统管理员权限并记录脱敏审计。</p>
      </div>
      <label v-if="configuration.source === 'environment'" class="llm-checkbox"
        ><input
          v-model="replaceEnvironment"
          type="checkbox"
        />确认接管旧环境配置，后续不再回退使用环境Key</label
      >
      <p v-if="!canManageCredentials" class="notice warning">
        当前入口不允许提交密钥，请使用 HTTPS，或通过 scripts/dev.sh
        启用本机开发入口。
      </p>
      <p v-else-if="!isHTTPS" class="notice">
        本机开发 HTTP 模式已启用，仅限当前电脑；密钥仍由后端加密保存。
      </p>
      <p v-if="!configuration.encryption_ready" class="notice warning">
        部署加密主密钥尚未就绪，请由运维先初始化密钥保管配置。
      </p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
    <button
      :disabled="busy || !configuration.key_configured || !canManageCredentials"
      @click="
        keyInput = '';
        modal = 'remove';
        removeConfirmed = false;
      "
    >
      移除已保存 Key</button
    ><small class="muted">移除操作需要再次确认，本页不展示真实密钥值。</small
    ><template #footer
      ><button :disabled="busy" @click="close">取消</button
      ><button
        class="primary"
        form="llm-key-form"
        :disabled="
          busy ||
          !canManageCredentials ||
          !configuration.encryption_ready ||
          (configuration.source === 'environment' && !replaceEnvironment)
        "
      >
        保存新密钥
      </button></template
    ></Modal
  >
  <Modal
    v-if="modal === 'remove'"
    title="确认移除 API Key"
    :busy="busy"
    @close="close"
    ><p>移除后，新请求无法继续使用旧密钥；不会回退使用环境凭据。</p>
    <label class="llm-checkbox"
      ><input v-model="removeConfirmed" type="checkbox" />确认移除已保存的
      Key</label
    >
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template #footer
      ><button :disabled="busy" @click="close">取消</button
      ><button
        class="primary"
        :disabled="busy || !removeConfirmed"
        @click="removeKey"
      >
        确认移除密钥
      </button></template
    ></Modal
  >
  <Modal
    v-if="modal === 'manual'"
    title="手动添加模型"
    subtitle="无法获取列表时，使用服务商提供的准确模型 ID"
    class="llm-manual-modal"
    :busy="busy"
    @close="close"
  >
    <div class="notice">
      模型来源：手动录入
      <p>录入后需验证接口调用成功，才能设为默认模型。</p>
    </div>
    <form id="llm-model-form" @submit.prevent="saveModel">
      <label
        >模型 ID *<input
          v-model="manual.model_id"
          required
          maxlength="256"
          placeholder="请输入模型提供方返回的 model ID（不可凭名称推测）" /></label
      ><label
        >显示名称（可选）<input
          v-model="manual.display_name"
          maxlength="256"
          placeholder="仅供界面辨识"
      /></label>
      <div class="llm-modal-facts">
        <h3>允许使用的场景</h3>
        <div class="actions">
          <span class="badge">项目阶段分析</span
          ><span class="badge">通知草稿生成</span
          ><span class="badge">其他用途（后续扩展）</span>
        </div>
        <small class="muted">具体场景所用模型在主页面分配。</small>
      </div>
      <p class="notice warning">
        请勿填写示例模型名代替真实模型
        ID。平台可用模型取决于账户授权，手动录入不等于已验证可用。
      </p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
    <template #footer
      ><button :disabled="busy" @click="close">取消</button
      ><button form="llm-model-form" class="primary" :disabled="busy">
        保存模型
      </button></template
    ></Modal
  >
  <Modal
    v-if="modal === 'result' && result && configuration"
    title="连接测试结果"
    class="llm-result-modal"
    :busy="busy"
    @close="close"
    ><p class="muted">
      {{
        result.code === "LLM_CREDENTIAL_MISSING"
          ? "尚未配置密钥，未向平台发送请求。"
          : "测试由后端执行；列表查询与模型调用独立记录。"
      }}
    </p>
    <div :class="result.ok ? 'success' : 'notice warning'">
      <strong>{{ result.ok ? "测试通过" : "当前测试未通过" }}</strong>
      <p>{{ result.message }}</p>
    </div>
    <div class="llm-test-field">
      <strong>服务地址</strong>
      <p>{{ configuration.base_url }}</p>
    </div>
    <div
      v-for="item in [
        { label: '服务连接状态', value: result.service_status },
        { label: '身份认证状态', value: result.authentication_status },
        { label: '模型列表查询', value: result.model_list_status },
        { label: '选定模型调用', value: result.model_call_status },
      ]"
      :key="item.label"
      class="llm-test-field"
    >
      <strong>{{ item.label }}</strong
      ><span>{{
        item.label === "模型列表查询" && item.value === "available"
          ? "列表读取成功"
          : llmState[item.value] || item.value
      }}</span>
    </div>
    <small class="muted"
      >最近测试 {{ displayTime(result.tested_at)
      }}{{
        result.http_status ? ` · 平台HTTP ${result.http_status}` : ""
      }}</small
    >
    <p class="notice">
      /models 不可用时允许手动配置准确模型 ID，不能据此认定 Key
      无效或模型不可用。
    </p>
    <template #footer
      ><button @click="close">关闭结果</button
      ><button
        v-if="!configuration.key_configured"
        class="primary"
        @click="keyModal"
      >
        前往 API Key 配置
      </button></template
    ></Modal
  >
  <Modal
    v-if="modal === 'service' && configuration"
    title="管理模型服务"
    :busy="busy"
    @close="close"
    ><form
      id="llm-service-form"
      class="form-grid"
      @submit.prevent="saveService"
    >
      <label class="full"
        >服务名称 *<input
          v-model="form.service_name"
          required
          maxlength="120" /></label
      ><label class="full"
        >API Base URL *<input
          v-model="form.base_url"
          type="url"
          required
          maxlength="500" /></label
      ><label
        >服务适配器<select v-model="form.adapter">
          <option value="openai_compatible">OpenAI 兼容候选（需验证）</option>
        </select></label
      ><label
        >请求超时（秒）<input
          v-model.number="form.timeout_seconds"
          type="number"
          min="1"
          max="60"
          required /></label
      ><label
        >调用模式<select v-model="form.mode">
          <option value="mock">明确标记 Mock</option>
          <option value="maas">真实 MaaS</option>
        </select></label
      ><label class="llm-checkbox"
        ><input v-model="form.enabled" type="checkbox" />允许实际业务调用</label
      >
      <p class="notice warning full">
        仅允许部署白名单中的HTTPS地址。变更地址将清除旧Key、默认与场景选择；旧地址模型记录保留但隔离。
      </p>
      <label
        v-if="configuration.source === 'environment'"
        class="llm-checkbox full"
        ><input
          v-model="replaceEnvironment"
          type="checkbox"
        />明确接管旧环境配置（不自动复制旧Key）</label
      >
      <p v-if="error" class="error full" role="alert">{{ error }}</p>
    </form>
    <template #footer
      ><button
        v-if="configuration.source === 'environment'"
        :disabled="
          busy || !canManageCredentials || !configuration.encryption_ready
        "
        @click="modal = 'import'"
      >
        迁移旧环境配置</button
      ><button :disabled="busy" @click="close">取消</button
      ><button
        class="primary"
        form="llm-service-form"
        :disabled="
          busy ||
          (configuration.source === 'environment' && !replaceEnvironment)
        "
      >
        保存服务配置
      </button></template
    ></Modal
  >
  <Modal
    v-if="modal === 'import'"
    title="确认迁移旧环境配置"
    :busy="busy"
    @close="close"
    ><p>
      由后端读取旧环境凭据并加密保存，已有模型ID以“手动、未测试”导入。迁移后由数据库配置接管，实际调用保持关闭，需测试并选用模型后启用。
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template #footer
      ><button @click="close">取消</button
      ><button
        class="primary"
        :disabled="busy || !canManageCredentials"
        @click="importEnvironment"
      >
        确认加密迁移
      </button></template
    ></Modal
  >
  <Modal
    v-if="deleting"
    title="删除手动模型"
    :busy="busy"
    @close="deleting = undefined"
    ><p>
      确认删除 {{ deleting.model_id }}？默认或场景正在引用时，后端会拒绝删除。
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template #footer
      ><button @click="deleting = undefined">取消</button
      ><button class="primary" :disabled="busy" @click="deleteModel">
        确认删除模型
      </button></template
    ></Modal
  >
  <Modal
    v-if="modal === 'audit'"
    title="大模型配置操作记录"
    drawer
    @close="close"
    ><div class="tabs">
      <button :disabled="busy" @click="showAudit('events')">配置审计</button
      ><button :disabled="busy" @click="showAudit('calls')">
        脱敏调用日志
      </button>
    </div>
    <p v-if="!auditRows.length" class="empty">暂无记录。</p>
    <div v-for="(row, i) in auditRows" :key="i" class="fact-box">
      <p>
        {{ row.action || row.operation }} · {{ row.actor_id }} ·
        {{ row.occurred_at }}
      </p>
      <small>{{ row.outcome_code || row.request_id }}</small>
    </div></Modal
  >
</template>

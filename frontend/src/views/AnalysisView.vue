<script setup lang="ts">
import { ElButton } from "element-plus/es/components/button/index";
import FormSelect from "../components/FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import FormDate from "../components/FormDate.vue";
import { ElCheckbox } from "element-plus/es/components/checkbox/index";
import { ElInput } from "element-plus/es/components/input/index";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api, errorMessage, json, versionHeader } from "../api";
import { useAuth } from "../store";
import type { Project, Page } from "../types";
import {
  businessToday,
  reportStatus,
  type AIConfig,
  type Report,
  type Snapshot,
  type FinancialAccess,
} from "../evaluationTypes";
import Icon from "../components/Icon.vue";
import Modal from "../components/Modal.vue";
import FinancePanel from "../components/FinancePanel.vue";
import ReportContent from "../components/ReportContent.vue";
import { displayTime } from "../llmTypes";
const basis = ref<Snapshot>();
const generationAttempt = ref<{ signature: string; key: string }>();
const route = useRoute(),
  auth = useAuth(),
  projectId = ref(String(route.query.project || "")),
  asOf = ref(String(route.query.as_of || businessToday())),
  type = ref("stage"),
  projects = ref<Project[]>([]),
  reports = ref<Report[]>([]),
  selected = ref<Report>(),
  config = ref<AIConfig>(),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  tab = ref("reports"),
  includeFinance = ref(false),
  financialRead = ref(false),
  allowExternal = ref(false),
  reviewOpen = ref(false),
  deleting = ref<Report>(),
  comment = ref(""),
  decision = ref("approved");
const canReview = computed(
  () =>
    selected.value &&
    auth.can(selected.value.project_id, "review") &&
    !selected.value.editor_ids.includes(auth.user?.user_id || ""),
);
function changeProject() {
  basis.value = undefined;
  generationAttempt.value = undefined;
  void load();
}
async function load() {
  if (!projectId.value) return;
  busy.value = true;
  error.value = "";
  selected.value = undefined;
  includeFinance.value = false;
  financialRead.value = false;
  try {
    reports.value = await api<Report[]>(`/projects/${projectId.value}/reports`);
    const grants = await api<FinancialAccess[]>(
      `/projects/${projectId.value}/financial-access`,
    );
    financialRead.value = !!grants.find(
      (g) => g.user_id === auth.user?.user_id && g.can_read,
    );
    if (reports.value[0]) await choose(reports.value[0].id);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function choose(id: string) {
  busy.value = true;
  error.value = "";
  try {
    selected.value = await api<Report>(`/reports/${id}`);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function generate() {
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    const snap =
      basis.value ||
      (await api<Snapshot>(`/projects/${projectId.value}/metric-snapshots`, {
        method: "POST",
        body: json({ as_of: asOf.value }),
      }));
    const body = {
      metric_snapshot_id: snap.id,
      report_type: type.value,
      include_finance: includeFinance.value,
      allow_external: allowExternal.value,
    };
    const signature = json(body);
    if (generationAttempt.value?.signature !== signature)
      generationAttempt.value = { signature, key: crypto.randomUUID() };
    const report = await api<Report>(
      `/projects/${projectId.value}/reports/draft`,
      {
        method: "POST",
        headers: { "Idempotency-Key": generationAttempt.value!.key },
        body: json(body),
      },
    );
    reports.value = await api<Report[]>(`/projects/${projectId.value}/reports`);
    selected.value = report;
    generationAttempt.value = undefined;
    success.value = "报告草稿已生成并保存，尚未审核。";
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function submit() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    selected.value = await api<Report>(
      `/reports/${selected.value.id}/submit-review`,
      { method: "POST", headers: versionHeader(selected.value.row_version) },
    );
    reports.value = reports.value.map((r) =>
      r.id === selected.value?.id ? selected.value! : r,
    );
    success.value = "已提交独立审核。";
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function removeReport() {
  if (!deleting.value) return;
  const target = deleting.value;
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await api(`/reports/${target.id}`, {
      method: "DELETE",
      headers: versionHeader(target.row_version),
    });
    reports.value = reports.value.filter((r) => r.id !== target.id);
    if (selected.value?.id === target.id) {
      selected.value = undefined;
      if (reports.value[0]) await choose(reports.value[0].id);
    }
    generationAttempt.value = undefined;
    deleting.value = undefined;
    success.value = "报告已删除，审核与审计记录保留。";
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function review() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    selected.value = await api<Report>(`/reports/${selected.value.id}/review`, {
      method: "POST",
      headers: versionHeader(selected.value.row_version),
      body: json({ decision: decision.value, comment: comment.value }),
    });
    reports.value = reports.value.map((r) =>
      r.id === selected.value?.id ? selected.value! : r,
    );
    reviewOpen.value = false;
    success.value = "报告审核结果已留痕。";
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  busy.value = true;
  try {
    const [p, c] = await Promise.all([
      api<Page<Project>>("/projects?page_size=100"),
      api<AIConfig>("/ai/config"),
    ]);
    projects.value = p.items;
    let page = 2;
    while (projects.value.length < p.total) {
      const next = await api<Page<Project>>(
        `/projects?page_size=100&page=${page++}`,
      );
      projects.value.push(...next.items);
    }
    config.value = c;
    if (!projectId.value) projectId.value = projects.value[0]?.id || "";
    if (route.query.snapshot) {
      const frozen = await api<Snapshot>(
        `/metric-snapshots/${String(route.query.snapshot)}`,
      );
      if (frozen.payload_json.project_id !== projectId.value)
        throw new Error("评价快照与报告项目不一致");
      basis.value = frozen;
      asOf.value = frozen.as_of_date;
    }
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
});
</script>
<template>
  <div class="page-title">
    <div>
      <h1>AI 阶段报告工作台</h1>
      <p>基于节点、核实结果和评价数据生成 · 保留事实来源与独立审核记录</p>
    </div>
    <RouterLink class="button" to="/metrics">查看量化评估</RouterLink>
  </div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <div class="tabs">
    <ElButton
      :class="{ primary: tab === 'reports' }"
      @click="
        tab = 'reports';
        load();
      "
      native-type="submit"
      :type="tab === 'reports' ? 'primary' : 'default'"
    >
      阶段评价报告</ElButton
    ><ElButton
      :class="{ primary: tab === 'finance' }"
      @click="tab = 'finance'"
      native-type="submit"
      :type="tab === 'finance' ? 'primary' : 'default'"
    >
      收付款记录
    </ElButton>
  </div>
  <div v-if="tab === 'finance'" class="card filters">
    <label
      >财务项目<FormSelect
        v-model="projectId"
        @change="changeProject"
        :aria-label="'财务项目'"
      >
        <ElOption
          :data-ui-value="p.id"
          v-for="p in projects"
          :key="p.id"
          :value="p.id"
          :label="String(p.project_code) + ' · ' + String(p.project_name)"
        /> </FormSelect></label
    ><label
      >财务统计截止日<FormDate
        v-model="asOf"
        :disabled="!!basis"
        :aria-label="'财务统计截止日'"
    /></label>
  </div>
  <FinancePanel
    v-if="tab === 'finance' && projectId"
    :project-id="projectId"
    :as-of="asOf"
  />
  <div v-if="tab === 'reports'" class="analysis-layout">
    <section class="card analysis-config">
      <h3>报告生成配置</h3>
      <p v-if="basis" class="notice">
        采用指定冻结快照 · {{ basis.payload_json.plan_version_label }} ·
        {{ basis.as_of_date }}。后续事实变化不会改写本报告依据。<ElButton
          class="text-button"
          @click="basis = undefined"
          native-type="submit"
          link
        >
          改用当前事实重新计算
        </ElButton>
      </p>
      <label
        >报告项目<FormSelect
          v-model="projectId"
          @change="changeProject"
          :aria-label="'报告项目'"
        >
          <ElOption
            :data-ui-value="p.id"
            v-for="p in projects"
            :key="p.id"
            :value="p.id"
            :label="String(p.project_code) + ' · ' + String(p.project_name)"
          /> </FormSelect></label
      ><label
        >报告截止日<FormDate
          v-model="asOf"
          :disabled="!!basis"
          :aria-label="'报告截止日'" /></label
      ><label
        >报告类型<FormSelect v-model="type" :aria-label="'报告类型'">
          <ElOption
            data-ui-value="stage"
            value="stage"
            :label="'项目阶段评价报告'"
          />
          <ElOption
            data-ui-value="exceptions"
            value="exceptions"
            :label="'异常节点分析'"
          />
          <ElOption
            data-ui-value="work_plan"
            value="work_plan"
            :label="'阶段工作安排'"
          /> </FormSelect></label
      ><ElCheckbox
        class="inline-label"
        v-model="includeFinance"
        :disabled="!financialRead"
        >包含已授权财务事实</ElCheckbox
      ><small v-if="!financialRead" class="muted"
        >需在收付款记录中单独取得财务读取权限。</small
      >
      <div class="notice warning">
        <strong>{{ config?.mode_label || "正在读取模型配置" }}</strong>
        <p>
          事实、数值和状态由后端确定。模型只整理已有事实引用，建议不作为业务事实。
        </p>
      </div>
      <ElCheckbox
        v-if="config?.provider !== 'mock'"
        class="inline-label"
        v-model="allowExternal"
        >允许本次向已配置模型外送事实ID、分类和类型（不发送正文、金额、名称）</ElCheckbox
      ><ElButton
        class="primary generate-report"
        :disabled="
          busy ||
          !projectId ||
          !asOf ||
          !auth.can(projectId) ||
          (!allowExternal && config?.provider !== 'mock')
        "
        @click="generate"
        native-type="submit"
        type="primary"
      >
        <Icon name="imgVectorSparkles" />{{ busy ? "处理中…" : "生成报告草稿" }}
      </ElButton>
      <p class="muted">报告由编辑生成，另一审核人批准；快照保留生成时事实。</p>
      <h3>已保存报告</h3>
      <ElButton
        :disabled="busy || !projectId"
        @click="load"
        native-type="submit"
        >刷新报告列表</ElButton
      >
      <p v-if="!reports.length" class="empty">暂无可访问的报告。</p>
      <div
        v-for="r in reports"
        :key="r.id"
        class="report-history-entry"
        :data-report-id="r.id"
      >
        <button
          type="button"
          class="queue-item"
          :class="{ selected: r.id === selected?.id }"
          :disabled="busy"
          @click="choose(r.id)"
        >
          <strong
            ><time :datetime="r.generated_at" :title="r.generated_at">{{
              displayTime(r.generated_at)
            }}</time></strong
          ><small
            >{{ reportStatus[r.review_status] }} ·
            {{ r.generator_type === "mock" ? "Mock" : "模型辅助"
            }}{{ r.contains_finance ? " · 含受限财务" : "" }}</small
          >
        </button>
        <ElButton
          v-if="auth.can(r.project_id)"
          class="report-delete-button"
          type="danger"
          native-type="button"
          link
          :disabled="busy"
          :aria-label="`删除报告 ${displayTime(r.generated_at)}`"
          @click="
            deleting = r;
            error = '';
            success = '';
          "
          >删除</ElButton
        >
      </div>
    </section>
    <section class="card report-preview">
      <div v-if="busy" class="empty">正在读取事实或生成报告…</div>
      <template v-else-if="selected"
        ><div class="section-title">
          <h2>项目阶段评价报告</h2>
          <span class="badge">{{ reportStatus[selected.review_status] }}</span>
        </div>
        <p class="muted">
          {{ selected.fact_bundle_json.metric_payload.project_code }} · 截止
          {{ selected.fact_bundle_json.metric_payload.as_of_date }} ·
          {{ selected.fact_bundle_json.metric_payload.plan_version_label }}
        </p>
        <p class="notice warning">
          {{ selected.validation_json.label
          }}{{ selected.contains_finance ? " · 含受限财务数据" : "" }}
        </p>
        <div class="report-stats">
          <div>
            <small>应完成</small
            ><strong>{{
              selected.fact_bundle_json.metric_payload.counts.due_total
            }}</strong>
          </div>
          <div>
            <small>按期率（试算）</small
            ><strong
              >{{
                selected.fact_bundle_json.metric_payload.counts
                  .on_time_rate_pct ?? "—"
              }}%</strong
            >
          </div>
          <div>
            <small>延期完成</small
            ><strong>{{
              selected.fact_bundle_json.metric_payload.counts.late_completed
            }}</strong>
          </div>
          <div>
            <small>待核对</small
            ><strong>{{
              selected.fact_bundle_json.metric_payload.counts
                .pending_verification
            }}</strong>
          </div>
        </div>
        <ReportContent :content="selected.content" />
        <details class="report-sources">
          <summary>事实引用与来源摘要</summary>
          <p>
            快照 {{ selected.metric_snapshot_id }}<br />摘要
            {{ selected.fact_bundle_json.source_digest }}
          </p>
          <p v-for="fact in selected.fact_bundle_json.facts" :key="fact.id">
            [{{ fact.id }}] {{ fact.text }}
          </p>
        </details>
        <h3>报告审核记录</h3>
        <p v-if="!selected.reviews.length" class="muted">尚无审核记录。</p>
        <p v-for="r in selected.reviews" :key="r.reviewed_at">
          {{ reportStatus[r.decision] }} · {{ r.comment }} ·
          {{ r.reviewer_id }} · {{ r.reviewed_at }}
        </p>
        <div class="actions">
          <ElButton
            v-if="
              ['draft', 'returned'].includes(selected.review_status) &&
              auth.can(selected.project_id)
            "
            :disabled="busy"
            @click="submit"
            native-type="submit"
          >
            提交报告审核</ElButton
          ><ElButton
            v-if="
              selected.review_status === 'pending_review' &&
              auth.can(selected.project_id, 'review')
            "
            :disabled="!canReview || busy"
            @click="
              reviewOpen = true;
              comment = '';
              decision = 'approved';
            "
            native-type="submit"
          >
            独立报告审核</ElButton
          ><a
            class="button primary"
            :href="`/api/v1/reports/${selected.id}/export`"
            ><Icon name="imgVectorFileDown" />导出报告 HTML</a
          >
        </div>
        <p class="muted">
          导出保留 Mock、草稿/批准状态及快照依据；不是自动发布。
        </p></template
      >
      <div v-else class="empty">
        <h2>报告预览</h2>
        <p>选择项目和业务截止日，从真实 API 数据生成草稿。</p>
        <p>尚无生效计划的项目无法生成评价报告。</p>
      </div>
    </section>
  </div>
  <Modal
    v-if="deleting"
    title="删除报告"
    :busy="busy"
    @close="deleting = undefined"
  >
    <p>
      确认删除 {{ displayTime(deleting.generated_at) }} 生成的{{
        reportStatus[deleting.review_status]
      }}报告？
    </p>
    <p class="muted">
      删除后将从报告列表和预览中移除，冻结事实、审核记录和操作日志仍保留。
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template #footer>
      <ElButton
        :disabled="busy"
        @click="deleting = undefined"
        native-type="button"
        >取消</ElButton
      >
      <ElButton
        :disabled="busy"
        :loading="busy"
        @click="removeReport"
        type="danger"
        native-type="button"
        >确认删除</ElButton
      >
    </template>
  </Modal>
  <Modal
    v-if="reviewOpen && selected"
    title="独立报告审核"
    :busy="busy"
    @close="reviewOpen = false"
    ><p>请核对冻结事实、来源与试算口径。本次审核不会修改报告正文。</p>
    <form id="report-review" @submit.prevent="review">
      <label
        >报告审核结论<FormSelect
          v-model="decision"
          :aria-label="'报告审核结论'"
        >
          <ElOption data-ui-value="approved" value="approved" :label="'批准'" />
          <ElOption
            data-ui-value="returned"
            value="returned"
            :label="'退回'"
          /> </FormSelect></label
      ><label
        >报告审核依据 *<ElInput
          v-model="comment"
          required
          maxlength="500"
          type="textarea"
          :aria-label="'报告审核依据 *'"
        />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
    <template #footer
      ><ElButton
        form="report-review"
        class="primary"
        :disabled="busy"
        native-type="submit"
        type="primary"
      >
        确认报告审核
      </ElButton></template
    ></Modal
  >
</template>

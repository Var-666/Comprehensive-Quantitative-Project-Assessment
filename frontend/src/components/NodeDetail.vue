<script setup lang="ts">
import { useUnsavedChanges } from "../useUnsavedChanges";
import OperationToast from "./OperationToast.vue";
import { ElButton } from "element-plus/es/components/button/index";
import { ElInput } from "element-plus/es/components/input/index";
import FormSelect from "./FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import FormDate from "./FormDate.vue";
import { computed, onMounted, reactive, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import type { Milestone } from "../types";
import { statuses } from "../types";
import { displayTime } from "../llmTypes";
import Modal from "./Modal.vue";
import StatusBadge from "./StatusBadge.vue";
import { useAuth, useCatalog } from "../store";
import NodeActions from "./NodeActions.vue";
import NodeConfiguration from "./NodeConfiguration.vue";
const auth = useAuth();
const catalog = useCatalog();
const props = defineProps<{
  node: Milestone;
  planId: string;
  justCreated?: boolean;
}>();
const emit = defineEmits<{
  close: [];
  changed: [];
  continue: [];
  approve: [];
}>();
const nodeActions = ref<InstanceType<typeof NodeActions>>();
const detail = ref<Milestone>(props.node),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  comment = ref("");
const cancelReason = ref("");
const section = ref(props.justCreated ? "configuration" : "info");
const auditLabels: Record<string, string> = {
  create: "新增节点",
  edit_draft: "修改节点计划",
  cancel_milestone: "取消节点",
  submit_actual: "提交实际记录",
  complete_milestone_from_tasks: "提交节点完成记录",
  verify: "核实实际记录",
  supersede_fact: "替换原核实记录",
  sample_fact: "导入示例实际记录",
};
const historyFields: Record<string, string> = {
  milestone_code: "节点编号",
  milestone_name: "节点名称",
  node_type_code: "节点类型",
  planned_date: "计划日期",
  date_kind: "日期性质",
  department_id: "责任部门",
  owner_id: "责任人",
  source_ref: "日期依据",
  change_reason: "变更原因",
  is_included: "计划范围",
  lifecycle_status: "节点状态",
  completion_flag: "完成情况",
  actual_date: "实际完成日期",
  evidence_ref: "核实依据",
  verification_status: "核实结果",
  comment: "核实意见",
  is_current: "当前核实事实",
  tracking_only: "仅时间记录",
};
function historyValue(key: string, value: unknown): string {
  if (key === "completion_flag")
    return value === true ? "已完成" : value === false ? "尚未完成" : "待确认";
  if (value === null || value === undefined || value === "") return "未填写";
  if (key === "department_id")
    return (
      catalog.departments.find((d) => d.id === value)?.dept_name ||
      "原部门已不可用"
    );
  if (key === "owner_id")
    return (
      catalog.users.find((u) => u.id === value)?.display_name ||
      "原责任人已不可用"
    );
  if (key === "node_type_code")
    return (
      catalog.nodeTypes.find((t) => t.code === value)?.display_name ||
      "原节点类型已不可用"
    );
  if (key === "date_kind")
    return (
      (
        {
          internal_plan: "内部计划",
          contractual: "合同约定",
          unconfirmed: "待确认",
        } as Record<string, string>
      )[String(value)] || "未记录"
    );
  if (key === "lifecycle_status")
    return value === "cancelled" ? "已取消" : "正常";
  if (key === "verification_status") return statuses[String(value)] || "未记录";
  if (key === "is_included") return value ? "纳入计划" : "移出计划";
  if (key === "is_current" || key === "tracking_only")
    return value ? "是" : "否";
  return String(value);
}
const auditEntries = computed(() =>
  (detail.value.audit_events || []).map((event) => ({
    ...event,
    title: auditLabels[event.action] || "更新节点记录",
    changes: Object.entries(historyFields)
      .filter(
        ([key]) =>
          (key in (event.after_json || {}) ||
            key in (event.before_json || {})) &&
          (event.before_json
            ? event.before_json[key] !== event.after_json?.[key]
            : key !== "is_current" &&
              event.after_json?.[key] !== null &&
              event.after_json?.[key] !== ""),
      )
      .map(([key, label]) => ({
        label,
        before:
          event.before_json && key !== "change_reason"
            ? historyValue(key, event.before_json[key])
            : null,
        after: historyValue(key, event.after_json?.[key]),
      })),
  })),
);
function jump(event: Event, value: string) {
  const dialog = (event.currentTarget as HTMLElement).closest(".modal");
  const body = dialog?.querySelector<HTMLElement>(".modal-body");
  const target = dialog?.querySelector<HTMLElement>(
    `[data-node-section="${value}"]`,
  );
  if (!body || !target) return;
  section.value = value;
  body.scrollTop +=
    target.getBoundingClientRect().top - body.getBoundingClientRect().top - 20;
}
async function confirmClose() {
  return (
    !nodeActions.value?.busy &&
    (await guard.confirmDiscard()) &&
    (await (nodeActions.value?.confirmDiscard() ?? true))
  );
}
async function continueAdding() {
  if (await confirmClose()) emit("continue");
}
async function approvePlan() {
  if (await confirmClose()) emit("approve");
}
function openActions(event: Event, select: boolean) {
  jump(event, "actions");
  if (select) void nodeActions.value?.open();
}
async function cancelNode() {
  busy.value = true;
  error.value = "";
  try {
    await api(`/milestones/${props.node.id}/cancel`, {
      method: "POST",
      headers: versionHeader(detail.value.row_version),
      body: json({ reason: cancelReason.value }),
    });
    await load();
    guard.markSaved(["cancelReason"]);
    success.value = "节点已取消，旧待发提醒已失效，历史保留";
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
const form = reactive({
  completion_flag: "unknown",
  actual_date: "",
  evidence_ref: "",
});
const guard = useUnsavedChanges(
  () => ({ form, comment: comment.value, cancelReason: cancelReason.value }),
  () => true,
  () => busy.value,
);
async function load() {
  error.value = "";
  try {
    detail.value = await api<Milestone>(
      `/milestones/${props.node.id}?plan_version_id=${props.planId}`,
    );
  } catch (e) {
    error.value = errorMessage(e);
  }
}
async function recheck() {
  await load();
  if (!error.value) {
    await nodeActions.value?.refresh();
    emit("changed");
  }
}
async function submit() {
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await api(`/milestones/${props.node.id}/actuals`, {
      method: "POST",
      body: json({
        completion_flag:
          form.completion_flag === "unknown"
            ? null
            : form.completion_flag === "true",
        actual_date: form.completion_flag === "true" ? form.actual_date : null,
        evidence_ref: form.evidence_ref,
      }),
    });
    success.value = "实际记录已提交，仍需独立核实";
    form.evidence_ref = "";
    guard.markSaved(["form"]);
    await load();
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function verify(id: string, decision: string) {
  if (!comment.value.trim()) {
    error.value = "请填写核实意见";
    return;
  }
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await api(`/milestone-actuals/${id}/verify`, {
      method: "POST",
      body: json({ decision, comment: comment.value }),
    });
    success.value = "核实结果已记录";
    comment.value = "";
    guard.markSaved(["comment"]);
    await load();
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <Modal
    class="node-detail"
    :before-close="confirmClose"
    :title="`${detail.milestone_code} · 节点详情`"
    :subtitle="detail.milestone_name"
    drawer
    :busy="busy"
    @close="emit('close')"
  >
    <template #navigation
      ><nav class="drawer-tabs" aria-label="节点详情区段">
        <ElButton
          v-for="(title, key) in {
            configuration: '配置检查',
            info: '节点信息',
            actions: '标准动作',
            records: '执行记录',
            history: '变更历史',
          }"
          :key="key"
          :class="{ active: section === key }"
          @click="jump($event, key)"
          native-type="submit"
        >
          {{ title }}
        </ElButton>
      </nav></template
    >
    <p v-if="error" class="error" role="alert">
      {{ error }} <ElButton @click="recheck">重试配置检查</ElButton>
    </p>
    <OperationToast v-model="success" :busy="busy" />
    <div data-node-section="configuration">
      <NodeConfiguration
        v-if="detail.configuration"
        :configuration="detail.configuration"
        :saved="justCreated"
        @actions="openActions"
        @approve="approvePlan"
        @refresh="recheck"
      />
      <p v-else-if="!error" role="status">正在检查节点配置…</p>
    </div>
    <section class="form-section" data-node-section="info">
      <h3>
        {{ detail.milestone_name }}
        <StatusBadge :value="detail.verification_status" />
      </h3>
      <dl class="details">
        <div>
          <dt>计划日期</dt>
          <dd>{{ detail.plan_item.planned_date }}</dd>
        </div>
        <div>
          <dt>当前已核实实际日期</dt>
          <dd>
            {{ detail.current_actual?.actual_date || "未知 / 尚未确认完成" }}
          </dd>
        </div>
        <div>
          <dt>责任部门</dt>
          <dd>{{ detail.department_name || "未指定" }}</dd>
        </div>
        <div>
          <dt>日期依据</dt>
          <dd>{{ detail.plan_item.source_ref || "未录入" }}</dd>
        </div>
      </dl>
    </section>
    <section v-if="detail.plan_change" class="notice">
      <strong
        >本版{{
          detail.plan_change.kind === "added"
            ? "新增节点"
            : detail.plan_change.kind === "removed"
              ? "移出计划"
              : "节点变更"
        }}</strong
      >
      <p v-if="detail.plan_change.old_date">
        计划日期：{{ detail.plan_change.old_date }} →
        {{ detail.plan_change.new_date
        }}<template v-if="detail.plan_change.delta_days">
          · {{ detail.plan_change.delta_days > 0 ? "后延" : "提前"
          }}{{ Math.abs(detail.plan_change.delta_days) }}天</template
        >
      </p>
      <p>变更原因：{{ detail.plan_change.reason }}</p>
    </section>
    <div data-node-section="actions">
      <NodeActions
        ref="nodeActions"
        :key="detail.plan_item.id"
        :node="detail"
        :plan-id="planId"
        @changed="
          load();
          emit('changed');
        "
      />
    </div>
    <section v-if="auth.can(detail.project_id)" class="form-section">
      <details v-if="detail.lifecycle_status === 'active'">
        <summary>取消节点</summary>
        <p class="notice">
          取消后不再产生新提醒。未发送旧稿会失效，已发送和执行记录保留。
        </p>
        <form @submit.prevent="cancelNode">
          <label
            >业务取消原因 *<ElInput
              v-model="cancelReason"
              required
              maxlength="500"
              type="textarea"
              :aria-label="'业务取消原因 *'" /></label
          ><ElButton :disabled="busy" native-type="submit"
            >确认取消节点</ElButton
          >
        </form>
      </details>
      <p v-else class="notice">节点已取消，保留历史计划及事实记录。</p>
    </section>
    <section v-if="auth.can(detail.project_id)" class="form-section">
      <h3>提交实际记录</h3>
      <form @submit.prevent="submit">
        <div class="form-grid">
          <label
            >完成事实<FormSelect
              v-model="form.completion_flag"
              aria-label="完成事实"
            >
              <ElOption
                data-ui-value="unknown"
                value="unknown"
                :label="'未知 / 待核对'"
              />
              <ElOption
                data-ui-value="true"
                value="true"
                :label="'已完成（待核实）'"
              />
              <ElOption
                data-ui-value="false"
                value="false"
                :label="'尚未完成（待核实）'"
              /> </FormSelect></label
          ><label
            >实际完成日期<FormDate
              v-model="form.actual_date"
              :disabled="form.completion_flag !== 'true'"
              :required="form.completion_flag === 'true'"
              :aria-label="'实际完成日期'"
          /></label>
        </div>
        <label
          >来源 / 证据说明 *<ElInput
            v-model="form.evidence_ref"
            required
            maxlength="500"
            :rows="2"
            type="textarea"
            :aria-label="'来源 / 证据说明 *'"
          />
        </label>
        <p class="muted">
          来源说明不等于正式证据附件。提交不改变已核实事实，也不代表节点已完成。
        </p>
        <ElButton
          class="primary"
          :disabled="busy"
          native-type="submit"
          type="primary"
          >提交实际记录</ElButton
        >
      </form>
    </section>
    <section class="form-section" data-node-section="records">
      <h3>实际记录与独立核实</h3>
      <p class="notice warning">
        仅本项目审核人员可以核实；提交人不能核实自己的记录。
      </p>
      <label
        >核实意见<ElInput
          v-model="comment"
          maxlength="2000"
          :aria-label="'核实意见'"
      /></label>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>提交时间</th>
              <th>完成事实</th>
              <th>实际日期</th>
              <th>核实状态</th>
              <th>来源</th>
              <th>审核操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in detail.actual_records" :key="a.id">
              <td>{{ displayTime(a.submitted_at) }}</td>
              <td>
                {{
                  a.completion_flag === true
                    ? "已完成"
                    : a.completion_flag === false
                      ? "尚未完成"
                      : "未知"
                }}<small v-if="a.is_current" class="subline"
                  >当前核实事实</small
                >
              </td>
              <td>{{ a.actual_date || "—" }}</td>
              <td><StatusBadge :value="a.verification_status" /></td>
              <td>
                {{ a.evidence_ref
                }}<small v-if="a.comment" class="subline">{{
                  a.comment
                }}</small>
              </td>
              <td>
                <div
                  v-if="
                    a.verification_status === 'submitted' &&
                    auth.can(detail.project_id, 'review') &&
                    a.submitted_by !== auth.user?.user_id
                  "
                  class="actions"
                >
                  <ElButton
                    :disabled="busy"
                    @click="verify(a.id, 'verified')"
                    native-type="submit"
                  >
                    确认核实</ElButton
                  ><ElButton
                    :disabled="busy"
                    @click="verify(a.id, 'returned')"
                    native-type="submit"
                  >
                    退回</ElButton
                  ><ElButton
                    :disabled="busy"
                    @click="verify(a.id, 'disputed')"
                    native-type="submit"
                  >
                    争议
                  </ElButton>
                </div>
                <span v-else>已处理</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!detail.actual_records.length" class="empty">尚无实际记录</p>
    </section>
    <section class="form-section" data-node-section="history">
      <h3>计划版本记录</h3>
      <ul class="node-version-list">
        <li v-for="p in detail.history" :key="p.id">
          <header>
            <strong>{{ p.version_label }}</strong
            ><StatusBadge :value="p.version_status" />
          </header>
          <dl class="node-history-facts">
            <div>
              <dt>节点名称</dt>
              <dd>{{ p.milestone_name }}</dd>
            </div>
            <div>
              <dt>计划日期</dt>
              <dd>{{ p.planned_date }}</dd>
            </div>
          </dl>
          <p class="muted">{{ p.change_reason || "未填写变更原因" }}</p>
        </li>
      </ul>
      <p v-if="!detail.history?.length" class="muted">暂无计划版本记录</p>
    </section>
    <section class="form-section">
      <h3>操作记录</h3>
      <ol class="node-audit-list">
        <li v-for="e in auditEntries" :key="e.id">
          <strong>{{ e.title }}</strong>
          <p class="muted">
            {{ e.actor_name || "历史操作人未记录" }} ·
            <time :datetime="e.occurred_at">{{
              displayTime(e.occurred_at)
            }}</time>
          </p>
          <dl class="node-audit-changes">
            <div v-for="change in e.changes" :key="change.label">
              <dt>{{ change.label }}</dt>
              <dd>
                <template v-if="change.before !== null"
                  ><span class="muted">{{ change.before }}</span> → </template
                >{{ change.after }}
              </dd>
            </div>
          </dl>
        </li>
      </ol>
      <p v-if="!auditEntries.length" class="muted">暂无操作记录</p>
    </section>
    <template #footer="{ close }"
      ><ElButton :disabled="busy" @click="close" native-type="submit">{{
        justCreated ? "返回节点列表" : "关闭"
      }}</ElButton>
      <ElButton
        v-if="justCreated"
        :disabled="busy"
        type="primary"
        @click="continueAdding"
        >继续添加节点</ElButton
      >
    </template>
  </Modal>
</template>

<style>
.node-detail .modal-body,
.node-detail .modal-body > div[data-node-section] {
  display: grid;
  align-content: start;
  gap: 16px;
}
.node-detail .modal-body > *,
.node-detail [data-node-section] > .form-section {
  min-width: 0;
  margin-block: 0;
}
.node-detail .form-section > h3 {
  margin: 0 0 16px;
}
.node-detail .form-section > :last-child {
  margin-bottom: 0;
}
</style>
<style scoped>
.node-version-list,
.node-audit-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.node-version-list li {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.node-version-list li + li {
  margin-top: 12px;
}
.node-version-list header {
  display: flex;
  align-items: center;
  gap: 10px;
}
.node-history-facts {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  margin: 12px 0;
}
.node-history-facts dt,
.node-audit-changes dt {
  color: var(--muted);
  font-size: 12px;
}
.node-history-facts dd,
.node-audit-changes dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}
.node-version-list p {
  margin: 0;
  overflow-wrap: anywhere;
}
.node-audit-list li {
  position: relative;
  border-left: 2px solid var(--line);
  padding: 0 0 22px 18px;
  margin-left: 5px;
}
.node-audit-list li:last-child {
  padding-bottom: 0;
}
.node-audit-list li::before {
  content: "";
  position: absolute;
  left: -6px;
  top: 5px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--blue);
}
.node-audit-list p {
  margin: 6px 0 10px;
  font-size: 12px;
}
.node-audit-changes {
  margin: 0;
  display: grid;
  gap: 8px;
}
.node-audit-changes > div {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 8px;
}
.node-audit-changes dd {
  margin: 0;
}
</style>

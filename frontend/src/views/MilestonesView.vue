<script setup lang="ts">
import { useUnsavedChanges } from "../useUnsavedChanges";
import OperationToast from "../components/OperationToast.vue";
import PageNavigation from "../components/PageNavigation.vue";
import StatCard from "../components/StatCard.vue";
import {
  List,
  CircleCheck,
  Calendar,
  Clock,
  Warning,
} from "@element-plus/icons-vue";
import { ElButton } from "element-plus/es/components/button/index";
import FormSelect from "../components/FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import { ElInput } from "element-plus/es/components/input/index";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, errorMessage, json, versionHeader } from "../api";
import { useCatalog, useAuth } from "../store";
const auth = useAuth();
import type { Milestone, Page, Plan, Project } from "../types";
import { statuses } from "../types";
import Icon from "../components/Icon.vue";
import NodeForm from "../components/NodeForm.vue";
import NodeDetail from "../components/NodeDetail.vue";
import Modal from "../components/Modal.vue";
import StatusBadge from "../components/StatusBadge.vue";
import TimelineDot from "../components/TimelineDot.vue";
import { businessToday, categoryLabels, type Metric } from "../evaluationTypes";
const route = useRoute(),
  router = useRouter(),
  catalog = useCatalog();
const projectOptions = ref<Project[]>([]),
  projectId = ref(String(route.query.project || "")),
  project = ref<Project>(),
  plans = ref<Plan[]>([]),
  planId = ref("");
const selectedPlan = computed(() =>
  plans.value.find((p) => p.id === planId.value),
);
const nodePageSize = 10;
const nodes = ref<Page<Milestone>>({
    items: [],
    total: 0,
    page: 1,
    page_size: nodePageSize,
  }),
  error = ref(""),
  busy = ref(false),
  success = ref("");
const type = ref(""),
  department = ref(""),
  showForm = ref(false),
  editing = ref<Milestone>(),
  showing = ref<Milestone>(),
  planDialog = ref<"create" | "activate">(),
  reason = ref(""),
  planBusy = ref(false),
  planError = ref("");
const canEdit = computed(
  () =>
    selectedPlan.value?.status === "draft" &&
    auth.can(projectId.value) &&
    project.value?.project_status !== "archived",
);
const metric = ref<Metric>(),
  metricError = ref("");
const nodeCategory = (node: Milestone) =>
  metric.value?.evidence.find((row) => row.milestone_id === node.id)?.category;
let projectRequest = 0,
  nodeRequest = 0;
async function loadOptions() {
  const items: Project[] = [];
  let page = 1;
  while (true) {
    const r = await api<Page<Project>>(`/projects?page_size=100&page=${page}`);
    items.push(...r.items);
    if (items.length >= r.total) break;
    page++;
  }
  projectOptions.value = items;
}
async function loadProject(preserve = false) {
  if (!projectId.value) return;
  const request = ++projectRequest;
  ++nodeRequest;
  const id = projectId.value;
  busy.value = true;
  error.value = "";
  if (!preserve) {
    project.value = undefined;
    plans.value = [];
    planId.value = "";
    metric.value = undefined;
    nodes.value = { items: [], total: 0, page: 1, page_size: nodePageSize };
  }
  try {
    const [p, v] = await Promise.all([
      api<Project>(`/projects/${id}`),
      api<Plan[]>(`/projects/${id}/plan-versions`),
    ]);
    if (request !== projectRequest) return;
    project.value = p;
    plans.value = v;
    if (!preserve || !v.some((x) => x.id === planId.value))
      planId.value =
        v.find((x) => x.id === route.query.plan)?.id ||
        p.current_plan_version_id ||
        v[0]?.id ||
        "";
    await loadNodes();
    if (request === projectRequest)
      void router.replace({ query: { project: id, plan: planId.value } });
  } catch (e) {
    if (request === projectRequest) error.value = errorMessage(e);
  } finally {
    if (request === projectRequest) busy.value = false;
  }
}
async function loadNodes(page = 1) {
  const request = ++nodeRequest;
  if (!planId.value) return;
  const id = projectId.value,
    plan = planId.value;
  const effective = selectedPlan.value?.status !== "draft";
  busy.value = true;
  error.value = "";
  metric.value = undefined;
  metricError.value = "";
  try {
    const q = new URLSearchParams({
      plan_version_id: plan,
      type: type.value,
      department: department.value,
      page: String(page),
      page_size: String(nodePageSize),
    });
    const result = await api<Page<Milestone>>(
      `/projects/${id}/milestones?${q}`,
    );
    if (request !== nodeRequest) return;
    nodes.value = result;
    if (effective) {
      try {
        const result = await api<Metric>(
          `/projects/${id}/metrics?as_of=${businessToday()}&plan_version_id=${plan}`,
        );
        if (request === nodeRequest) metric.value = result;
      } catch (e) {
        if (request === nodeRequest) metricError.value = errorMessage(e);
      }
    }
  } catch (e) {
    if (request === nodeRequest) error.value = errorMessage(e);
  } finally {
    if (request === nodeRequest) busy.value = false;
  }
}
function edit(node?: Milestone) {
  editing.value = node;
  showForm.value = true;
}
const planGuard = useUnsavedChanges(
  () => ({ reason: reason.value }),
  () => !!planDialog.value,
  () => planBusy.value,
);
async function savePlan() {
  planBusy.value = true;
  planError.value = "";
  try {
    if (planDialog.value === "create") {
      const p = await api<Plan>(`/projects/${projectId.value}/plan-versions`, {
        method: "POST",
        headers: versionHeader(project.value!.row_version),
        body: json({
          base_version_id: project.value!.current_plan_version_id,
          change_reason: reason.value,
        }),
      });
      planId.value = p.id;
    } else {
      await api(`/plan-versions/${planId.value}/activate`, {
        method: "POST",
        headers: versionHeader(selectedPlan.value!.row_version),
        body: json({ approval_ref: reason.value }),
      });
    }
    planDialog.value = undefined;
    success.value = "计划操作已记录";
    await loadProject(true);
  } catch (e) {
    planError.value = errorMessage(e);
  } finally {
    planBusy.value = false;
  }
}
onMounted(async () => {
  busy.value = true;
  try {
    await Promise.all([loadOptions(), catalog.load()]);
    if (!projectId.value) projectId.value = projectOptions.value[0]?.id || "";
    await loadProject();
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
      <h1>项目节点管理</h1>
      <p>支持计划版本、变更记录与独立实际核实 · 本地演示</p>
    </div>
    <ElButton
      class="primary"
      :disabled="!canEdit"
      :title="canEdit ? '新增草稿节点' : '请先选择或新建草稿版本'"
      @click="edit()"
      native-type="submit"
      type="primary"
    >
      <Icon name="imgVectorPlus" />添加节点
    </ElButton>
  </div>
  <section class="card filters">
    <label
      >所属项目<FormSelect
        v-model="projectId"
        @change="
          type = '';
          department = '';
          loadProject();
        "
        :aria-label="'所属项目'"
      >
        <ElOption data-ui-value="" value="" disabled :label="'请选择项目'" />
        <ElOption
          :data-ui-value="p.id"
          v-for="p in projectOptions"
          :key="p.id"
          :value="p.id"
          :label="String(p.project_code) + ' · ' + String(p.project_name)"
        /> </FormSelect></label
    ><label
      >计划版本<FormSelect
        v-model="planId"
        aria-label="计划版本"
        :disabled="busy"
        @change="loadNodes()"
      >
        <ElOption
          :data-ui-value="p.id"
          v-for="p in plans"
          :key="p.id"
          :value="p.id"
          :label="String(p.version_label) + ' · ' + String(statuses[p.status])"
        /> </FormSelect></label
    ><ElButton
      :disabled="
        !project ||
        !auth.can(projectId) ||
        plans.some((p) => p.status === 'draft') ||
        project.project_status === 'archived'
      "
      @click="
        reason = '';
        planError = '';
        planDialog = 'create';
      "
      native-type="submit"
    >
      新建变更草稿</ElButton
    ><ElButton
      :disabled="
        selectedPlan?.status !== 'draft' ||
        !auth.can(projectId, 'review') ||
        selectedPlan.editor_ids.includes(auth.user?.user_id || '')
      "
      @click="
        reason = '';
        planError = '';
        planDialog = 'activate';
      "
      native-type="submit"
    >
      批准生效
    </ElButton>
    <div v-if="project" class="project-context-meta">
      <strong>{{ project.department_name || "未指定部门" }}</strong
      ><small>{{ project.owner_name || "未指定负责人" }}</small>
    </div>
  </section>
  <p v-if="error" class="error" role="alert">
    {{ error }}
    <ElButton @click="loadProject(true)" native-type="submit"
      >刷新重试</ElButton
    >
  </p>
  <OperationToast v-model="success" :busy="busy" />
  <p v-if="!projectId && !busy" class="card empty">
    暂无项目。<RouterLink to="/projects">先创建项目</RouterLink>
  </p>
  <template v-if="project && selectedPlan">
    <div class="node-stat-grid">
      <StatCard
        class="node-stat"
        label="全部计划节点"
        :value="metric ? metric.evidence.length : nodes.total"
        :icon="List"
        compact
      />
      <StatCard
        class="node-stat"
        label="已核实完成"
        :value="metric ? metric.counts.verified_completed : '—'"
        :icon="CircleCheck"
        tone="green"
        compact
      />
      <StatCard
        class="node-stat"
        label="尚未到期"
        :value="metric?.counts.not_due ?? '—'"
        :icon="Calendar"
        compact
      />
      <StatCard
        class="node-stat"
        label="待核对"
        :value="metric?.counts.pending_verification ?? '—'"
        :icon="Clock"
        tone="amber"
        compact
      />
      <StatCard
        class="node-stat"
        label="延期完成"
        :value="metric?.counts.late_completed ?? '—'"
        :icon="Warning"
        tone="red"
        compact
      />
    </div>
    <p v-if="metricError" class="error" role="alert">
      统计暂不可用：{{ metricError }}
      <ElButton @click="loadNodes(nodes.page)" native-type="submit"
        >重试统计</ElButton
      >
    </p>
    <p v-if="selectedPlan.status === 'draft'" class="muted">
      草稿尚未批准，不计算正式节点评价；批准后显示统计。
    </p>

    <section class="card timeline-card">
      <div class="section-title">
        <div class="timeline-heading">
          <h3>关键里程碑时间轴</h3>
          <p class="muted">
            按计划日期排序 · 当前页前 8 条 · {{ selectedPlan.version_label }}
          </p>
        </div>
        <small class="muted">{{
          metric ? `统计截止 ${metric.as_of_date}` : "草稿未评价"
        }}</small>
      </div>
      <div v-if="nodes.items.length" class="timeline-scroll">
        <div class="timeline milestone-timeline">
          <button
            v-for="n in nodes.items.slice(0, 8)"
            :key="n.id"
            class="step-card"
            :class="nodeCategory(n)"
            @click="showing = n"
            type="button"
          >
            <TimelineDot :category="nodeCategory(n)" /><small>{{
              n.node_type_code
            }}</small
            ><strong>{{ n.milestone_name }}</strong
            ><span>计划 {{ n.plan_item.planned_date }}</span
            ><span
              >核实实际 {{ n.current_actual?.actual_date || "待确认" }}</span
            ><span
              v-if="nodeCategory(n)"
              class="badge"
              :class="nodeCategory(n)"
              >{{ categoryLabels[nodeCategory(n)!] }}</span
            ><StatusBadge v-else :value="n.verification_status" />
          </button>
        </div>
      </div>
      <p v-else class="empty">该版本暂无节点</p>
    </section>
    <details v-if="!canEdit" class="plan-readonly-note">
      <summary>生效及历史计划只读 · 查看版本和核实说明</summary>
      生效及历史计划只读。调整计划请先创建变更草稿，原版本会完整保留。核实事实独立于计划版本。
    </details>
    <section class="card table-card">
      <div class="section-title">
        <h3>节点明细台账</h3>
        <div class="actions">
          <ElButton
            :disabled="!canEdit"
            @click="
              router.push({
                path: '/imports',
                query: {
                  target: 'milestones',
                  project: projectId,
                  plan: planId,
                },
              })
            "
            native-type="submit"
          >
            <Icon name="imgVectorFileUp" />导入 Excel</ElButton
          ><ElButton :disabled="!canEdit" @click="edit()" native-type="submit"
            >添加节点</ElButton
          >
        </div>
      </div>
      <div class="filters compact">
        <label
          >节点类型<FormSelect
            v-model="type"
            @change="loadNodes()"
            :aria-label="'节点类型'"
          >
            <ElOption data-ui-value="" value="" :label="'全部'" />
            <ElOption
              :data-ui-value="t.code"
              v-for="t in catalog.nodeTypes"
              :key="t.code"
              :value="t.code"
              :label="String(t.display_name)"
            /> </FormSelect></label
        ><label
          >责任部门<FormSelect
            v-model="department"
            @change="loadNodes()"
            :aria-label="'责任部门'"
          >
            <ElOption data-ui-value="" value="" :label="'全部'" />
            <ElOption
              :data-ui-value="d.id"
              v-for="d in catalog.departments"
              :key="d.id"
              :value="d.id"
              :label="String(d.dept_name)"
            /> </FormSelect
        ></label>
      </div>
      <p v-if="busy" class="empty" role="status">正在加载节点…</p>
      <div v-else-if="nodes.items.length" class="table-wrap">
        <table class="milestone-list-table">
          <thead>
            <tr>
              <th>节点编号</th>
              <th>节点名称</th>
              <th>节点类型</th>
              <th>计划日期</th>
              <th>核实实际日期</th>
              <th>责任部门</th>
              <th>核实状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="n in nodes.items" :key="n.id">
              <td>{{ n.milestone_code }}</td>
              <td>{{ n.milestone_name }}</td>
              <td>{{ n.node_type_code }}</td>
              <td>{{ n.plan_item.planned_date }}</td>
              <td>{{ n.current_actual?.actual_date || "待确认" }}</td>
              <td>{{ n.department_name || "未指定" }}</td>
              <td><StatusBadge :value="n.verification_status" /></td>
              <td>
                <div class="actions">
                  <ElButton
                    class="text-button"
                    @click="showing = n"
                    native-type="submit"
                    link
                  >
                    查看详情</ElButton
                  ><ElButton
                    class="text-button"
                    :disabled="!canEdit"
                    @click="edit(n)"
                    native-type="submit"
                    link
                  >
                    编辑
                  </ElButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">该筛选下暂无节点</p>
      <PageNavigation
        :page="nodes.page"
        :total="nodes.total"
        :page-size="nodePageSize"
        :disabled="busy"
        @change="loadNodes"
      />
    </section>
    <NodeForm
      v-if="showForm"
      :project="project"
      :plan="selectedPlan"
      :node="editing"
      @close="showForm = false"
      @saved="
        showForm = false;
        success = '节点草稿已保存';
        loadProject(true);
      "
    />
    <NodeDetail
      v-if="showing"
      :node="showing"
      :plan-id="planId"
      @close="showing = undefined"
      @changed="loadProject(true)"
    />
    <Modal
      v-if="planDialog"
      :before-close="planGuard.confirmDiscard"
      :title="planDialog === 'create' ? '新建计划变更草稿' : '批准计划生效'"
      :busy="planBusy"
      @close="planDialog = undefined"
      ><form id="plan-form" @submit.prevent="savePlan">
        <p v-if="planError" class="error" role="alert">{{ planError }}</p>
        <p class="notice">
          {{
            planDialog === "create"
              ? "从当前生效版本复制全部节点快照，原版本保持只读。"
              : "仅本项目审核人员可批准。参与编制此版本的人员不能批准自己的计划。"
          }}
        </p>
        <label
          >{{ planDialog === "create" ? "变更原因 *" : "批准依据 *"
          }}<ElInput
            v-model="reason"
            required
            maxlength="500"
            :rows="4"
            type="textarea"
            :aria-label="
              String(planDialog === 'create' ? '变更原因 *' : '批准依据 *')
            "
          />
        </label>
      </form>
      <template #footer="{ close }"
        ><ElButton :disabled="planBusy" @click="close" native-type="submit">
          取消</ElButton
        ><ElButton
          class="primary"
          form="plan-form"
          :disabled="planBusy"
          native-type="submit"
          type="primary"
        >
          {{
            planBusy
              ? "处理中…"
              : planDialog === "create"
                ? "创建变更草稿"
                : "批准计划生效"
          }}
        </ElButton></template
      ></Modal
    >
  </template>
</template>

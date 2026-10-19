<script setup lang="ts">
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
import ImportDialog from "../components/ImportDialog.vue";
import Modal from "../components/Modal.vue";
import StatusBadge from "../components/StatusBadge.vue";
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
const nodes = ref<Page<Milestone>>({
    items: [],
    total: 0,
    page: 1,
    page_size: 100,
  }),
  error = ref(""),
  busy = ref(false),
  success = ref("");
const type = ref(""),
  department = ref(""),
  showForm = ref(false),
  editing = ref<Milestone>(),
  showing = ref<Milestone>(),
  showImport = ref(false),
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
  busy.value = true;
  error.value = "";
  try {
    const [p, v] = await Promise.all([
      api<Project>(`/projects/${projectId.value}`),
      api<Plan[]>(`/projects/${projectId.value}/plan-versions`),
    ]);
    project.value = p;
    plans.value = v;
    if (!preserve || !v.some((x) => x.id === planId.value))
      planId.value = p.current_plan_version_id || v[0]?.id || "";
    await loadNodes();
    void router.replace({ query: { project: projectId.value } });
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function loadNodes(page = 1) {
  if (!planId.value) return;
  busy.value = true;
  error.value = "";
  try {
    const q = new URLSearchParams({
      plan_version_id: planId.value,
      type: type.value,
      department: department.value,
      page: String(page),
    });
    nodes.value = await api<Page<Milestone>>(
      `/projects/${projectId.value}/milestones?${q}`,
    );
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function edit(node?: Milestone) {
  editing.value = node;
  showForm.value = true;
}
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
    <button
      class="primary"
      :disabled="!canEdit"
      :title="canEdit ? '新增草稿节点' : '请先选择或新建草稿版本'"
      @click="edit()"
    >
      <Icon name="imgVectorPlus" />添加节点
    </button>
  </div>
  <section class="card filters">
    <label
      >所属项目<select
        v-model="projectId"
        @change="
          type = '';
          department = '';
          loadProject();
        "
      >
        <option value="" disabled>请选择项目</option>
        <option v-for="p in projectOptions" :key="p.id" :value="p.id">
          {{ p.project_code }} · {{ p.project_name }}
        </option>
      </select></label
    ><label
      >计划版本<select
        v-model="planId"
        aria-label="计划版本"
        @change="loadNodes()"
      >
        <option v-for="p in plans" :key="p.id" :value="p.id">
          {{ p.version_label }} · {{ statuses[p.status] }}
        </option>
      </select></label
    ><button
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
    >
      新建变更草稿</button
    ><button
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
    >
      批准生效
    </button>
  </section>
  <p v-if="error" class="error" role="alert">
    {{ error }} <button @click="loadProject(true)">刷新重试</button>
  </p>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <p v-if="!projectId && !busy" class="card empty">
    暂无项目。<RouterLink to="/projects">先创建项目</RouterLink>
  </p>
  <template v-if="project && selectedPlan">
    <section class="card project-strip">
      <div>
        <strong>{{ project.project_code }} / {{ project.project_name }}</strong
        ><small class="subline"
          >{{ project.department_name || "未指定部门" }} ·
          {{ project.owner_name || "未指定负责人" }}</small
        >
      </div>
      <span
        >本版节点 <b>{{ nodes.total }}</b></span
      ><span>当前查看 {{ selectedPlan.version_label }}</span
      ><StatusBadge :value="selectedPlan.status" />
    </section>
    <p v-if="!canEdit" class="notice">
      生效及历史计划只读。调整计划请先创建变更草稿，原版本会完整保留。核实事实独立于计划版本。
    </p>
    <section class="card timeline-card">
      <div class="section-title">
        <h3>关键里程碑时间轴</h3>
        <span class="muted"
          >按计划日期排序 · 当前页前 8 条 ·
          {{ selectedPlan.version_label }}</span
        >
      </div>
      <div v-if="nodes.items.length" class="timeline">
        <button
          v-for="n in nodes.items.slice(0, 8)"
          :key="n.id"
          class="step-card"
          @click="showing = n"
        >
          <small>{{ n.node_type_code }}</small
          ><strong>{{ n.milestone_name }}</strong
          ><span>计划 {{ n.plan_item.planned_date }}</span
          ><span>核实实际 {{ n.current_actual?.actual_date || "待确认" }}</span
          ><StatusBadge :value="n.verification_status" />
        </button>
      </div>
      <p v-else class="empty">该版本暂无节点</p>
    </section>
    <section class="card table-card">
      <div class="section-title">
        <h3>节点明细台账</h3>
        <div class="actions">
          <button :disabled="!canEdit" @click="showImport = true">
            <Icon name="imgVectorFileUp" />导入 Excel</button
          ><button :disabled="!canEdit" @click="edit()">添加节点</button>
        </div>
      </div>
      <div class="filters compact">
        <label
          >节点类型<select v-model="type" @change="loadNodes()">
            <option value="">全部</option>
            <option
              v-for="t in catalog.nodeTypes"
              :key="t.code"
              :value="t.code"
            >
              {{ t.display_name }}
            </option>
          </select></label
        ><label
          >责任部门<select v-model="department" @change="loadNodes()">
            <option value="">全部</option>
            <option v-for="d in catalog.departments" :key="d.id" :value="d.id">
              {{ d.dept_name }}
            </option>
          </select></label
        >
      </div>
      <p v-if="busy" class="empty" role="status">正在加载节点…</p>
      <div v-else-if="nodes.items.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>节点编号</th>
              <th>节点名称 / 类型</th>
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
              <td>
                {{ n.milestone_name
                }}<small class="subline">{{ n.node_type_code }}</small>
              </td>
              <td>{{ n.plan_item.planned_date }}</td>
              <td>{{ n.current_actual?.actual_date || "待确认" }}</td>
              <td>{{ n.department_name || "未指定" }}</td>
              <td><StatusBadge :value="n.verification_status" /></td>
              <td>
                <div class="actions">
                  <button class="text-button" @click="showing = n">
                    查看详情</button
                  ><button
                    class="text-button"
                    :disabled="!canEdit"
                    @click="edit(n)"
                  >
                    编辑
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">该筛选下暂无节点</p>
      <div class="pagination">
        <span>第 {{ nodes.page }} 页 · 共 {{ nodes.total }} 条</span
        ><button
          :disabled="busy || nodes.page <= 1"
          @click="loadNodes(nodes.page - 1)"
        >
          上一页</button
        ><button
          :disabled="busy || nodes.page * nodes.page_size >= nodes.total"
          @click="loadNodes(nodes.page + 1)"
        >
          下一页
        </button>
      </div>
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
    <ImportDialog
      v-if="showImport"
      :project-id="projectId"
      :plan-id="planId"
      @close="showImport = false"
      @imported="loadProject(true)"
    />
    <Modal
      v-if="planDialog"
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
          }}<textarea v-model="reason" required maxlength="500" rows="4" />
        </label>
      </form>
      <template #footer
        ><button :disabled="planBusy" @click="planDialog = undefined">
          取消</button
        ><button
          class="primary"
          type="submit"
          form="plan-form"
          :disabled="planBusy"
        >
          {{ planBusy ? "处理中…" : "确认" }}
        </button></template
      ></Modal
    >
  </template>
</template>

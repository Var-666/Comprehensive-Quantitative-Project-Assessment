<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, errorMessage, versionHeader } from "../api";
import type { Audit, Page, Project } from "../types";
import { businessToday, categoryLabels, type Metric } from "../evaluationTypes";
import { label, type TaskRecord } from "../workflowTypes";
import ProjectForm from "../components/ProjectForm.vue";
import StatusBadge from "../components/StatusBadge.vue";
import Modal from "../components/Modal.vue";
import ProjectMembers from "../components/ProjectMembers.vue";
import TimelineDot from "../components/TimelineDot.vue";
import { useAuth } from "../store";
const auth = useAuth();
const route = useRoute(),
  router = useRouter();
const project = ref<Project>(),
  events = ref<Audit[]>([]),
  error = ref(""),
  busy = ref(false),
  editing = ref(false),
  archiving = ref(false);
const metric = ref<Metric>(),
  summaryError = ref("");
const tasks = ref<Page<TaskRecord>>({
  items: [],
  total: 0,
  page: 1,
  page_size: 3,
});
async function loadSummary(p: Project) {
  summaryError.value = "";
  metric.value = undefined;
  try {
    const [evaluation, pending] = await Promise.all([
      p.current_plan_version_id
        ? api<Metric>(`/projects/${p.id}/metrics?as_of=${businessToday()}`)
        : Promise.resolve(undefined),
      api<Page<TaskRecord>>(
        `/tasks?project_id=${p.id}&status=todo&page_size=3`,
      ),
    ]);
    metric.value = evaluation;
    tasks.value = pending;
  } catch (e) {
    summaryError.value = errorMessage(e);
  }
}
async function load() {
  busy.value = true;
  error.value = "";
  try {
    const [p, e] = await Promise.all([
      api<Project>(`/projects/${route.params.id}`),
      api<Audit[]>(`/projects/${route.params.id}/audit-events`),
    ]);
    project.value = p;
    events.value = e;
    await loadSummary(p);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function archive() {
  busy.value = true;
  error.value = "";
  try {
    project.value = await api<Project>(`/projects/${project.value!.id}`, {
      method: "DELETE",
      headers: versionHeader(project.value!.row_version),
    });
    archiving.value = false;
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <p v-if="error" class="error" role="alert">
    {{ error }} <button @click="load">刷新</button>
  </p>
  <p v-if="busy" role="status">加载中…</p>
  <template v-if="project"
    ><div class="page-title">
      <div>
        <h1>{{ project.project_code }} · {{ project.project_name }}</h1>
        <p>
          项目管理 / 详情 · 当前计划
          {{ project.current_plan_label || "尚无生效计划" }}
        </p>
      </div>
      <div class="actions">
        <RouterLink class="button" to="/projects">返回项目列表</RouterLink
        ><button :disabled="!auth.can(project.id)" @click="editing = true">
          编辑项目</button
        ><button
          class="primary"
          @click="
            router.push({ path: '/milestones', query: { project: project.id } })
          "
        >
          查看节点计划
        </button>
      </div>
    </div>
    <nav class="project-detail-tabs" aria-label="项目详情导航">
      <span aria-current="page">项目概况</span
      ><RouterLink :to="{ path: '/milestones', query: { project: project.id } }"
        >节点计划</RouterLink
      ><RouterLink
        :to="{ path: '/tasks', query: { tab: 'tasks', project: project.id } }"
        >执行与待办</RouterLink
      ><RouterLink :to="{ path: '/metrics', query: { project: project.id } }"
        >量化评估</RouterLink
      ><a href="#project-audit-history">历史变更</a>
    </nav>
    <section class="card detail-card project-information">
      <h3>项目基本信息 <StatusBadge :value="project.project_status" /></h3>
      <dl class="details">
        <div>
          <dt>项目类型</dt>
          <dd>{{ project.project_type || "未录入" }}</dd>
        </div>
        <div>
          <dt>项目负责人</dt>
          <dd>{{ project.owner_name || "未指定" }}</dd>
        </div>
        <div>
          <dt>责任部门</dt>
          <dd>{{ project.department_name || "未指定" }}</dd>
        </div>
        <div>
          <dt>计划开始</dt>
          <dd>{{ project.planned_start || "未录入" }}</dd>
        </div>
        <div>
          <dt>预计结束</dt>
          <dd>{{ project.planned_end || "未录入" }}</dd>
        </div>
        <div>
          <dt>数据来源</dt>
          <dd>{{ project.data_source }}</dd>
        </div>
        <div>
          <dt>当前计划版本</dt>
          <dd>{{ project.current_plan_label || "尚无生效计划" }}</dd>
        </div>
        <div>
          <dt>数据修订号</dt>
          <dd>{{ project.row_version }}</dd>
        </div>
        <div>
          <dt>最近更新</dt>
          <dd>{{ project.updated_at.slice(0, 10) }}</dd>
        </div>
      </dl>
      <p v-if="project.attention_note" class="notice warning">
        {{ project.attention_note }}
      </p>
    </section>
    <div class="stat-grid">
      <div class="card stat">
        <span>已录入节点</span><strong>{{ project.milestone_count }}</strong>
      </div>
      <div class="card stat">
        <span>已确认完成</span
        ><strong class="completed">{{
          metric ? metric.counts.verified_completed : "—"
        }}</strong
        ><small class="muted">以独立核实事实为准</small>
      </div>
      <div class="card stat">
        <span>到期待核对</span
        ><strong class="draft">{{
          metric?.counts.pending_verification ?? "—"
        }}</strong
        ><small class="muted">事实不足，不推定延期</small>
      </div>
      <div class="card stat">
        <span>延期完成</span
        ><strong class="danger-text">{{
          metric?.counts.late_completed ?? "—"
        }}</strong
        ><small class="muted">未完成与延期完成分列</small>
      </div>
    </div>
    <p v-if="summaryError" class="error" role="alert">
      项目摘要暂不可用：{{ summaryError }}
      <button :disabled="busy" @click="loadSummary(project)">重试摘要</button>
    </p>
    <div class="project-progress-panels">
      <section class="card project-milestones">
        <div class="section-title">
          <h3>项目关键里程碑</h3>
          <RouterLink
            :to="{ path: '/milestones', query: { project: project.id } }"
            >查看全部节点 ›</RouterLink
          >
        </div>
        <p class="muted">
          生效计划按日期排序 · 当前展示前 5 项；不代表加权项目完成率
        </p>
        <div v-if="metric?.evidence.length" class="timeline detail-timeline">
          <RouterLink
            v-for="node in metric.evidence
              .filter((r) => r.category !== 'excluded')
              .slice(0, 5)"
            :key="node.milestone_id"
            class="step-card"
            :class="node.category"
            :to="{ path: '/milestones', query: { project: project.id } }"
            ><TimelineDot :category="node.category" /><strong>{{
              node.milestone_name
            }}</strong
            ><small>计划 {{ node.planned_date }}</small
            ><small>核实实际 {{ node.actual_date || "待核对" }}</small
            ><span class="badge" :class="node.category">{{
              categoryLabels[node.category]
            }}</span></RouterLink
          >
        </div>
        <p v-else class="empty">
          尚无可展示的生效计划节点，请先录入并独立批准计划。
        </p>
      </section>
      <section class="card project-todos">
        <div class="section-title">
          <h3>项目重点待办事项</h3>
          <span class="badge todo">待处理 {{ tasks.total }}</span>
        </div>
        <p class="muted">展示待处理状态任务；其他状态见提醒与待办。</p>
        <RouterLink
          v-for="task in tasks.items"
          :key="task.id"
          class="overview-todo"
          :to="{
            path: '/tasks',
            query: { tab: 'tasks', project: project.id, task: task.id },
          }"
          ><div>
            <strong>{{ task.title }}</strong
            ><small>截止 {{ task.due_date }}</small>
          </div>
          <span class="badge" :class="task.status">{{
            label(task.status)
          }}</span></RouterLink
        >
        <p v-if="!tasks.items.length" class="empty">
          暂无待处理任务。<RouterLink
            :to="{
              path: '/tasks',
              query: { tab: 'tasks', project: project.id },
            }"
            >查看执行任务</RouterLink
          >
        </p>
      </section>
    </div>
    <section class="card project-execution-summary">
      <h3>项目执行摘要与数据质量</h3>
      <p class="muted">
        {{
          metric
            ? `统计截止 ${metric.as_of_date} · ${metric.formula.version} · ${metric.plan_version_label}`
            : "尚无生效计划，不生成正式评价。"
        }}
      </p>
      <div v-if="metric" class="execution-summary-grid">
        <div
          v-for="(value, title) in {
            到期节点: metric.counts.due_total,
            已核实按期: metric.counts.on_time_completed,
            已核实逾期未完成: metric.counts.confirmed_overdue_unfinished,
            待核对事项: metric.counts.pending_verification,
          }"
          :key="title"
        >
          <span>{{ title }}</span
          ><strong>{{ value }}</strong>
        </div>
      </div>
      <p v-if="metric" class="muted">
        {{ metric.formula.score }}
        任务反馈、通知审核通过均不替代节点实际完成核实。
      </p>
    </section>
    <section id="project-audit-history" class="card table-card">
      <h3>历史变更</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间（UTC）</th>
              <th>操作</th>
              <th>操作人</th>
              <th>变更前 / 后</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in events" :key="e.id">
              <td>{{ e.occurred_at }}</td>
              <td>{{ e.action }}</td>
              <td>{{ e.actor_id }}</td>
              <td>
                <details>
                  <summary>查看变更记录</summary>
                  <pre>{{
                    JSON.stringify(
                      { before: e.before_json, after: e.after_json },
                      null,
                      2,
                    )
                  }}</pre>
                </details>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <ProjectMembers :project-id="project.id" />
    <p class="muted">
      项目归档保留节点和审计历史。<button
        v-if="project.project_status !== 'archived' && auth.can(project.id)"
        class="text-button danger"
        @click="archiving = true"
      >
        归档项目
      </button>
    </p>
    <ProjectForm
      v-if="editing"
      :project="project"
      @close="editing = false"
      @saved="
        editing = false;
        load();
      "
    />
    <Modal
      v-if="archiving"
      title="归档项目"
      :busy="busy"
      @close="archiving = false"
      ><p>
        确认归档
        {{
          project.project_code
        }}？历史记录将保留，归档后不能修改节点计划；可在编辑项目中恢复状态。
      </p>
      <p v-if="error" class="error">{{ error }}</p>
      <template #footer
        ><button :disabled="busy" @click="archiving = false">取消</button
        ><button class="primary" :disabled="busy" @click="archive">
          确认归档
        </button></template
      ></Modal
    >
  </template>
</template>

<script setup lang="ts">
import { ElButton } from "element-plus/es/components/button/index";
import StatCard from "../components/StatCard.vue";
import {
  OfficeBuilding,
  DataLine,
  Clock,
  Warning,
} from "@element-plus/icons-vue";
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, errorMessage } from "../api";
import { useAuth } from "../store";
import { businessToday, type Dashboard } from "../evaluationTypes";
import type { Project } from "../types";
import { label } from "../workflowTypes";
import StatusBadge from "../components/StatusBadge.vue";
import ProjectForm from "../components/ProjectForm.vue";
import Modal from "../components/Modal.vue";
import Icon from "../components/Icon.vue";

const auth = useAuth(),
  router = useRouter();
const summary = ref<{ total: number; active: number; milestones: number }>();
const dashboard = ref<Dashboard>();
const error = ref(""),
  busy = ref(true),
  showForm = ref(false),
  showBasis = ref(false);
const chartMax = computed(() =>
  Math.max(
    1,
    ...(dashboard.value?.months.flatMap((m) => [
      m.on_time_completed,
      m.late_completed,
    ]) || []),
  ),
);
const hasHistory = computed(() =>
  dashboard.value?.months.some((m) => m.due_total > 0),
);
async function load() {
  busy.value = true;
  error.value = "";
  try {
    const [s, d] = await Promise.all([
      api<NonNullable<typeof summary.value>>("/summary"),
      api<Dashboard>(`/metrics/dashboard?as_of=${businessToday()}`),
    ]);
    summary.value = s;
    dashboard.value = d;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function saved(project: Project) {
  showForm.value = false;
  void router.push(`/projects/${project.id}`);
}
onMounted(load);
</script>
<template>
  <div class="overview-workspace">
    <div class="page-title">
      <div>
        <h1>项目总体概览</h1>
        <p>
          项目状态、关键节点与待办工作统一掌握 ·
          {{ auth.user?.demo_mode ? "模拟测试数据" : "业务数据" }}
        </p>
      </div>
      <ElButton
        class="primary"
        :disabled="!auth.user?.is_system_admin"
        @click="showForm = true"
        native-type="submit"
        type="primary"
      >
        <Icon name="imgVectorPlus" />新建项目
      </ElButton>
    </div>
    <p v-if="error" class="error" role="alert">
      {{ error }}
      <ElButton :disabled="busy" @click="load" native-type="submit"
        >重试</ElButton
      >
    </p>
    <p v-if="busy" class="card empty" role="status">
      正在加载项目、节点和待办…
    </p>
    <template v-else-if="summary && dashboard && !error">
      <div class="stat-grid overview-stats">
        <StatCard
          label="在管项目"
          :value="summary.total"
          :icon="OfficeBuilding"
        >
          已录入 {{ summary.milestones }} 个节点
        </StatCard>
        <StatCard label="进行中项目" :value="summary.active" :icon="DataLine">
          按当前项目状态统计
        </StatCard>
        <StatCard
          label="近期待办"
          :value="dashboard.pending_tasks"
          :icon="Clock"
          tone="amber"
        >
          当前尚未核实完成的任务
        </StatCard>
        <StatCard
          label="异常节点"
          :value="
            dashboard.counts.late_completed +
            dashboard.counts.confirmed_overdue_unfinished
          "
          :icon="Warning"
          tone="red"
        >
          延期完成及已核实逾期未完成
        </StatCard>
      </div>
      <div class="overview-panels">
        <section class="card overview-trend" aria-labelledby="trend-title">
          <div class="section-title">
            <h3 id="trend-title">节点履约趋势</h3>
            <span class="muted">最近 6 个完整自然月 · 按期 / 延期完成</span>
          </div>
          <div
            v-if="hasHistory"
            class="monthly-chart"
            role="img"
            aria-label="最近六个月按期及延期完成节点数量，按计划到期月份分组"
          >
            <div
              v-for="month in dashboard.months"
              :key="month.month"
              class="monthly-column"
              :aria-label="`${month.month}：按期完成 ${month.on_time_completed}，延期完成 ${month.late_completed}，待核对 ${month.pending_verification}`"
            >
              <div class="monthly-bars">
                <span
                  class="monthly-bar on-time"
                  :style="{
                    height: `${(month.on_time_completed / chartMax) * 136}px`,
                  }"
                  :title="`按期完成 ${month.on_time_completed}`"
                /><span
                  class="monthly-bar late"
                  :style="{
                    height: `${(month.late_completed / chartMax) * 136}px`,
                  }"
                  :title="`延期完成 ${month.late_completed}`"
                />
              </div>
              <span>{{ Number(month.month.slice(5)) }}月</span>
            </div>
          </div>
          <p v-else class="empty chart-empty">
            最近六个完整月暂无可统计的计划节点，不生成模拟趋势。
          </p>
          <div class="chart-legend">
            <span><i class="on-time" />按期完成</span
            ><span><i class="late" />延期完成</span
            ><ElButton
              class="text-button"
              @click="showBasis = true"
              native-type="submit"
              link
            >
              统计依据
            </ElButton>
          </div>
        </section>
        <section class="card overview-todos" aria-labelledby="todo-title">
          <h3 id="todo-title">近期待办事项</h3>
          <p class="muted">未完成任务按截止日期排序</p>
          <RouterLink
            v-for="task in dashboard.upcoming_tasks"
            :key="task.id"
            class="overview-todo"
            :to="{
              path: '/tasks',
              query: { tab: 'tasks', project: task.project_id, task: task.id },
            }"
          >
            <div>
              <strong>{{ task.title }}</strong
              ><small>截止 {{ task.due_date }}</small>
            </div>
            <span class="badge" :class="task.status">{{
              label(task.status)
            }}</span>
          </RouterLink>
          <p v-if="!dashboard.upcoming_tasks.length" class="empty">
            暂无未完成任务。<RouterLink to="/tasks">查看提醒与待办</RouterLink>
          </p>
        </section>
      </div>
      <section class="card table-card overview-projects">
        <div class="section-title">
          <h3>重点项目进展</h3>
          <span class="muted"
            >按项目编号展示前 5 项 · 截止 {{ dashboard.as_of_date }}</span
          ><RouterLink class="text-button" to="/projects"
            >全部项目 →</RouterLink
          >
        </div>
        <div v-if="dashboard.projects.length" class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>项目编号</th>
                <th>项目名称</th>
                <th>负责人</th>
                <th>节点数量</th>
                <th>已核实完成</th>
                <th>当前计划</th>
                <th>下一关键节点</th>
                <th>下一节点计划日期</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in dashboard.projects" :key="p.id">
                <td>
                  <RouterLink :to="`/projects/${p.id}`">{{
                    p.project_code
                  }}</RouterLink>
                </td>
                <td>
                  <RouterLink :to="`/projects/${p.id}`">{{
                    p.project_name
                  }}</RouterLink>
                </td>
                <td>{{ p.owner_name || "未指定" }}</td>
                <td>{{ p.milestone_count }}</td>
                <td>
                  {{ p.counts ? p.counts.verified_completed : "无生效计划" }}
                </td>
                <td>{{ p.current_plan_label || "尚无生效计划" }}</td>
                <td>{{ p.next_milestone?.milestone_name || "—" }}</td>
                <td>{{ p.next_milestone?.planned_date || "—" }}</td>
                <td><StatusBadge :value="p.project_status" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty">
          尚无可访问的项目，请创建项目或联系管理员授权。
        </p>
      </section>
    </template>
    <ProjectForm v-if="showForm" @close="showForm = false" @saved="saved" />
    <Modal
      v-if="showBasis && dashboard"
      title="总览统计依据"
      @close="showBasis = false"
      ><p>{{ dashboard.trend_basis }}</p>
      <p>{{ dashboard.task_basis }}</p>
      <p>
        异常节点为延期完成与已核实逾期未完成的数量之和；待核对
        {{ dashboard.counts.pending_verification }} 项单列，不推定为延期。
      </p>
      <p>
        计算时间 {{ dashboard.computed_at }} · {{ dashboard.formula.version }}
      </p>
      <RouterLink to="/metrics">查看量化评估及证据</RouterLink></Modal
    >
  </div>
</template>

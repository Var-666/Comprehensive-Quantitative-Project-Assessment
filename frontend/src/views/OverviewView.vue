<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, errorMessage } from "../api";
import type { Page, Project } from "../types";
import StatusBadge from "../components/StatusBadge.vue";
const summary = ref<{ total: number; active: number; milestones: number }>();
const projects = ref<Project[]>([]),
  error = ref(""),
  busy = ref(true);
async function load() {
  busy.value = true;
  error.value = "";
  try {
    const [s, p] = await Promise.all([
      api<NonNullable<typeof summary.value>>("/summary"),
      api<Page<Project>>("/projects?page_size=5"),
    ]);
    summary.value = s;
    projects.value = p.items;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <div class="page-title">
    <div>
      <h1>项目总体概览</h1>
      <p>项目台账与节点计划统一掌握 · 本地演示数据</p>
    </div>
    <RouterLink class="button primary" to="/projects">管理项目</RouterLink>
  </div>
  <p v-if="error" class="error" role="alert">
    {{ error }} <button @click="load">重试</button>
  </p>
  <p v-if="busy" class="empty">加载中…</p>
  <template v-else-if="summary"
    ><div class="stat-grid">
      <div class="card stat">
        <span>在管项目</span><strong>{{ summary.total }}</strong>
      </div>
      <div class="card stat">
        <span>进行中项目</span
        ><strong class="active">{{ summary.active }}</strong>
      </div>
      <div class="card stat">
        <span>已录入节点</span><strong>{{ summary.milestones }}</strong>
      </div>
      <div class="card stat">
        <span>当前阶段</span
        ><strong class="phase-number">第一期业务闭环</strong>
      </div>
    </div>
    <section class="card table-card">
      <div class="section-title">
        <h3>重点项目进展</h3>
        <span class="muted">查询当前数据库 · 评价与报告见对应模块</span>
      </div>
      <div v-if="projects.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>项目编号 / 名称</th>
              <th>负责人</th>
              <th>节点数量</th>
              <th>当前计划</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in projects" :key="p.id">
              <td>
                <RouterLink :to="`/projects/${p.id}`"
                  >{{ p.project_code }} · {{ p.project_name }}</RouterLink
                >
              </td>
              <td>{{ p.owner_name || "未指定" }}</td>
              <td>{{ p.milestone_count }}</td>
              <td>{{ p.current_plan_label || "尚未已生效" }}</td>
              <td><StatusBadge :value="p.project_status" /></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">尚无项目，请先新建或初始化模拟测试数据。</p>
    </section>
    <p class="notice">
      项目、节点、导入、标准动作、提醒待办、试算评价与阶段报告已接入数据库。 AI
      默认 Mock，实际事实与报告仍须独立核实、审核。
    </p>
  </template>
</template>

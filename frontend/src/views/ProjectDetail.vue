<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, errorMessage, versionHeader } from "../api";
import type { Audit, Project } from "../types";
import ProjectForm from "../components/ProjectForm.vue";
import StatusBadge from "../components/StatusBadge.vue";
import Modal from "../components/Modal.vue";
import ProjectMembers from "../components/ProjectMembers.vue";
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
          {{ project.current_plan_label || "尚未已生效" }}
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
    <section class="card detail-card">
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
        <span>当前计划版本</span
        ><strong>{{ project.current_plan_label || "草稿" }}</strong>
      </div>
      <div class="card stat">
        <span>数据修订号</span><strong>{{ project.row_version }}</strong>
      </div>
      <div class="card stat">
        <span>最近更新</span
        ><strong class="phase-number">{{
          project.updated_at.slice(0, 10)
        }}</strong>
      </div>
    </div>
    <section class="card table-card">
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

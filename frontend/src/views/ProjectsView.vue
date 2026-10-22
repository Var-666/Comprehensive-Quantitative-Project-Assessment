<script setup lang="ts">
import OperationToast from "../components/OperationToast.vue";
import PageNavigation from "../components/PageNavigation.vue";
import StatCard from "../components/StatCard.vue";
import {
  FolderOpened,
  VideoPlay,
  EditPen,
  CircleCheck,
} from "@element-plus/icons-vue";
import { ElButton } from "element-plus/es/components/button/index";
import { ElInput } from "element-plus/es/components/input/index";
import FormSelect from "../components/FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, errorMessage } from "../api";
import type { Page, Project } from "../types";
import { statuses } from "../types";
import { useAuth } from "../store";
const auth = useAuth();
import Icon from "../components/Icon.vue";
import ProjectForm from "../components/ProjectForm.vue";
import StatusBadge from "../components/StatusBadge.vue";
const router = useRouter();
const data = ref<Page<Project>>({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
});
const summary = ref({ total: 0, active: 0, draft: 0, completed: 0 });
const keyword = ref(""),
  status = ref(""),
  type = ref(""),
  error = ref(""),
  busy = ref(false),
  success = ref("");
const showForm = ref(false),
  editing = ref<Project>();
async function load(page = 1) {
  busy.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({
      page: String(page),
      page_size: "20",
      keyword: keyword.value,
      status: status.value,
      type: type.value,
    });
    const [list, stats] = await Promise.all([
      api<Page<Project>>(`/projects?${params}`),
      api<typeof summary.value>("/summary"),
    ]);
    data.value = list;
    summary.value = stats;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function reset() {
  keyword.value = "";
  status.value = "";
  type.value = "";
  void load();
}
function edit(p?: Project) {
  editing.value = p;
  showForm.value = true;
}
function saved(p: Project) {
  showForm.value = false;
  void router.push(`/projects/${p.id}`);
}
onMounted(() => load());
</script>
<template>
  <div class="page-title">
    <div>
      <h1>项目管理</h1>
      <p>集中管理试点项目基本信息、当前状态与节点执行数据</p>
    </div>
    <div class="actions">
      <ElButton
        :disabled="!auth.user?.is_system_admin"
        @click="
          router.push({ path: '/imports', query: { target: 'projects' } })
        "
        native-type="submit"
      >
        <Icon name="imgVectorFileUp" />导入 Excel</ElButton
      ><ElButton
        class="primary"
        :disabled="!auth.user?.is_system_admin"
        @click="edit()"
        native-type="submit"
        type="primary"
      >
        <Icon name="imgVectorPlus" />新建项目
      </ElButton>
    </div>
  </div>
  <form class="card filters" @submit.prevent="load()">
    <ElInput
      v-model="keyword"
      class="project-search"
      aria-label="搜索项目"
      placeholder="搜索项目编号 / 项目名称 / 负责人"
      clearable
    >
      <template #prefix><Icon name="imgVectorSearch" /></template>
    </ElInput>
    <label class="inline-label"
      >项目状态<FormSelect
        v-model="status"
        @change="load()"
        :aria-label="'项目状态'"
      >
        <ElOption data-ui-value="" value="" :label="'全部'" />
        <ElOption
          :data-ui-value="s"
          v-for="s in [
            'draft',
            'not_started',
            'active',
            'completed',
            'archived',
          ]"
          :key="s"
          :value="s"
          :label="String(statuses[s])"
        /> </FormSelect></label
    ><label class="inline-label"
      >项目类型<FormSelect
        v-model="type"
        aria-label="项目类型"
        allow-create
        default-first-option
        @change="load()"
      >
        <ElOption data-ui-value="" value="" label="全部" />
        <ElOption
          v-for="item in ['船舶建造', '试制项目', '修理改造']"
          :key="item"
          :data-ui-value="item"
          :value="item"
          :label="item"
        /> </FormSelect></label
    ><ElButton :disabled="busy" native-type="submit">查询</ElButton
    ><ElButton @click="reset" native-type="button">
      <Icon name="imgVectorRotateCcw" />重置筛选
    </ElButton>
  </form>
  <div class="stat-grid">
    <StatCard
      v-for="(label, key) in {
        total: '全部项目',
        active: '执行中',
        draft: '草稿',
        completed: '已完成',
      }"
      :key="key"
      :label="label"
      :value="summary[key]"
      :icon="
        {
          total: FolderOpened,
          active: VideoPlay,
          draft: EditPen,
          completed: CircleCheck,
        }[key]
      "
      :tone="key === 'completed' ? 'green' : key === 'draft' ? 'amber' : 'blue'"
    />
  </div>
  <OperationToast v-model="success" :busy="busy" />
  <p v-if="error" class="error" role="alert">
    {{ error }}
    <ElButton @click="load(data.page)" native-type="submit">重试</ElButton>
  </p>
  <section class="card table-card" :aria-busy="busy">
    <div class="section-title">
      <h3>试点项目台账</h3>
      <span class="muted">数据来自本地数据库 · 共 {{ data.total }} 个项目</span>
    </div>
    <p v-if="busy" class="empty" role="status">正在加载项目…</p>
    <div v-else-if="data.items.length" class="table-wrap">
      <table class="project-list-table">
        <thead>
          <tr>
            <th>项目编号</th>
            <th>项目名称</th>
            <th>项目类型</th>
            <th>负责人</th>
            <th>节点数量</th>
            <th>最近更新</th>
            <th>状态</th>
            <th>备注</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in data.items" :key="p.id">
            <td>
              <RouterLink :to="`/projects/${p.id}`">{{
                p.project_code
              }}</RouterLink>
            </td>
            <td>{{ p.project_name }}</td>
            <td>{{ p.project_type || "—" }}</td>
            <td>{{ p.owner_name || "未指定" }}</td>
            <td>{{ p.milestone_count }}</td>
            <td>{{ p.updated_at.slice(0, 10) }}</td>
            <td><StatusBadge :value="p.project_status" /></td>
            <td :class="{ 'warning-text': p.attention_note }">
              {{ p.attention_note || "—" }}
            </td>
            <td>
              <div class="row-actions">
                <RouterLink
                  class="icon-button"
                  :to="`/projects/${p.id}`"
                  :aria-label="`查看 ${p.project_code}`"
                  ><Icon name="imgVectorEye" /></RouterLink
                ><ElButton
                  class="icon-button"
                  :aria-label="`编辑 ${p.project_code}`"
                  :disabled="!auth.can(p.id)"
                  @click="edit(p)"
                  native-type="submit"
                  link
                >
                  <Icon name="imgVectorPencil" />
                </ElButton>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else-if="!error" class="empty">
      暂无符合条件的项目。可新建项目或导入 Excel。
    </div>
    <PageNavigation
      :page="data.page"
      :total="data.total"
      :page-size="data.page_size"
      :disabled="busy"
      @change="load"
    />
  </section>
  <ProjectForm
    v-if="showForm"
    :project="editing"
    @close="showForm = false"
    @saved="saved"
  />
</template>

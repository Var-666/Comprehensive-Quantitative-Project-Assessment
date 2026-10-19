<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, errorMessage } from "../api";
import type { Page, Project } from "../types";
import { statuses } from "../types";
import { useAuth } from "../store";
const auth = useAuth();
import Icon from "../components/Icon.vue";
import ProjectForm from "../components/ProjectForm.vue";
import ImportDialog from "../components/ImportDialog.vue";
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
  editing = ref<Project>(),
  showImport = ref(false);
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
      <button
        :disabled="!auth.user?.is_system_admin"
        @click="showImport = true"
      >
        <Icon name="imgVectorFileUp" />导入 Excel</button
      ><button
        class="primary"
        :disabled="!auth.user?.is_system_admin"
        @click="edit()"
      >
        <Icon name="imgVectorPlus" />新建项目
      </button>
    </div>
  </div>
  <form class="card filters" @submit.prevent="load()">
    <div class="search">
      <Icon name="imgVectorSearch" /><input
        v-model="keyword"
        aria-label="搜索项目"
        placeholder="搜索项目编号 / 项目名称 / 负责人"
      />
    </div>
    <label class="inline-label"
      >项目状态<select v-model="status" @change="load()">
        <option value="">全部</option>
        <option
          v-for="s in [
            'draft',
            'not_started',
            'active',
            'completed',
            'archived',
          ]"
          :key="s"
          :value="s"
        >
          {{ statuses[s] }}
        </option>
      </select></label
    ><label class="inline-label"
      >项目类型<input
        v-model="type"
        aria-label="项目类型"
        placeholder="全部"
        list="filter-types"
        @change="load()"
      /><datalist id="filter-types">
        <option>船舶建造</option>
        <option>试制项目</option>
        <option>修理改造</option>
      </datalist></label
    ><button type="submit" :disabled="busy">查询</button
    ><button type="button" @click="reset">
      <Icon name="imgVectorRotateCcw" />重置筛选
    </button>
  </form>
  <div class="stat-grid">
    <div
      v-for="(label, key) in {
        total: '全部项目',
        active: '执行中',
        draft: '草稿',
        completed: '已完成',
      }"
      :key="key"
      class="card stat"
    >
      <span>{{ label }}</span
      ><strong :class="key">{{ summary[key] }}</strong>
    </div>
  </div>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <p v-if="error" class="error" role="alert">
    {{ error }} <button @click="load(data.page)">重试</button>
  </p>
  <section class="card table-card" :aria-busy="busy">
    <div class="section-title">
      <h3>试点项目台账</h3>
      <span class="muted">数据来自本地数据库 · 共 {{ data.total }} 个项目</span>
    </div>
    <p v-if="busy" class="empty" role="status">正在加载项目…</p>
    <div v-else-if="data.items.length" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>项目编号</th>
            <th>项目名称</th>
            <th>项目类型</th>
            <th>负责人</th>
            <th>节点数量</th>
            <th>最近更新</th>
            <th>状态</th>
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
            <td>
              {{ p.project_name
              }}<small v-if="p.attention_note" class="subline warning-text">{{
                p.attention_note
              }}</small>
            </td>
            <td>{{ p.project_type || "—" }}</td>
            <td>{{ p.owner_name || "未指定" }}</td>
            <td>{{ p.milestone_count }}</td>
            <td>{{ p.updated_at.slice(0, 10) }}</td>
            <td><StatusBadge :value="p.project_status" /></td>
            <td class="row-actions">
              <RouterLink
                class="icon-button"
                :to="`/projects/${p.id}`"
                :aria-label="`查看 ${p.project_code}`"
                ><Icon name="imgVectorEye" /></RouterLink
              ><button
                class="icon-button"
                :aria-label="`编辑 ${p.project_code}`"
                :disabled="!auth.can(p.id)"
                @click="edit(p)"
              >
                <Icon name="imgVectorPencil" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else-if="!error" class="empty">
      暂无符合条件的项目。可新建项目或导入 Excel。
    </div>
    <div class="pagination">
      <span>第 {{ data.page }} 页 · 共 {{ data.total }} 条</span
      ><button :disabled="busy || data.page <= 1" @click="load(data.page - 1)">
        上一页</button
      ><button
        :disabled="busy || data.page * data.page_size >= data.total"
        @click="load(data.page + 1)"
      >
        下一页
      </button>
    </div>
  </section>
  <ProjectForm
    v-if="showForm"
    :project="editing"
    @close="showForm = false"
    @saved="saved"
  />
  <ImportDialog
    v-if="showImport"
    @close="showImport = false"
    @imported="
      success = 'Excel 导入已写入本地数据库';
      load();
    "
  />
</template>

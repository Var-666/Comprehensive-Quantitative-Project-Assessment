<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api, errorMessage } from "../api";
import type { ActionTemplate } from "../workflowTypes";
import { label } from "../workflowTypes";
import { useAuth, useCatalog } from "../store";
import type { Page } from "../types";
import ConfigApproval from "../components/ConfigApproval.vue";
import TemplateForm from "../components/TemplateForm.vue";
import RuleCalendarPanel from "../components/RuleCalendarPanel.vue";
import Icon from "../components/Icon.vue";
const auth = useAuth(),
  catalog = useCatalog(),
  tab = ref("templates"),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  selected = ref<ActionTemplate>(),
  show = ref(false),
  editing = ref<ActionTemplate>(),
  copy = ref(false),
  page = ref(1),
  status = ref(""),
  type = ref("");
const data = ref<Page<ActionTemplate>>({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
});
async function load(n = page.value) {
  busy.value = true;
  error.value = "";
  try {
    await catalog.load();
    data.value = await api<Page<ActionTemplate>>(
      `/action-templates?page=${n}&page_size=20&status=${status.value}&node_type=${encodeURIComponent(type.value)}`,
    );
    page.value = n;
    selected.value =
      data.value.items.find((t) => t.id === selected.value?.id) ||
      data.value.items[0];
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function open(template?: ActionTemplate, createCopy = false) {
  editing.value = template;
  copy.value = createCopy;
  show.value = true;
}
async function saved(value: ActionTemplate) {
  show.value = false;
  success.value = "模板草稿已保存";
  selected.value = value;
  await load(1);
}
onMounted(() => load());
</script>
<template>
  <div class="page-title">
    <div>
      <h1>标准动作配置</h1>
      <p>将高频项目节点的准备事项沉淀为可维护模板，并通过适用条件控制匹配</p>
    </div>
    <button
      v-if="tab === 'templates'"
      class="primary"
      :disabled="!auth.user?.is_system_admin"
      @click="open()"
    >
      <Icon name="imgVectorPlus" />创建动作模板
    </button>
  </div>
  <div class="tabs">
    <button
      :class="{ primary: tab === 'templates' }"
      @click="tab = 'templates'"
    >
      动作模板</button
    ><button :class="{ primary: tab === 'rules' }" @click="tab = 'rules'">
      提醒规则</button
    ><button
      :class="{ primary: tab === 'calendars' }"
      @click="tab = 'calendars'"
    >
      工作日历
    </button>
  </div>
  <p v-if="error" class="error" role="alert">
    {{ error }} <button @click="load()">重试</button>
  </p>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <template v-if="tab === 'templates'">
    <p v-if="busy" class="empty" role="status">正在加载动作模板…</p>
    <div v-else class="workflow-split template-split">
      <section class="card queue">
        <h3>标准动作模板</h3>
        <p class="muted">按节点类型管理 · 共{{ data.total }}个版本</p>
        <form
          class="filters compact template-filters"
          @submit.prevent="load(1)"
        >
          <label
            >节点类型<select v-model="type">
              <option value="">全部</option>
              <option
                v-for="n in catalog.nodeTypes"
                :key="n.code"
                :value="n.code"
              >
                {{ n.display_name }}
              </option>
            </select></label
          ><label
            >模板状态<select v-model="status">
              <option value="">全部</option>
              <option
                v-for="s in ['draft', 'pending_review', 'approved', 'retired']"
                :key="s"
                :value="s"
              >
                {{ label(s) }}
              </option>
            </select></label
          ><button :disabled="busy">查询模板</button>
        </form>
        <p v-if="!data.items.length" class="empty">
          暂无模板，请创建后提交业务确认。
        </p>
        <button
          v-for="t in data.items"
          :key="t.id"
          class="queue-item"
          :class="{ selected: selected?.id === t.id }"
          @click="selected = t"
        >
          <strong>{{ t.title }}</strong
          ><small
            >{{ t.items.length }}项动作 · {{ t.version_label }} ·
            {{ label(t.status) }}</small
          >
        </button>
        <div class="pagination">
          <button :disabled="page <= 1" @click="load(page - 1)">上一页</button
          ><span>{{ page }}</span
          ><button :disabled="page * 20 >= data.total" @click="load(page + 1)">
            下一页
          </button>
        </div>
      </section>
      <section v-if="selected" class="card workflow-detail">
        <div class="section-title">
          <h2>{{ selected.title }}</h2>
          <span class="badge" :class="selected.status">{{
            label(selected.status)
          }}</span>
        </div>
        <p class="muted">
          适用节点：{{ selected.node_type_code }} · 适用项目类型：{{
            selected.applicability_json.project_type || "不限"
          }}
        </p>
        <dl class="details">
          <div>
            <dt>模板编号及版本</dt>
            <dd>{{ selected.template_code }} · {{ selected.version_label }}</dd>
          </div>
          <div>
            <dt>模板来源</dt>
            <dd>{{ selected.source_ref }}</dd>
          </div>
        </dl>
        <h3>节点触发后需执行的标准动作</h3>
        <div v-for="i in selected.items" :key="i.id" class="action-item">
          <span class="badge">{{ i.item_code }}</span>
          <div>
            <strong>{{ i.title }}</strong>
            <p class="muted">
              责任部门：{{
                catalog.departments.find(
                  (d) => d.id === i.default_department_id,
                )?.dept_name || "沿用节点责任部门"
              }}
            </p>
            <p>核实依据：{{ i.completion_criteria }}</p>
            <small
              >所需材料：{{
                i.materials_required_json.join("、") || "无单独材料要求"
              }}</small
            >
          </div>
        </div>
        <div v-if="auth.user?.is_system_admin" class="actions">
          <button v-if="selected.status === 'draft'" @click="open(selected)">
            <Icon name="imgVectorSave" />编辑草稿</button
          ><button @click="open(selected, true)">创建新版本</button>
        </div>
        <ConfigApproval
          :key="selected.id"
          :item="selected"
          path="action-templates"
          @changed="load()"
        />
      </section>
      <section v-else class="card empty">
        请选择模板查看动作及业务依据。
      </section>
    </div></template
  >
  <RuleCalendarPanel
    v-else
    :key="tab"
    :kind="tab === 'rules' ? 'rules' : 'calendars'"
  />
  <TemplateForm
    v-if="show"
    :template="editing"
    :copy="copy"
    @close="show = false"
    @saved="saved"
  />
</template>

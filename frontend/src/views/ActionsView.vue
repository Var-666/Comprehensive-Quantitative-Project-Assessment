<script setup lang="ts">
import PageNavigation from "../components/PageNavigation.vue";
import { ElButton } from "element-plus/es/components/button/index";
import FormSelect from "../components/FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
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
    <ElButton
      v-if="tab === 'templates'"
      class="primary"
      :disabled="!auth.user?.is_system_admin"
      @click="open()"
      native-type="submit"
      type="primary"
    >
      <Icon name="imgVectorPlus" />创建动作模板
    </ElButton>
  </div>
  <div class="tabs">
    <ElButton
      :class="{ primary: tab === 'templates' }"
      @click="tab = 'templates'"
      native-type="submit"
      :type="tab === 'templates' ? 'primary' : 'default'"
    >
      动作模板</ElButton
    ><ElButton
      :class="{ primary: tab === 'rules' }"
      @click="tab = 'rules'"
      native-type="submit"
      :type="tab === 'rules' ? 'primary' : 'default'"
    >
      提醒规则</ElButton
    ><ElButton
      :class="{ primary: tab === 'calendars' }"
      @click="tab = 'calendars'"
      native-type="submit"
      :type="tab === 'calendars' ? 'primary' : 'default'"
    >
      工作日历
    </ElButton>
  </div>
  <p v-if="error" class="error" role="alert">
    {{ error }} <ElButton @click="load()" native-type="submit">重试</ElButton>
  </p>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <template v-if="tab === 'templates'">
    <p v-if="busy" class="empty" role="status">正在加载动作模板…</p>
    <div v-else class="workflow-split template-split">
      <section class="card queue">
        <div class="template-library-heading">
          <h3>标准动作模板</h3>
          <span class="badge">{{ data.total }} 个版本</span>
        </div>
        <p class="template-library-caption">按节点类型筛选并选择模板</p>
        <form
          class="filters compact template-filters"
          @submit.prevent="load(1)"
        >
          <label
            >节点类型<FormSelect v-model="type" :aria-label="'节点类型'">
              <ElOption data-ui-value="" value="" :label="'全部'" />
              <ElOption
                :data-ui-value="n.code"
                v-for="n in catalog.nodeTypes"
                :key="n.code"
                :value="n.code"
                :label="String(n.display_name)"
              /> </FormSelect></label
          ><label
            >模板状态<FormSelect v-model="status" :aria-label="'模板状态'">
              <ElOption data-ui-value="" value="" :label="'全部'" />
              <ElOption
                :data-ui-value="s"
                v-for="s in ['draft', 'pending_review', 'approved', 'retired']"
                :key="s"
                :value="s"
                :label="String(label(s))"
              /> </FormSelect></label
          ><ElButton :disabled="busy" native-type="submit">查询模板</ElButton>
        </form>
        <p v-if="!data.items.length" class="empty">
          暂无模板，请创建后提交业务确认。
        </p>
        <ul class="template-list" aria-label="标准动作模板列表">
          <li v-for="t in data.items" :key="t.id">
            <button
              type="button"
              class="queue-item template-choice"
              :class="{ selected: selected?.id === t.id }"
              :aria-pressed="selected?.id === t.id"
              aria-controls="template-detail"
              @click="selected = t"
            >
              <span class="template-choice-meta">
                <span>{{ t.template_code }}</span>
                <span class="badge" :class="t.status">{{
                  label(t.status)
                }}</span>
              </span>
              <strong>{{ t.title }}</strong>
              <small class="template-choice-meta">
                <span
                  >{{ t.node_type_code }} · {{ t.items.length }} 项动作</span
                >
                <span>{{ t.version_label }}</span>
              </small>
            </button>
          </li>
        </ul>
        <PageNavigation
          :page="page"
          :total="data.total"
          :page-size="20"
          :disabled="busy"
          @change="load"
        />
      </section>
      <section
        v-if="selected"
        id="template-detail"
        class="card workflow-detail template-detail"
        aria-labelledby="template-title"
      >
        <div class="template-detail-heading">
          <div>
            <p class="template-version">
              {{ selected.template_code }} / {{ selected.version_label }}
            </p>
            <h2 id="template-title">{{ selected.title }}</h2>
          </div>
          <span class="badge" :class="selected.status">{{
            label(selected.status)
          }}</span>
        </div>
        <dl class="template-summary">
          <div>
            <dt>适用节点</dt>
            <dd>{{ selected.node_type_code }}</dd>
          </div>
          <div>
            <dt>适用项目类型</dt>
            <dd>{{ selected.applicability_json.project_type || "不限" }}</dd>
          </div>
          <div class="template-source">
            <dt>模板来源</dt>
            <dd>{{ selected.source_ref }}</dd>
          </div>
        </dl>
        <div class="template-actions-heading">
          <h3>节点触发后需执行的标准动作</h3>
          <span>{{ selected.items.length }} 项</span>
        </div>
        <div class="template-action-list">
          <article
            v-for="i in selected.items"
            :key="i.id"
            class="template-action"
          >
            <div class="template-action-heading">
              <h4>{{ i.title }}</h4>
              <span class="badge">{{ i.item_code }}</span>
            </div>
            <dl class="template-requirements">
              <div>
                <dt>责任部门</dt>
                <dd>
                  {{
                    catalog.departments.find(
                      (d) => d.id === i.default_department_id,
                    )?.dept_name || "沿用节点责任部门"
                  }}
                </dd>
              </div>
              <div>
                <dt>核实依据</dt>
                <dd>{{ i.completion_criteria }}</dd>
              </div>
              <div>
                <dt>所需材料</dt>
                <dd>
                  {{ i.materials_required_json.join("、") || "无单独材料要求" }}
                </dd>
              </div>
            </dl>
          </article>
        </div>
        <footer class="template-toolbar">
          <div v-if="auth.user?.is_system_admin" class="actions">
            <ElButton
              v-if="selected.status === 'draft'"
              @click="open(selected)"
              native-type="submit"
            >
              <Icon name="imgVectorSave" />编辑草稿</ElButton
            ><ElButton @click="open(selected, true)" native-type="submit"
              >创建新版本</ElButton
            >
          </div>
          <ConfigApproval
            :key="selected.id"
            :item="selected"
            path="action-templates"
            @changed="load()"
          />
        </footer>
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

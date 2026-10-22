<script setup lang="ts">
import { useUnsavedChanges } from "../useUnsavedChanges";
import OperationToast from "./OperationToast.vue";
import { ElButton } from "element-plus/es/components/button/index";
import { DocumentChecked } from "@element-plus/icons-vue";
import {
  ElCheckbox,
  ElCheckboxGroup,
} from "element-plus/es/components/checkbox/index";
import { onMounted, ref } from "vue";
import { api, errorMessage, json } from "../api";
import { useAuth, useCatalog } from "../store";
import type { Milestone } from "../types";
import type { ActionMatching, ActionTemplate } from "../workflowTypes";
const props = defineProps<{ node: Milestone; planId: string }>();
const emit = defineEmits<{ changed: [] }>();
const auth = useAuth(),
  catalog = useCatalog(),
  matching = ref<ActionMatching>(),
  links = ref<NonNullable<ActionMatching["links"]>>([]),
  templates = ref<NonNullable<ActionMatching["candidates"]>>([]),
  selected = ref<string[]>([]),
  show = ref(false),
  busy = ref(false),
  error = ref(""),
  success = ref("");
const guard = useUnsavedChanges(
  () => ({ selected: selected.value }),
  () => show.value,
  () => busy.value,
);
async function load() {
  error.value = "";
  try {
    matching.value = await api<ActionMatching>(
      `/milestones/${props.node.id}/action-matching?plan_version_id=${props.planId}`,
    );
    links.value = matching.value.links || [];
  } catch (e) {
    matching.value = undefined;
    templates.value = [];
    error.value = errorMessage(e);
  }
}
async function open() {
  if (show.value && !error.value) return;
  show.value = true;
  error.value = "";
  busy.value = true;
  try {
    await load();
    if (!matching.value) return;
    const suggestions = await api<ActionTemplate[]>(
      `/milestones/${props.node.id}/suggested-actions?plan_item_id=${props.node.plan_item.id}`,
    );
    templates.value = suggestions.map((template) => ({
      ...template,
      items: template.items.map((item) => ({
        ...item,
        department_name:
          catalog.departments.find(
            (d) =>
              d.id ===
              (item.default_department_id ||
                props.node.plan_item.department_id),
          )?.dept_name || null,
      })),
    }));
    const available = new Set(
      templates.value.flatMap((t) => t.items.map((i) => i.id)),
    );
    selected.value = links.value
      .filter((l) => l.status === "active" && available.has(l.snapshot_json.id))
      .map((l) => l.snapshot_json.id || "")
      .filter(Boolean);
    guard.markSaved();
  } catch (e) {
    templates.value = [];
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function save() {
  if (!matching.value?.can_modify) {
    error.value = matching.value?.blocked_reason || "当前节点不允许修改";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await api(`/milestones/${props.node.id}/action-links`, {
      method: "POST",
      body: json({
        plan_item_id: props.node.plan_item.id,
        plan_version_id: props.planId,
        template_item_ids: selected.value,
      }),
    });
    await load();
    show.value = false;
    success.value = "动作配置已保存；模板版本及内容已留快照";
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
async function cancel() {
  if (await guard.confirmDiscard()) show.value = false;
}
defineExpose({
  open,
  refresh: load,
  busy,
  confirmDiscard: guard.confirmDiscard,
});
</script>
<template>
  <section class="form-section node-actions">
    <div class="section-title">
      <h3>关联标准动作</h3>
      <ElButton
        v-if="matching?.status !== 'tracking_only'"
        :disabled="!auth.can(node.project_id) || !matching?.can_modify"
        @click="open"
        native-type="submit"
      >
        关联动作模板
      </ElButton>
    </div>
    <p v-if="error && !show" class="error" role="alert">
      {{ error }} <ElButton @click="load">重新检查动作</ElButton>
    </p>
    <OperationToast v-model="success" :busy="busy" />
    <section v-if="matching" class="notice" role="status">
      <strong>{{ matching.label }}</strong>
      <p v-if="matching.status !== 'tracking_only'">
        已关联 {{ matching.action_count }} 项动作；适用的已批准模板
        {{ matching.candidate_count }} 个。
      </p>
      <p v-if="!matching.can_modify && matching.status !== 'tracking_only'">
        {{ matching.blocked_reason }}
      </p>
      <p v-if="matching.status === 'conflict'">
        系统不会代选模板，请对比候选的版本、动作、责任部门与核实依据后确认。
      </p>
      <p v-if="matching.status === 'pending_approval'">
        草稿和待审核模板不能用于自动匹配，须先独立批准。
      </p>
      <RouterLink
        v-if="
          auth.user?.is_system_admin &&
          !matching.action_count &&
          matching.status !== 'tracking_only'
        "
        to="/actions"
        >维护标准动作配置 →</RouterLink
      >
    </section>
    <p
      v-if="matching && !links.length && matching.status !== 'tracking_only'"
      class="muted"
    >
      尚未关联批准动作，不会生成对应准备任务。
    </p>
    <article
      v-for="l in links"
      :key="l.id"
      class="linked-action-card"
      :class="{
        'is-current':
          matching?.status !== 'tracking_only' &&
          l.status === 'active' &&
          l.applicable,
        'needs-review':
          matching?.status !== 'tracking_only' &&
          l.status === 'active' &&
          !l.applicable,
      }"
      :aria-label="l.snapshot_json.title"
    >
      <header class="linked-action-heading">
        <span class="linked-action-icon" aria-hidden="true"
          ><DocumentChecked
        /></span>
        <h4>{{ l.snapshot_json.title }}</h4>
        <span class="badge linked-action-status">{{
          matching?.status === "tracking_only"
            ? "已保存快照，暂不执行"
            : l.status === "active"
              ? l.applicable
                ? "已关联"
                : "待复核"
              : l.status === "cancelled"
                ? "已取消"
                : "历史关联"
        }}</span>
      </header>
      <p class="linked-action-template">
        {{ l.template_title }}
        <span class="badge">{{ l.snapshot_json.version_label }}</span>
      </p>
      <dl class="linked-action-meta">
        <div>
          <dt>责任部门</dt>
          <dd>{{ l.department_name || "未指定" }}</dd>
        </div>
        <div>
          <dt>关联方式</dt>
          <dd>
            {{
              l.source.startsWith("automatic_")
                ? l.source === "automatic_excel_import"
                  ? "系统自动匹配（正式导入）"
                  : "系统自动匹配（新建节点）"
                : "人工关联（含历史配置）"
            }}
          </dd>
        </div>
      </dl>
      <div class="linked-action-requirements">
        <span>核实要求</span>
        <p>{{ l.snapshot_json.completion_criteria || "未指定" }}</p>
        <div
          v-if="l.snapshot_json.materials_required_json?.length"
          class="linked-action-materials"
        >
          <span>所需材料</span>
          <span
            v-for="(material, index) in l.snapshot_json.materials_required_json"
            :key="index"
            class="badge"
            >{{ material }}</span
          >
        </div>
      </div>
    </article>
  </section>
  <section v-if="show" class="form-section" aria-label="选择标准动作模板">
    <h3>选择标准动作模板</h3>
    <p class="notice">
      当前节点：{{ node.milestone_code }} {{ node.milestone_name }} · 计划{{
        node.plan_item.planned_date
      }}。仅显示已批准且符合适用条件的模板。已有动作保留快照；调整请通过新计划或模板版本。
    </p>
    <p v-if="busy" role="status">正在加载可用模板…</p>
    <p v-if="error" class="error" role="alert">
      {{ error }} <ElButton @click="open">重试动作模板</ElButton>
    </p>
    <p v-if="!busy && !templates.length" class="empty">
      没有可用的批准模板，请先前往标准动作模块配置。
    </p>
    <ElCheckboxGroup v-model="selected"
      ><section v-for="t in templates" :key="t.id" class="form-section">
        <h3>
          {{ t.template_code }} · {{ t.title }} · {{ t.version_label }} ·
          {{ t.items.length }}项动作
        </h3>
        <p class="muted">
          适用节点：{{ t.node_type_code }} · 适用项目类型：{{
            t.applicability_json.project_type || "不限"
          }}
        </p>
        <ElButton
          :disabled="busy"
          @click="
            selected = [
              ...new Set([
                ...selected.filter((id) =>
                  links.some(
                    (l) => l.status === 'active' && l.snapshot_json.id === id,
                  ),
                ),
                ...t.items.map((i) => i.id!).filter(Boolean),
              ]),
            ]
          "
          >使用这套模板</ElButton
        >
        <ElCheckbox
          v-for="i in t.items"
          :key="i.id"
          class="checkbox-line action-item"
          :value="i.id"
          :disabled="
            links.some(
              (l) => l.status === 'active' && l.snapshot_json.id === i.id,
            )
          "
          ><span
            >{{ i.item_code }} {{ i.title
            }}<small class="subline"
              >默认责任部门：{{ i.department_name || "未指定" }} · 核实依据：{{
                i.completion_criteria
              }}</small
            ></span
          ></ElCheckbox
        >
      </section></ElCheckboxGroup
    >
    <p class="notice">
      关联动作生成的是准备工作，任务反馈及核实不会自动改变节点实际完成事实。
    </p>
    <div class="actions">
      <ElButton :disabled="busy" @click="cancel" native-type="button"
        >取消</ElButton
      ><ElButton
        :disabled="busy || !!error || !selected.length || !matching?.can_modify"
        class="primary"
        @click="save"
        native-type="submit"
        type="primary"
      >
        保存关联配置
      </ElButton>
    </div>
  </section>
</template>
<style scoped>
.node-actions {
  display: grid;
  gap: 16px;
}
.node-actions > * {
  min-width: 0;
  margin-block: 0;
}
.linked-action-card {
  --action-color: var(--muted);
  --action-tint: var(--pale);
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--white);
  overflow-wrap: anywhere;
}
.linked-action-card.is-current {
  --action-color: var(--blue);
  --action-tint: var(--light);
  border-color: #d5e2fa;
}
.linked-action-card.needs-review {
  --action-color: var(--amber);
  --action-tint: var(--amberlight);
  border-color: #eed9b6;
}
.linked-action-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.linked-action-icon {
  display: grid;
  place-items: center;
  flex: 0 0 32px;
  height: 32px;
  border-radius: 8px;
  color: var(--action-color);
  background: var(--action-tint);
}
.linked-action-icon svg {
  width: 19px;
  height: 19px;
}
.linked-action-heading h4 {
  flex: 1;
  min-width: 120px;
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
}
.linked-action-status {
  max-width: 100%;
  white-space: normal;
  color: var(--action-color);
  background: var(--action-tint);
}
.linked-action-template {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
  color: var(--muted);
  font-size: 12px;
}
.linked-action-meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.5fr);
  gap: 12px;
  margin: 0 0 12px;
}
.linked-action-meta dt,
.linked-action-requirements > span,
.linked-action-materials > span:first-child {
  color: var(--muted);
  font-size: 12px;
}
.linked-action-meta dd {
  margin: 8px 0 0;
}
.linked-action-requirements {
  padding: 12px;
  border-radius: 8px;
  background: var(--bg);
}
.linked-action-requirements p {
  margin: 8px 0 0;
  line-height: 1.7;
}
.linked-action-materials {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.linked-action-materials .badge {
  max-width: 100%;
  border: 1px solid var(--line);
  background: var(--white);
  white-space: normal;
}
</style>

<script setup lang="ts">
import { useUnsavedChanges } from "../useUnsavedChanges";
import OperationToast from "./OperationToast.vue";
import { ElButton } from "element-plus/es/components/button/index";
import {
  ElCheckbox,
  ElCheckboxGroup,
} from "element-plus/es/components/checkbox/index";
import { onMounted, ref } from "vue";
import { api, errorMessage, json } from "../api";
import { useAuth } from "../store";
import type { Milestone } from "../types";
import type { ActionLink, ActionTemplate } from "../workflowTypes";
import { label } from "../workflowTypes";
import Modal from "./Modal.vue";
const props = defineProps<{ node: Milestone }>();
const emit = defineEmits<{ changed: [] }>();
const auth = useAuth(),
  links = ref<ActionLink[]>([]),
  templates = ref<ActionTemplate[]>([]),
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
  try {
    links.value = await api<ActionLink[]>(
      `/milestones/${props.node.id}/action-links?plan_item_id=${props.node.plan_item.id}`,
    );
  } catch (e) {
    error.value = errorMessage(e);
  }
}
async function open() {
  show.value = true;
  error.value = "";
  busy.value = true;
  try {
    templates.value = await api<ActionTemplate[]>(
      `/milestones/${props.node.id}/suggested-actions?plan_item_id=${props.node.plan_item.id}`,
    );
    selected.value = links.value
      .filter((l) => l.status === "active")
      .map((l) => l.snapshot_json.id || "")
      .filter(Boolean);
    guard.markSaved();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function save() {
  busy.value = true;
  error.value = "";
  try {
    links.value = await api<ActionLink[]>(
      `/milestones/${props.node.id}/action-links`,
      {
        method: "POST",
        body: json({
          plan_item_id: props.node.plan_item.id,
          plan_version_id: props.node.plan_item.plan_version_id,
          template_item_ids: selected.value,
        }),
      },
    );
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
</script>
<template>
  <section class="form-section">
    <div class="section-title">
      <h3>关联标准动作</h3>
      <ElButton
        :disabled="
          !auth.can(node.project_id) || node.lifecycle_status !== 'active'
        "
        @click="open"
        native-type="submit"
      >
        关联动作模板
      </ElButton>
    </div>
    <p v-if="error && !show" class="error" role="alert">{{ error }}</p>
    <OperationToast v-model="success" :busy="busy" />
    <p v-if="!links.length" class="muted">
      尚未关联批准动作，不会生成对应准备任务。
    </p>
    <div v-for="l in links" :key="l.id" class="action-item">
      <span class="badge">{{ label(l.status) }}</span>
      <div>
        <strong>{{ l.snapshot_json.title }}</strong>
        <p class="muted">
          {{ l.snapshot_json.template_code }} ·
          {{ l.snapshot_json.version_label }} ·
          {{ l.snapshot_json.completion_criteria }}
        </p>
      </div>
    </div>
  </section>
  <Modal
    v-if="show"
    :before-close="guard.confirmDiscard"
    title="关联标准动作"
    drawer
    :busy="busy"
    @close="show = false"
    ><p class="notice">
      当前节点：{{ node.milestone_code }} {{ node.milestone_name }} · 计划{{
        node.plan_item.planned_date
      }}。仅显示已批准且符合适用条件的模板。已有动作保留快照；调整请通过新计划或模板版本。
    </p>
    <p v-if="busy" role="status">正在加载可用模板…</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="!busy && !templates.length" class="empty">
      没有可用的批准模板，请先前往标准动作模块配置。
    </p>
    <ElCheckboxGroup v-model="selected"
      ><section v-for="t in templates" :key="t.id" class="form-section">
        <h3>{{ t.template_code }} · {{ t.title }} · {{ t.version_label }}</h3>
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
              >核实依据：{{ i.completion_criteria }}</small
            ></span
          ></ElCheckbox
        >
      </section></ElCheckboxGroup
    >
    <p class="notice">
      关联动作生成的是准备工作，任务反馈及核实不会自动改变节点实际完成事实。
    </p>
    <template #footer="{ close }"
      ><ElButton :disabled="busy" @click="close" native-type="submit"
        >取消</ElButton
      ><ElButton
        :disabled="busy || !selected.length"
        class="primary"
        @click="save"
        native-type="submit"
        type="primary"
      >
        保存关联配置
      </ElButton></template
    ></Modal
  >
</template>

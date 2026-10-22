<script setup lang="ts">
import { ElInput } from "element-plus/es/components/input/index";
import FormSelect from "./FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import { ElButton } from "element-plus/es/components/button/index";
import { reactive, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useCatalog } from "../store";
import type { ActionTemplate, ActionItem } from "../workflowTypes";
import Modal from "./Modal.vue";
import Icon from "./Icon.vue";
const props = defineProps<{ template?: ActionTemplate; copy?: boolean }>();
const emit = defineEmits<{ close: []; saved: [value: ActionTemplate] }>();
const catalog = useCatalog(),
  busy = ref(false),
  error = ref("");
const blank = (): ActionItem => ({
  item_code: "01",
  title: "",
  completion_criteria: "",
  default_department_id: null,
  materials_required_json: [],
});
const form = reactive({
  template_code: props.template?.template_code || "",
  version_label: props.copy ? "" : props.template?.version_label || "V1",
  title: props.template?.title || "",
  node_type_code: props.template?.node_type_code || "",
  source_ref: props.template?.source_ref || "",
  project_type: props.template?.applicability_json.project_type || "",
  items: props.template?.items.map((i) => ({
    ...i,
    materials: i.materials_required_json.join("\n"),
  })) || [{ ...blank(), materials: "" }],
});
async function save() {
  busy.value = true;
  error.value = "";
  try {
    const edit = props.template && !props.copy;
    const result = await api<ActionTemplate>(
      `/action-templates${edit ? "/" + props.template!.id : ""}`,
      {
        method: edit ? "PATCH" : "POST",
        headers: edit ? versionHeader(props.template!.row_version) : {},
        body: json({
          template_code: form.template_code,
          version_label: form.version_label,
          title: form.title,
          node_type_code: form.node_type_code,
          source_ref: form.source_ref,
          applicability_json: { project_type: form.project_type || null },
          items: form.items.map((i) => ({
            item_code: i.item_code,
            title: i.title,
            completion_criteria: i.completion_criteria,
            default_department_id: i.default_department_id || null,
            materials_required_json: i.materials
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
          })),
        }),
      },
    );
    emit("saved", result);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <Modal
    :title="
      copy ? '创建模板新版本' : template ? '编辑模板草稿' : '创建动作模板'
    "
    wide
    :busy="busy"
    @close="emit('close')"
  >
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <form id="template-form" @submit.prevent="save">
      <div class="form-grid">
        <label
          >模板编号 *<ElInput
            v-model="form.template_code"
            required
            maxlength="64"
            :readonly="!!template"
            :aria-label="'模板编号 *'" /></label
        ><label
          >版本号 *<ElInput
            v-model="form.version_label"
            required
            maxlength="30"
            :readonly="!!template && !copy"
            :aria-label="'版本号 *'" /></label
        ><label
          >模板名称 *<ElInput
            v-model="form.title"
            required
            maxlength="200"
            :aria-label="'模板名称 *'" /></label
        ><label
          >适用节点类型 *<FormSelect
            v-model="form.node_type_code"
            required
            :aria-label="'适用节点类型 *'"
          >
            <ElOption data-ui-value="" value="" :label="'请选择'" />
            <ElOption
              :data-ui-value="n.code"
              v-for="n in catalog.nodeTypes"
              :key="n.code"
              :value="n.code"
              :label="String(n.display_name)"
            /> </FormSelect></label
        ><label
          >适用项目类型（留空表示不限）<ElInput
            v-model="form.project_type"
            maxlength="60"
            :aria-label="'适用项目类型（留空表示不限）'" /></label
        ><label
          >模板来源 *<ElInput
            v-model="form.source_ref"
            required
            maxlength="500"
            :aria-label="'模板来源 *'"
        /></label>
      </div>
      <h3>节点触发后需执行的标准动作</h3>
      <section v-for="(item, i) in form.items" :key="i" class="form-section">
        <div class="form-grid">
          <label
            >动作编号 *<ElInput
              v-model="item.item_code"
              required
              maxlength="50"
              :aria-label="'动作编号 *'" /></label
          ><label
            >动作名称 *<ElInput
              v-model="item.title"
              required
              maxlength="240"
              :aria-label="'动作名称 *'" /></label
          ><label
            >默认责任部门<FormSelect
              v-model="item.default_department_id"
              :aria-label="'默认责任部门'"
            >
              <ElOption data-ui-value="" value="" :label="'沿用节点部门'" />
              <ElOption
                :data-ui-value="d.id"
                v-for="d in catalog.departments"
                :key="d.id"
                :value="d.id"
                :label="String(d.dept_name)"
              /> </FormSelect></label
          ><label
            >完成判定及核实依据 *<ElInput
              v-model="item.completion_criteria"
              required
              maxlength="4000"
              :rows="2"
              type="textarea"
              :aria-label="'完成判定及核实依据 *'" /></label
          ><label
            >所需材料（每行一项）<ElInput
              v-model="item.materials"
              :rows="2"
              type="textarea"
              :aria-label="'所需材料（每行一项）'"
            />
          </label>
        </div>
        <ElButton
          :disabled="form.items.length === 1"
          @click="form.items.splice(i, 1)"
          native-type="button"
        >
          移除此项
        </ElButton>
      </section>
      <ElButton
        :disabled="form.items.length >= 100"
        @click="
          form.items.push({
            ...blank(),
            item_code: String(form.items.length + 1).padStart(2, '0'),
            materials: '',
          })
        "
        native-type="button"
      >
        添加动作项
      </ElButton>
    </form>
    <template #footer
      ><ElButton :disabled="busy" @click="emit('close')" native-type="submit"
        >取消</ElButton
      ><ElButton form="template-form" :disabled="busy" native-type="submit">
        <Icon name="imgVectorSave" />保存草稿
      </ElButton></template
    >
  </Modal>
</template>

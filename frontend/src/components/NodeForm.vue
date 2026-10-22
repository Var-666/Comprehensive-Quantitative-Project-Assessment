<script setup lang="ts">
import { ElInput } from "element-plus/es/components/input/index";
import FormSelect from "./FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import FormDate from "./FormDate.vue";
import { ElButton } from "element-plus/es/components/button/index";
import { onMounted, reactive, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useCatalog } from "../store";
import type { Milestone, Plan, Project } from "../types";
import Modal from "./Modal.vue";
const props = defineProps<{ project: Project; plan: Plan; node?: Milestone }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const catalog = useCatalog(),
  busy = ref(false),
  error = ref("");
const form = reactive({
  milestone_code: props.node?.milestone_code || "",
  milestone_name: props.node?.milestone_name || "",
  node_type_code: props.node?.plan_item.node_type_code || "",
  planned_date: props.node?.plan_item.planned_date || "",
  date_kind: props.node?.plan_item.date_kind || "internal_plan",
  department_id: props.node?.plan_item.department_id || "",
  owner_id: props.node?.plan_item.owner_id || "",
  source_ref: props.node?.plan_item.source_ref || "",
  change_reason: "",
});
onMounted(async () => {
  try {
    await catalog.load();
  } catch (e) {
    error.value = errorMessage(e);
  }
});
async function save() {
  busy.value = true;
  error.value = "";
  try {
    await api(
      props.node
        ? `/milestones/${props.node.id}/plan-item`
        : `/projects/${props.project.id}/milestones`,
      {
        method: props.node ? "PATCH" : "POST",
        headers: props.node ? versionHeader(props.node.row_version) : {},
        body: json({
          ...form,
          plan_version_id: props.plan.id,
          department_id: form.department_id || null,
          owner_id: form.owner_id || null,
        }),
      },
    );
    emit("saved");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <Modal
    class="node-form-modal"
    :title="node ? '编辑节点计划草稿' : '新增项目节点'"
    subtitle="设置节点基本属性；草稿计划需独立批准后生效"
    :busy="busy"
    @close="emit('close')"
  >
    <form id="node-form" @submit.prevent="save">
      <p class="notice">
        {{ project.project_code }} · {{ project.project_name }} /
        {{ plan.version_label }} 草稿
      </p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <section class="form-section">
        <h3>节点基本信息</h3>
        <div class="form-grid">
          <label
            >节点编号 *<ElInput
              v-model="form.milestone_code"
              required
              maxlength="64"
              :readonly="!!node"
              :aria-label="'节点编号 *'" /></label
          ><label
            >节点名称 *<ElInput
              v-model="form.milestone_name"
              required
              maxlength="200"
              :aria-label="'节点名称 *'"
          /></label>
          <label
            >节点类型 *<FormSelect
              v-model="form.node_type_code"
              required
              :aria-label="'节点类型 *'"
            >
              <ElOption data-ui-value="" value="" disabled :label="'请选择'" />
              <ElOption
                :data-ui-value="t.code"
                v-for="t in catalog.nodeTypes"
                :key="t.code"
                :value="t.code"
                :label="String(t.display_name)"
              /> </FormSelect></label
          ><label
            >计划完成日期 *<FormDate
              v-model="form.planned_date"
              required
              :aria-label="'计划完成日期 *'"
          /></label>
          <label
            >责任部门<FormSelect
              v-model="form.department_id"
              :aria-label="'责任部门'"
            >
              <ElOption data-ui-value="" value="" :label="'未指定'" />
              <ElOption
                :data-ui-value="d.id"
                v-for="d in catalog.departments"
                :key="d.id"
                :value="d.id"
                :label="String(d.dept_name)"
              /> </FormSelect></label
          ><label
            >责任人<FormSelect v-model="form.owner_id" :aria-label="'责任人'">
              <ElOption data-ui-value="" value="" :label="'未指定'" />
              <ElOption
                :data-ui-value="u.id"
                v-for="u in catalog.users"
                :key="u.id"
                :value="u.id"
                :label="String(u.display_name)"
              /> </FormSelect
          ></label>
          <label
            >日期性质<FormSelect
              v-model="form.date_kind"
              :aria-label="'日期性质'"
            >
              <ElOption
                data-ui-value="internal_plan"
                value="internal_plan"
                :label="'内部计划'"
              />
              <ElOption
                data-ui-value="contractual"
                value="contractual"
                :label="'合同约定（需来源）'"
              />
              <ElOption
                data-ui-value="unconfirmed"
                value="unconfirmed"
                :label="'待确认'"
              /> </FormSelect></label
          ><label
            >日期依据说明<ElInput
              v-model="form.source_ref"
              maxlength="500"
              :required="form.date_kind === 'contractual'"
              :aria-label="'日期依据说明'"
          /></label>
        </div>
        <label
          >录入 / 变更原因 *<ElInput
            v-model="form.change_reason"
            required
            maxlength="2000"
            :rows="2"
            type="textarea"
            :aria-label="'录入 / 变更原因 *'"
          />
        </label>
      </section>
      <p class="notice warning">
        内部计划调整不自动修改合同义务。实际完成日期须在节点详情中单独提交与核实；标准动作与提醒通过已批准的模板和规则配置。
      </p>
    </form>
    <template #footer
      ><ElButton :disabled="busy" @click="emit('close')" native-type="submit"
        >取消</ElButton
      ><ElButton
        form="node-form"
        class="primary"
        :disabled="busy"
        native-type="submit"
        type="primary"
      >
        {{ busy ? "保存中…" : "保存节点" }}
      </ElButton></template
    >
  </Modal>
</template>

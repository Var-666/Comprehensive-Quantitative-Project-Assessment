<script setup lang="ts">
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
            >节点编号 *<input
              v-model="form.milestone_code"
              required
              maxlength="64"
              :readonly="!!node" /></label
          ><label
            >节点名称 *<input
              v-model="form.milestone_name"
              required
              maxlength="200"
          /></label>
          <label
            >节点类型 *<select v-model="form.node_type_code" required>
              <option value="" disabled>请选择</option>
              <option
                v-for="t in catalog.nodeTypes"
                :key="t.code"
                :value="t.code"
              >
                {{ t.display_name }}
              </option>
            </select></label
          ><label
            >计划完成日期 *<input
              v-model="form.planned_date"
              type="date"
              required
          /></label>
          <label
            >责任部门<select v-model="form.department_id">
              <option value="">未指定</option>
              <option
                v-for="d in catalog.departments"
                :key="d.id"
                :value="d.id"
              >
                {{ d.dept_name }}
              </option>
            </select></label
          ><label
            >责任人<select v-model="form.owner_id">
              <option value="">未指定</option>
              <option v-for="u in catalog.users" :key="u.id" :value="u.id">
                {{ u.display_name }}
              </option>
            </select></label
          >
          <label
            >日期性质<select v-model="form.date_kind">
              <option value="internal_plan">内部计划</option>
              <option value="contractual">合同约定（需来源）</option>
              <option value="unconfirmed">待确认</option>
            </select></label
          ><label
            >日期依据说明<input
              v-model="form.source_ref"
              maxlength="500"
              :required="form.date_kind === 'contractual'"
          /></label>
        </div>
        <label
          >录入 / 变更原因 *<textarea
            v-model="form.change_reason"
            required
            maxlength="2000"
            rows="2"
          />
        </label>
      </section>
      <p class="notice warning">
        内部计划调整不自动修改合同义务。实际完成日期须在节点详情中单独提交与核实；标准动作与提醒通过已批准的模板和规则配置。
      </p>
    </form>
    <template #footer
      ><button :disabled="busy" @click="emit('close')">取消</button
      ><button type="submit" form="node-form" class="primary" :disabled="busy">
        {{ busy ? "保存中…" : "保存节点" }}
      </button></template
    >
  </Modal>
</template>

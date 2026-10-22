<script setup lang="ts">
import { ElInput } from "element-plus/es/components/input/index";
import FormSelect from "./FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import FormDate from "./FormDate.vue";
import { ElButton } from "element-plus/es/components/button/index";
import { onMounted, reactive, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useCatalog, useAuth } from "../store";
import { statuses, type Project } from "../types";
import Modal from "./Modal.vue";
const props = defineProps<{ project?: Project }>();
const emit = defineEmits<{ close: []; saved: [project: Project] }>();
const catalog = useCatalog();
const busy = ref(false),
  error = ref("");
const form = reactive({
  project_code: props.project?.project_code || "",
  project_name: props.project?.project_name || "",
  project_type: props.project?.project_type || "",
  project_status: props.project?.project_status || "not_started",
  owner_id: props.project?.owner_id || "",
  department_id: props.project?.department_id || "",
  planned_start: props.project?.planned_start || "",
  planned_end: props.project?.planned_end || "",
  attention_note: props.project?.attention_note || "",
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
    const payload = {
      ...form,
      owner_id: form.owner_id || null,
      department_id: form.department_id || null,
      planned_start: form.planned_start || null,
      planned_end: form.planned_end || null,
    };
    const result = await api<Project>(
      props.project ? `/projects/${props.project.id}` : "/projects",
      {
        method: props.project ? "PATCH" : "POST",
        headers: props.project ? versionHeader(props.project.row_version) : {},
        body: json(payload),
      },
    );
    await useAuth().load();
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
    :title="project ? '编辑项目' : '新建项目'"
    :subtitle="
      project
        ? '修改项目基本信息，计划版本与实际事实独立管理'
        : '建立项目台账，后续可录入节点与标准动作'
    "
    :busy="busy"
    @close="emit('close')"
  >
    <form id="project-form" @submit.prevent="save">
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <section class="form-section">
        <h3>项目基本信息</h3>
        <div class="form-grid">
          <label
            >项目编号 *<ElInput
              v-model="form.project_code"
              required
              maxlength="64"
              :aria-label="'项目编号 *'"
          /></label>
          <label
            >项目名称 *<ElInput
              v-model="form.project_name"
              required
              maxlength="200"
              :aria-label="'项目名称 *'"
          /></label>
          <label
            >项目类型<ElInput
              v-model="form.project_type"
              list="project-types"
              maxlength="60"
              :aria-label="'项目类型'"
            /><datalist id="project-types">
              <option>船舶建造</option>
              <option>试制项目</option>
              <option>修理改造</option>
            </datalist></label
          >
          <label
            >项目状态<FormSelect
              v-model="form.project_status"
              :aria-label="'项目状态'"
            >
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
              /> </FormSelect
          ></label>
          <label
            >项目负责人<FormSelect
              v-model="form.owner_id"
              :aria-label="'项目负责人'"
            >
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
              /> </FormSelect
          ></label>
        </div>
      </section>
      <section class="form-section">
        <h3>计划时间与备注</h3>
        <div class="form-grid">
          <label
            >计划开始日期<FormDate
              v-model="form.planned_start"
              :aria-label="'计划开始日期'" /></label
          ><label
            >预计结束日期<FormDate
              v-model="form.planned_end"
              :min="form.planned_start"
              :aria-label="'预计结束日期'"
          /></label>
        </div>
        <label
          >关注说明<ElInput
            v-model="form.attention_note"
            maxlength="2000"
            :rows="2"
            type="textarea"
            :aria-label="'关注说明'"
          />
        </label>
      </section>
      <p class="notice">
        项目编号必须唯一，正式编号规则与类型目录待确认。新建项目仅创建初始计划草稿，不自动生成业务节点。
      </p>
    </form>
    <template #footer
      ><ElButton :disabled="busy" @click="emit('close')" native-type="submit"
        >取消</ElButton
      ><ElButton
        class="primary"
        form="project-form"
        :disabled="busy"
        native-type="submit"
        type="primary"
      >
        {{ busy ? "保存中…" : "保存并进入详情" }}
      </ElButton></template
    >
  </Modal>
</template>

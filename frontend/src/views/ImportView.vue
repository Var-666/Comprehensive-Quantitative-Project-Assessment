<script setup lang="ts">
import { ElInput } from "element-plus/es/components/input/index";
import { ElCheckbox } from "element-plus/es/components/checkbox/index";
import { ElButton } from "element-plus/es/components/button/index";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useUnsavedChanges } from "../useUnsavedChanges";
import {
  ElUpload,
  type UploadFile,
  type UploadInstance,
  type UploadRawFile,
} from "element-plus/es/components/upload/index";
import { api, errorMessage, json } from "../api";
import type { Batch, Project, Plan } from "../types";
import StatusBadge from "../components/StatusBadge.vue";
import { useAuth } from "../store";
const route = useRoute(),
  router = useRouter(),
  auth = useAuth();
const projectId =
  typeof route.query.project === "string" ? route.query.project : undefined;
const planId =
  typeof route.query.plan === "string" ? route.query.plan : undefined;
const target = route.query.target === "milestones" ? "milestones" : "projects";
const contextReady = ref(false),
  contextTitle = ref("");
const returnTo = projectId
  ? { path: "/milestones", query: { project: projectId, plan: planId } }
  : { path: "/projects" };
function leave() {
  void router.push(returnTo);
}

const file = ref<File>(),
  busy = ref(false),
  error = ref(""),
  batch = ref<Batch>(),
  confirmed = ref(false);
const sheet = ref(projectId ? "02_节点计划" : "01_项目台账"),
  header = ref(6);
const mapping = ref<Record<string, string>>(
  projectId
    ? {
        project_code: "项目编号",
        milestone_code: "节点编号",
        milestone_name: "节点名称",
        node_type_code: "节点类型",
        planned_date: "计划完成日期",
        department_name: "责任部门",
        owner_name: "责任人",
        source_ref: "日期依据",
      }
    : {
        project_code: "项目编号",
        project_name: "项目名称",
        project_type: "项目类型",
        owner_name: "项目负责人",
        department_name: "责任部门",
        project_status: "项目状态",
        planned_start: "计划开始",
        planned_end: "计划结束",
      },
);
const committed = computed(() => !!batch.value?.result_json);
const guard = useUnsavedChanges(
  () => ({
    file: file.value
      ? {
          name: file.value.name,
          size: file.value.size,
          modified: file.value.lastModified,
        }
      : null,
    sheet: sheet.value,
    header: header.value,
    mapping: mapping.value,
  }),
  () => !committed.value,
  () => busy.value,
);
const idempotencyKey = crypto.randomUUID();
onMounted(async () => {
  try {
    if (!["projects", "milestones"].includes(String(route.query.target)))
      throw new Error("导入目标无效，请从项目或节点页面重新进入。");
    if (target === "projects") {
      if (projectId || planId)
        throw new Error("项目导入不接受节点计划上下文，请从项目页重新进入。");
      if (!auth.user?.is_system_admin)
        throw new Error("仅系统管理员可导入项目。");
      contextTitle.value = "项目台账导入";
    } else {
      if (!projectId || !planId || !auth.can(projectId))
        throw new Error("缺少项目编辑权限或草稿计划，请从节点页面重新进入。");
      const [project, plans] = await Promise.all([
        api<Project>(`/projects/${projectId}`),
        api<Plan[]>(`/projects/${projectId}/plan-versions`),
      ]);
      const plan = plans.find((p) => p.id === planId);
      if (
        !plan ||
        plan.status !== "draft" ||
        project.project_status === "archived"
      )
        throw new Error(
          "只能向当前项目的草稿计划导入节点，请返回节点页重新选择。",
        );
      contextTitle.value = `${project.project_code} · ${project.project_name} / ${plan.version_label} 草稿`;
    }
    contextReady.value = true;
  } catch (e) {
    contextTitle.value = "导入条件不满足";
    error.value = errorMessage(e);
  }
});
const upload = ref<UploadInstance>();
function choose(value: UploadFile) {
  file.value = value.raw;
}
function replace(files: File[]) {
  upload.value?.clearFiles();
  upload.value?.handleStart(files[0] as UploadRawFile);
}
async function preview() {
  if (!file.value) {
    error.value = "请选择 Excel 文件";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const data = new FormData();
    data.append("file", file.value);
    data.append("target", target);
    data.append("sheet_name", sheet.value);
    data.append("header_row", String(header.value));
    data.append(
      "mapping_json",
      json(
        Object.fromEntries(
          Object.entries(mapping.value).filter(([, v]) => v.trim()),
        ),
      ),
    );
    if (projectId) data.append("project_id", projectId);
    if (planId) data.append("plan_version_id", planId);
    batch.value = await api<Batch>("/imports/preview", {
      method: "POST",
      body: data,
    });
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function commit() {
  busy.value = true;
  error.value = "";
  try {
    batch.value = await api<Batch>(`/imports/${batch.value!.id}/commit`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: json({
        preview_hash: batch.value!.preview_hash,
        include_valid_only: false,
      }),
    });
    await useAuth().load();
    guard.markSaved();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="page-title">
    <div>
      <h1>Excel 数据导入</h1>
      <p>{{ contextTitle || "正在核对导入权限与计划…" }}</p>
    </div>
    <ElButton :disabled="busy" @click="leave" native-type="button">{{
      committed ? "返回台账" : "返回来源页面"
    }}</ElButton>
  </div>
  <section class="card import-workspace" :aria-busy="busy">
    <div class="steps">
      <span :class="{ selected: !batch }">① 选择文件与映射</span
      ><span :class="{ selected: batch && !committed }">② 校验预览</span
      ><span :class="{ selected: committed }">③ 确认与结果</span>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="!batch">
      <section class="form-section">
        <h3>文件来源（仅本地演示）</h3>
        <ElUpload
          ref="upload"
          accept=".xlsx"
          :auto-upload="false"
          :limit="1"
          :on-change="choose"
          :on-remove="() => (file = undefined)"
          :on-exceed="replace"
          ><ElButton native-type="button">选择 Excel 文件</ElButton></ElUpload
        >
        <p class="muted">
          仅 .xlsx，最大 5MB，最多 2,000 行。默认映射适配提供的模拟工作簿。
        </p>
      </section>
      <section class="form-section">
        <div class="form-grid">
          <label
            >工作表名称<ElInput
              v-model="sheet"
              placeholder="留空使用首个工作表"
              :aria-label="'工作表名称'" /></label
          ><label
            >表头行号<ElInput
              v-model.number="header"
              type="number"
              min="1"
              max="50"
              :aria-label="'表头行号'"
          /></label>
        </div>
      </section>
      <section class="form-section">
        <h3>Excel 字段与系统字段映射</h3>
        <p class="muted">
          右侧填写实际列名；可清空选填字段。必填字段将在后端校验。
        </p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>系统字段</th>
                <th>Excel 列名</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(_, field) in mapping" :key="field">
                <td>{{ field }}</td>
                <td>
                  <ElInput
                    v-model="mapping[field]"
                    :aria-label="String(field)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
    <template v-else>
      <p :class="committed ? 'success' : 'notice'">
        {{
          committed
            ? `导入完成：写入 ${batch.result_json!.inserted} 行，跳过 ${batch.result_json!.skipped} 行`
            : `校验完成：合法 ${batch.valid_rows} 行，错误/重复 ${batch.error_rows} 行。尚未写入业务数据。`
        }}
      </p>
      <p class="muted">批次 {{ batch.id }} · {{ batch.filename }}</p>
      <div class="table-wrap preview-table">
        <table>
          <thead>
            <tr>
              <th>工作表 / 行号</th>
              <th>数据预览</th>
              <th>状态</th>
              <th>失败原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in batch.rows" :key="row.id">
              <td>{{ row.sheet_name }} / {{ row.source_row_number }}</td>
              <td>
                <div v-for="(value, key) in row.raw_json" :key="key">
                  {{ key }}：{{ value ?? "空" }}
                </div>
              </td>
              <td><StatusBadge :value="row.row_status" /></td>
              <td>
                <p v-for="(err, i) in row.validation_errors_json" :key="i">
                  {{ err.field }} · {{ err.message }}
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="batch.error_rows" class="notice warning">
        本版默认整批原子导入。请修正错误或重复行后重新上传；已有数据不会覆盖。
      </p>
      <a
        v-if="batch.error_rows"
        :href="`/api/v1/imports/${batch.id}/errors`"
        download
        >下载错误行 CSV</a
      >
      <ElCheckbox
        v-if="!committed && !batch.error_rows"
        class="check"
        v-model="confirmed"
        >我已核对预览，确认将合法数据写入本地演示库</ElCheckbox
      >
    </template>
    <footer class="import-footer">
      <ElButton :disabled="busy" @click="leave" native-type="submit">
        {{ committed ? "完成" : "取消" }}
      </ElButton>
      <ElButton
        v-if="batch && !committed"
        :disabled="busy"
        @click="
          batch = undefined;
          confirmed = false;
        "
        native-type="submit"
      >
        重新选择文件
      </ElButton>
      <ElButton
        v-if="!batch"
        class="primary"
        :disabled="busy || !file || !contextReady"
        @click="preview"
        native-type="submit"
        type="primary"
      >
        {{ busy ? "校验中…" : "下一步：校验预览" }}
      </ElButton>
      <ElButton
        v-else-if="!committed"
        class="primary"
        :disabled="busy || !!batch.error_rows || !confirmed"
        @click="commit"
        native-type="submit"
        type="primary"
      >
        {{ busy ? "写入中…" : "确认导入" }}
      </ElButton>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { api, errorMessage, json } from "../api";
import type { Batch } from "../types";
import Modal from "./Modal.vue";
import StatusBadge from "./StatusBadge.vue";
import { useAuth } from "../store";
const props = defineProps<{ projectId?: string; planId?: string }>();
const emit = defineEmits<{ close: []; imported: [] }>();
const target = props.projectId ? "milestones" : "projects";
const file = ref<File>(),
  busy = ref(false),
  error = ref(""),
  batch = ref<Batch>(),
  confirmed = ref(false);
const sheet = ref(props.projectId ? "02_节点计划" : "01_项目台账"),
  header = ref(6);
const mapping = ref<Record<string, string>>(
  props.projectId
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
const idempotencyKey = crypto.randomUUID();
function choose(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0];
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
    if (props.projectId) data.append("project_id", props.projectId);
    if (props.planId) data.append("plan_version_id", props.planId);
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
    emit("imported");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <Modal
    title="Excel 数据导入 · 字段映射与校验"
    wide
    :busy="busy"
    @close="emit('close')"
  >
    <div class="steps">
      <span :class="{ selected: !batch }">① 选择文件与映射</span
      ><span :class="{ selected: batch && !committed }">② 校验预览</span
      ><span :class="{ selected: committed }">③ 确认与结果</span>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="!batch">
      <section class="form-section">
        <h3>文件来源（仅本地演示）</h3>
        <input
          type="file"
          accept=".xlsx"
          aria-label="Excel 文件"
          @change="choose"
        />
        <p class="muted">
          仅 .xlsx，最大 5MB，最多 2,000 行。默认映射适配提供的模拟工作簿。
        </p>
      </section>
      <section class="form-section">
        <div class="form-grid">
          <label
            >工作表名称<input
              v-model="sheet"
              placeholder="留空使用首个工作表" /></label
          ><label
            >表头行号<input
              v-model.number="header"
              type="number"
              min="1"
              max="50"
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
                  <input v-model="mapping[field]" :aria-label="String(field)" />
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
      <label v-if="!committed && !batch.error_rows" class="check"
        ><input
          v-model="confirmed"
          type="checkbox"
        />我已核对预览，确认将合法数据写入本地演示库</label
      >
    </template>
    <template #footer>
      <button :disabled="busy" @click="emit('close')">
        {{ committed ? "完成" : "取消" }}
      </button>
      <button
        v-if="batch && !committed"
        :disabled="busy"
        @click="
          batch = undefined;
          confirmed = false;
        "
      >
        重新选择文件
      </button>
      <button
        v-if="!batch"
        class="primary"
        :disabled="busy || !file"
        @click="preview"
      >
        {{ busy ? "校验中…" : "下一步：校验预览" }}
      </button>
      <button
        v-else-if="!committed"
        class="primary"
        :disabled="busy || !!batch.error_rows || !confirmed"
        @click="commit"
      >
        {{ busy ? "写入中…" : "确认导入" }}
      </button>
    </template>
  </Modal>
</template>

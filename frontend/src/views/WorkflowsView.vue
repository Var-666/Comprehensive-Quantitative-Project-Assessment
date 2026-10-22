<script setup lang="ts">
import { useUnsavedChanges } from "../useUnsavedChanges";
import OperationToast from "../components/OperationToast.vue";
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { ElButton } from "element-plus/es/components/button/index";
import { ElDatePicker } from "element-plus/es/components/date-picker/index";
import {
  ElForm,
  ElFormItem,
  type FormInstance,
} from "element-plus/es/components/form/index";
import { ElOption, ElSelect } from "element-plus/es/components/select/index";
import { ElPagination } from "element-plus/es/components/pagination/index";
import { api, errorMessage, json, versionHeader } from "../api";
import { useAuth, useCatalog } from "../store";
import type { Page, Project } from "../types";
import type {
  InboxRecord,
  Notice,
  ScanRow,
  TaskRecord,
} from "../workflowTypes";
import { label } from "../workflowTypes";
import Modal from "../components/Modal.vue";
import Icon from "../components/Icon.vue";
import TaskDrawer from "../components/TaskDrawer.vue";
const route = useRoute();
const auth = useAuth(),
  catalog = useCatalog(),
  tab = ref(route.query.tab === "tasks" ? "tasks" : "notices"),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  projectId = ref(String(route.query.project || "")),
  status = ref(""),
  mine = ref(false),
  projects = ref<Project[]>([]),
  notices = ref<Page<Notice>>({ items: [], total: 0, page: 1, page_size: 20 }),
  tasks = ref<Page<TaskRecord>>({
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
  }),
  inbox = ref<InboxRecord[]>([]),
  selected = ref<Notice>(),
  showTask = ref<TaskRecord>(),
  reviewAction = ref(""),
  reviewComment = ref(""),
  confirmed = ref(false);
const aiConfig = ref<{ provider: string; mode_label: string }>(),
  aiConsent = ref(false);
async function arrangeDraft() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    const r = await api<{ notice: Notice; generation: { label: string } }>(
      `/notifications/${selected.value.id}/ai-draft`,
      {
        method: "POST",
        headers: versionHeader(selected.value.row_version),
        body: json({ allow_external: aiConsent.value }),
      },
    );
    choose(r.notice);
    success.value = r.generation.label + "；草稿已保存，仍需独立审核。";
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
const edit = reactive({ title: "", body: "" });
const today = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(new Date());
const scan = reactive({
  as_of: today,
  result: [] as ScanRow[],
  generated: null as number | null,
  previewed: false,
  project: "",
});
const scanForm = ref<FormInstance>();
const canWrite = computed(
  () => !!selected.value && auth.can(selected.value.project_id),
);
const canReview = computed(
  () =>
    !!selected.value &&
    auth.can(selected.value.project_id, "review") &&
    !selected.value.editor_ids.includes(auth.user?.user_id || ""),
);
const editable = computed(
  () =>
    selected.value &&
    ["draft", "returned"].includes(selected.value.status) &&
    canWrite.value,
);
function choose(n?: Notice) {
  selected.value = n;
  edit.title = n?.title || "";
  edit.body = n?.body || "";
}
async function load(page = 1) {
  busy.value = true;
  error.value = "";
  try {
    const q = new URLSearchParams({
      project_id: projectId.value,
      status: status.value,
      page: String(page),
      page_size: "20",
    });
    if (tab.value === "notices") {
      notices.value = await api<Page<Notice>>(`/notifications?${q}`);
      choose(
        notices.value.items.find((n) => n.id === selected.value?.id) ||
          (notices.value.items[0] as Notice),
      );
    } else if (tab.value === "tasks") {
      tasks.value = await api<Page<TaskRecord>>(
        `/tasks?${q}&mine=${mine.value}`,
      );
    } else if (tab.value === "inbox")
      inbox.value = await api<InboxRecord[]>("/inbox");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function switchTab(value: string) {
  tab.value = value;
  status.value = "";
  success.value = "";
  await load();
}
async function mutate(
  path: string,
  body?: unknown,
  method = "POST",
  message = "操作已保存",
) {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await api<Notice>(
      `/notifications/${selected.value.id}/${path}`,
      {
        method,
        headers: versionHeader(selected.value.row_version),
        ...(body === undefined ? {} : { body: json(body) }),
      },
    );
    choose(result);
    reviewAction.value = "";
    success.value = message;
    await load(notices.value.page);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function openReview(action: string) {
  reviewAction.value = action;
  reviewComment.value = "";
  confirmed.value = false;
}
const reviewGuard = useUnsavedChanges(
  () => ({ comment: reviewComment.value, confirmed: confirmed.value }),
  () => !!reviewAction.value,
  () => busy.value,
);
async function review() {
  await mutate(
    "review",
    {
      draft_version: selected.value!.draft_version,
      decision: reviewAction.value,
      comment: reviewComment.value,
    },
    "POST",
    "审核结果已保存；审核通过仍处于待发送状态",
  );
}
async function run(generate = false) {
  if (!(await scanForm.value?.validate().catch(() => false))) return;
  busy.value = true;
  error.value = "";
  try {
    const r = await api<{ items: ScanRow[]; generated: number }>(
      `/reminder-jobs/${generate ? "run" : "simulate"}`,
      {
        method: "POST",
        body: json({ as_of: scan.as_of, project_ids: [scan.project] }),
      },
    );
    scan.result = r.items;
    scan.generated = generate ? r.generated : null;
    scan.previewed = true;
    if (generate)
      success.value = `已发送${r.generated}条站内提醒；重复项已跳过。任务尚待人工分派。`;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function read(m: InboxRecord) {
  try {
    await api(`/inbox/${m.id}/read`, { method: "POST" });
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  }
}
onMounted(async () => {
  try {
    await catalog.load();
    aiConfig.value = await api("/ai/config");
    let n = 1;
    while (true) {
      const p = await api<Page<Project>>(`/projects?page_size=100&page=${n}`);
      projects.value.push(...p.items);
      if (projects.value.length >= p.total) break;
      n++;
    }
    scan.project = projects.value[0]?.id || "";
    await load();
    if (tab.value === "tasks" && route.query.task) {
      showTask.value = await api<TaskRecord>(
        `/tasks/${encodeURIComponent(String(route.query.task))}`,
      );
    }
  } catch (e) {
    error.value = errorMessage(e);
  }
});
</script>
<template>
  <div class="page-title">
    <div>
      <h1>提醒与待办</h1>
      <p>按已批准规则自动发送站内提醒并生成待办，对外正式函件仍需审批</p>
    </div>
    <ElButton type="primary" class="primary" @click="switchTab('scan')">
      <Icon name="imgVectorPlus" />预览与补充扫描
    </ElButton>
  </div>
  <div class="workbench-toolbar">
    <div class="tabs">
      <ElButton
        :class="{ primary: tab === 'notices' }"
        :type="tab === 'notices' ? 'primary' : 'default'"
        @click="switchTab('notices')"
      >
        通知队列</ElButton
      ><ElButton
        :class="{ primary: tab === 'tasks' }"
        :type="tab === 'tasks' ? 'primary' : 'default'"
        @click="switchTab('tasks')"
      >
        执行任务</ElButton
      ><ElButton
        :class="{ primary: tab === 'inbox' }"
        :type="tab === 'inbox' ? 'primary' : 'default'"
        @click="switchTab('inbox')"
      >
        站内收件箱</ElButton
      ><ElButton
        :class="{ primary: tab === 'scan' }"
        :type="tab === 'scan' ? 'primary' : 'default'"
        @click="switchTab('scan')"
      >
        提醒扫描
      </ElButton>
    </div>
    <p v-if="error" class="error" role="alert">
      {{ error }} <ElButton @click="load()">重试</ElButton>
    </p>
    <OperationToast v-model="success" :busy="busy" />
    <form
      v-if="['notices', 'tasks'].includes(tab)"
      class="filters compact"
      @submit.prevent="load()"
    >
      <label for="work-project"
        >筛选项目<ElSelect
          id="work-project"
          v-model="projectId"
          aria-label="筛选项目"
          filterable
          :disabled="busy"
          :empty-values="[undefined, null]"
          popper-class="project-element-popper"
          class="work-project-select"
        >
          <ElOption label="全部授权项目" value="" />
          <ElOption
            v-for="p in projects"
            :key="p.id"
            :value="p.id"
            :label="`${p.project_code} · ${p.project_name}`"
          /> </ElSelect></label
      ><label for="work-status"
        >工作状态<ElSelect
          id="work-status"
          v-model="status"
          aria-label="工作状态"
          :disabled="busy"
          :empty-values="[undefined, null]"
          popper-class="project-element-popper"
          class="work-status-select"
        >
          <ElOption label="全部" value="" />
          <ElOption
            v-for="s in tab === 'notices'
              ? [
                  'draft',
                  'pending_review',
                  'returned',
                  'approved_pending_send',
                  'sent',
                  'invalidated',
                ]
              : [
                  'unassigned',
                  'todo',
                  'in_progress',
                  'submitted',
                  'returned',
                  'verified_done',
                  'cancelled',
                ]"
            :key="s"
            :value="s"
            :label="label(s)"
          /> </ElSelect></label
      ><label v-if="tab === 'tasks'" class="checkbox-line"
        ><input v-model="mine" type="checkbox" />仅看分派给我</label
      ><ElButton native-type="submit" :loading="busy">查询工作</ElButton>
    </form>
  </div>
  <p v-if="busy" class="muted" role="status">正在处理…</p>
  <div v-if="tab === 'notices'" class="workflow-split notice-split">
    <section class="card queue">
      <h3>
        通知记录 <span class="badge">共{{ notices.total }}条</span>
      </h3>
      <p v-if="!notices.items.length && !busy" class="empty">
        暂无通知。可先配置标准动作和规则，再预览提醒扫描。
      </p>
      <button
        v-for="n in notices.items"
        :key="n.id"
        class="queue-item"
        :class="{ selected: selected?.id === n.id }"
        @click="choose(n)"
      >
        <strong>{{ n.title }}</strong
        ><span class="badge">{{ label(n.status) }}</span
        ><small
          >{{ n.fact_snapshot_json.planned_date }} · 提前{{
            n.fact_snapshot_json.days_before
          }}个{{ label(n.fact_snapshot_json.day_basis) }}</small
        >
      </button>
      <ElPagination
        class="work-pagination"
        :current-page="notices.page"
        :page-size="20"
        :total="notices.total"
        :disabled="busy"
        layout="prev, pager, next"
        prev-text="上一页"
        next-text="下一页"
        :pager-count="5"
        @current-change="load"
      />
    </section>
    <section v-if="selected" class="card workflow-detail">
      <div class="section-title">
        <h2>
          <Icon name="imgVectorBell" />{{
            selected.fact_snapshot_json.milestone_name
          }}准备提醒
        </h2>
        <span class="badge" :class="selected.status">{{
          label(selected.status)
        }}</span>
      </div>
      <div class="fact-box">
        <strong
          >项目：{{ selected.fact_snapshot_json.project_code }}
          {{ selected.fact_snapshot_json.project_name }}</strong
        >
        <p>
          计划节点：{{ selected.fact_snapshot_json.planned_date }} |
          提醒触发：{{ selected.fact_snapshot_json.trigger_date }}
        </p>
        <p>
          接收人：{{ selected.fact_snapshot_json.recipient_name }} | 依据：{{
            selected.fact_snapshot_json.plan_version
          }}
          · {{ selected.fact_snapshot_json.rule_code }}
          {{ selected.fact_snapshot_json.rule_version }}
        </p>
        <p>来源：{{ selected.fact_snapshot_json.source_ref }}</p>
      </div>
      <h3>通知内容 · 第{{ selected.draft_version }}版</h3>
      <p
        v-if="selected.status !== 'sent' && selected.status !== 'invalidated'"
        class="notice"
      >
        此为历史流程遗留草稿；新触发的规则提醒会直接投递站内收件箱。
      </p>
      <p v-if="editable" class="notice warning">
        {{ aiConfig?.mode_label }} · AI
        仅整理已批准来源事实，不能改变提醒日期或核实状态。
      </p>
      <label
        v-if="editable && aiConfig?.provider !== 'mock'"
        class="inline-label"
        ><input
          v-model="aiConsent"
          type="checkbox"
        />允许本次外送事实ID与分类（不含正文）</label
      >
      <ElButton
        v-if="editable"
        :disabled="busy || (!aiConsent && aiConfig?.provider !== 'mock')"
        @click="arrangeDraft"
      >
        AI 整理通知草稿
      </ElButton>
      <template v-if="editable"
        ><label
          >通知标题<input
            v-model="edit.title"
            required
            maxlength="200" /></label
        ><label
          >通知正文<textarea
            v-model="edit.body"
            :rows="10"
            required
            maxlength="12000"
          />
        </label>
        <div class="actions">
          <ElButton
            :disabled="busy || !edit.title.trim() || !edit.body.trim()"
            @click="
              mutate('draft', edit, 'PATCH', '草稿修订已保存，需重新审核')
            "
          >
            <Icon name="imgVectorSave" />保存通知草稿</ElButton
          ><ElButton
            type="primary"
            class="primary"
            :disabled="
              busy ||
              edit.title !== selected.title ||
              edit.body !== selected.body
            "
            @click="
              mutate('submit-review', undefined, 'POST', '通知已提交独立审核')
            "
          >
            提交通知审核
          </ElButton>
        </div>
        <p
          v-if="edit.title !== selected.title || edit.body !== selected.body"
          class="muted"
        >
          请先保存修改，再提交审核。
        </p></template
      >
      <div v-else class="notification-body">
        <strong>{{ selected.title }}</strong>
        <p class="pre-wrap">{{ selected.body }}</p>
      </div>
      <div class="actions">
        <template v-if="selected.status === 'pending_review'"
          ><ElButton
            :disabled="busy || !canReview"
            @click="openReview('returned')"
          >
            <Icon name="imgVectorUndo2" />退回修改</ElButton
          ><ElButton
            type="primary"
            class="primary"
            :disabled="busy || !canReview"
            @click="openReview('approved')"
          >
            <Icon name="imgVectorCheck" />审核通过
          </ElButton></template
        ><ElButton
          type="primary"
          v-if="selected.status === 'approved_pending_send'"
          class="primary"
          :disabled="busy || !canWrite"
          @click="
            mutate(
              'dispatch',
              { channel: 'in_app' },
              'POST',
              '站内消息已发布，投递记录已保存',
            )
          "
        >
          发布站内通知</ElButton
        ><RouterLink
          class="button"
          :to="`/milestones?project=${selected.project_id}`"
          ><Icon name="imgVectorFileText" />查看节点依据</RouterLink
        >
      </div>
      <p class="muted">
        已批准规则触发后自动投递站内收件箱，无需逐条审核或发布。外部邮件、短信和企业消息渠道未启用；对外正式函件仍需审批。计划变更会作废未发送旧稿，已发布历史保留。
      </p>
      <details>
        <summary>生成与投递记录</summary>
        <p>生成方式：确定性模板，不是AI输出</p>
        <p v-for="(r, i) in selected.reviews" :key="i">
          第{{ r.draft_version }}版 · {{ label(r.decision) }} ·
          {{ r.comment }} · {{ r.reviewed_at }}
        </p>
        <p v-for="(d, i) in selected.deliveries" :key="i">
          站内投递：{{ d.attempt_state }} · {{ d.finished_at }}
        </p>
      </details>
    </section>
    <section v-else class="card empty">
      请选择一条通知查看依据与投递记录。
    </section>
  </div>
  <section v-if="tab === 'tasks'" class="card table-card">
    <div class="section-title">
      <h3>标准动作执行任务</h3>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>执行人</th>
            <th>截止日期</th>
            <th>执行状态</th>
            <th>来源复核</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks.items" :key="t.id">
            <td>{{ t.title }}</td>
            <td>
              {{
                catalog.users.find((u) => u.id === t.assignee_id)
                  ?.display_name || "未分派"
              }}
            </td>
            <td>{{ t.due_date }}</td>
            <td>
              <span class="badge" :class="t.status">{{ label(t.status) }}</span>
            </td>
            <td>{{ t.requires_review ? t.review_reason : "—" }}</td>
            <td><ElButton @click="showTask = t">处理任务</ElButton></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!tasks.items.length && !busy" class="empty">
      暂无符合条件的任务。
    </p>
    <ElPagination
      class="work-pagination"
      :current-page="tasks.page"
      :page-size="20"
      :total="tasks.total"
      :disabled="busy"
      layout="prev, pager, next"
      prev-text="上一页"
      next-text="下一页"
      :pager-count="5"
      @current-change="load"
    />
  </section>
  <section v-if="tab === 'inbox'" class="card workflow-detail">
    <h3>我的站内消息</h3>
    <p v-if="!inbox.length && !busy" class="empty">
      暂无消息。已批准规则触发后，站内提醒会自动出现在这里。
    </p>
    <section v-for="m in inbox" :key="m.id" class="form-section">
      <div class="section-title">
        <h3>{{ m.title }}</h3>
        <ElButton v-if="!m.read_at" @click="read(m)">标记已读</ElButton
        ><span v-else class="muted">已读</span>
      </div>
      <p class="pre-wrap">{{ m.body }}</p>
      <small>{{ m.created_at }}</small>
    </section>
  </section>
  <section v-if="tab === 'scan'" class="card workflow-detail">
    <h3>提醒扫描预览与生成</h3>
    <p class="notice">
      后台按已批准规则自动发送站内提醒并生成待办。此处可预览或补充扫描，确认后立即投递，无需逐条审核或发布。自动扫描进程使用当前业务日期；开发/测试环境可选模拟日期，正式环境只能生成当天结果。
    </p>
    <ElForm
      ref="scanForm"
      :model="scan"
      class="form-grid work-scan-form"
      label-position="top"
      @submit.prevent="run(false)"
    >
      <ElFormItem
        label="扫描项目"
        prop="project"
        :rules="[
          { required: true, message: '请选择扫描项目', trigger: 'change' },
        ]"
      >
        <ElSelect
          v-model="scan.project"
          aria-label="扫描项目 *"
          filterable
          :disabled="busy"
          placeholder="请选择项目"
          popper-class="project-element-popper"
          @change="scan.previewed = false"
        >
          <ElOption
            v-for="p in projects"
            :key="p.id"
            :value="p.id"
            :label="`${p.project_code} · ${p.project_name}`"
          />
        </ElSelect>
      </ElFormItem>
      <ElFormItem
        label="统计 / 扫描日期"
        prop="as_of"
        :rules="[
          {
            required: true,
            message: '请选择有效扫描日期',
            trigger: 'change',
          },
        ]"
      >
        <ElDatePicker
          v-model="scan.as_of"
          aria-label="统计 / 扫描日期 *"
          type="date"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          :clearable="false"
          :disabled="busy"
          popper-class="project-element-popper"
          @change="scan.previewed = false"
        />
      </ElFormItem>
      <div class="actions">
        <ElButton native-type="submit" :loading="busy">预览提醒计算</ElButton
        ><ElButton
          type="primary"
          native-type="button"
          class="primary"
          :disabled="busy || !scan.previewed || !auth.user?.is_system_admin"
          @click="run(true)"
        >
          确认发送提醒并生成待办
        </ElButton>
      </div>
    </ElForm>
    <p v-if="scan.generated !== null" class="success" role="status">
      本次已发送{{ scan.generated }}条站内提醒，并生成待办；重复项已跳过。
    </p>
    <div v-if="scan.previewed" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>节点</th>
            <th>计划日期</th>
            <th>触发日期</th>
            <th>判断结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in scan.result" :key="i">
            <td>{{ r.milestone_code }} {{ r.milestone_name }}</td>
            <td>{{ r.planned_date || "—" }}</td>
            <td>{{ r.trigger_date || "—" }}</td>
            <td>
              {{
                r.eligible ? "可生成" : label(r.skipped_reason || "不可生成")
              }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
  <TaskDrawer
    v-if="showTask"
    :task="showTask"
    @close="showTask = undefined"
    @changed="load(tasks.page)"
  />
  <Modal
    v-if="reviewAction && selected"
    :before-close="reviewGuard.confirmDiscard"
    title="通知审核确认"
    :busy="busy"
    @close="reviewAction = ''"
  >
    <section class="form-section">
      <h3>{{ selected.title }}</h3>
      <p>
        计划{{ selected.fact_snapshot_json.planned_date }} · 接收人{{
          selected.fact_snapshot_json.recipient_name
        }}
        · 内容第{{ selected.draft_version }}版
      </p>
    </section>
    <p class="notice">
      审核通过仅代表通知内容经过审批。不代表消息已发送、被接收或节点完成。
    </p>
    <form id="notice-review" @submit.prevent="review">
      <label class="checkbox-line"
        ><input
          v-model="confirmed"
          type="checkbox"
          required
        />已核对项目节点、通知内容、接收人与来源</label
      ><label
        >审核意见 *<textarea
          v-model="reviewComment"
          required
          maxlength="500"
          :rows="3"
        />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
    <template #footer="{ close }"
      ><ElButton :disabled="busy" @click="close">返回修改</ElButton
      ><ElButton
        type="primary"
        class="primary"
        form="notice-review"
        native-type="submit"
        :disabled="busy || !confirmed"
      >
        {{ reviewAction === "approved" ? "确认审核通过" : "确认退回修改" }}
      </ElButton></template
    >
  </Modal>
</template>

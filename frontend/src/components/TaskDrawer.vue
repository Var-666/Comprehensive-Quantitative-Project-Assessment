<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useAuth, useCatalog } from "../store";
import type { TaskRecord } from "../workflowTypes";
import { label } from "../workflowTypes";
import Modal from "./Modal.vue";
const props = defineProps<{ task: TaskRecord }>();
const emit = defineEmits<{ close: []; changed: [] }>();
const auth = useAuth(),
  catalog = useCatalog(),
  detail = ref(props.task),
  tab = ref("details"),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  assignee = ref(props.task.assignee_id || ""),
  comment = ref(""),
  evidence = ref(""),
  claimed = ref(false),
  review = ref(""),
  audit = ref<{ action: string; actor_id: string; occurred_at: string }[]>([]);
const executor = computed(
  () => detail.value.assignee_id === auth.user?.user_id,
);
async function load() {
  detail.value = await api<TaskRecord>(`/tasks/${props.task.id}`);
  audit.value = await api<typeof audit.value>(
    `/tasks/${props.task.id}/audit-events`,
  );
}
async function perform(action: () => Promise<unknown>, message: string) {
  busy.value = true;
  error.value = "";
  try {
    await action();
    await load();
    success.value = message;
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function update(status?: string) {
  await perform(
    () =>
      api(`/tasks/${detail.value.id}`, {
        method: "PATCH",
        headers: versionHeader(detail.value.row_version),
        body: json(
          status
            ? { status, reason: comment.value || "执行人更新任务状态" }
            : {
                assignee_id: assignee.value,
                reason: comment.value || "项目编辑明确工作责任人",
              },
        ),
      }),
    "任务更新已保存",
  );
}
async function feedback() {
  await perform(
    () =>
      api(`/tasks/${detail.value.id}/feedback`, {
        method: "POST",
        headers: versionHeader(detail.value.row_version),
        body: json({
          comment: comment.value,
          claimed_completion: claimed.value,
          evidence_ref: evidence.value,
        }),
      }),
    "执行反馈已提交，仍需独立核实；节点完成事实未改变",
  );
}
async function verify(id: string, decision: string) {
  if (!review.value.trim()) {
    error.value = "请填写核实意见";
    return;
  }
  await perform(
    () =>
      api(`/task-feedback/${id}/verify`, {
        method: "POST",
        body: json({ decision, comment: review.value }),
      }),
    "核实结果已留痕；不等同节点完成",
  );
}
onMounted(async () => {
  try {
    await catalog.load();
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  }
});
</script>
<template>
  <Modal title="任务执行反馈" drawer :busy="busy" @close="emit('close')">
    <p class="muted">{{ detail.title }} · 截止{{ detail.due_date }}</p>
    <div class="tabs">
      <button :class="{ primary: tab === 'details' }" @click="tab = 'details'">
        任务详情</button
      ><button
        :class="{ primary: tab === 'feedback' }"
        @click="tab = 'feedback'"
      >
        执行反馈</button
      ><button :class="{ primary: tab === 'audit' }" @click="tab = 'audit'">
        操作记录
      </button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="success" class="success" role="status">{{ success }}</p>
    <p v-if="detail.requires_review" class="notice">
      来源变更需复核：{{
        detail.review_reason
      }}。请由项目编辑取消旧任务，按新计划重新分派；原反馈保留。
    </p>
    <template v-if="tab === 'details'"
      ><section class="form-section">
        <div class="section-title">
          <h3>{{ detail.title }}</h3>
          <span class="badge" :class="detail.status">{{
            label(detail.status)
          }}</span>
        </div>
        <p>核实依据：{{ detail.action_snapshot_json.completion_criteria }}</p>
        <p>
          所需材料：{{
            detail.action_snapshot_json.materials_required_json.join("、") ||
            "无单独材料要求"
          }}
        </p>
        <p>
          执行人：{{
            catalog.users.find((u) => u.id === detail.assignee_id)
              ?.display_name || "尚未分派"
          }}
        </p>
      </section>
      <form
        v-if="
          auth.can(detail.project_id) &&
          !['verified_done', 'cancelled', 'submitted'].includes(detail.status)
        "
        class="form-section"
        @submit.prevent="update()"
      >
        <label
          >分派执行人 *<select v-model="assignee" required>
            <option value="">请选择具有项目编辑权限的账号</option>
            <option v-for="u in catalog.users" :key="u.id" :value="u.id">
              {{ u.display_name }}
            </option>
          </select></label
        >
        <p class="muted">
          后端验证项目编辑权限及可用账号，只读角色不能执行任务。
        </p>
        <button :disabled="busy || detail.requires_review" class="primary">
          保存任务分派</button
        ><button type="button" :disabled="busy" @click="update('cancelled')">
          取消旧任务
        </button>
      </form>
      <button
        v-if="executor && ['todo', 'returned'].includes(detail.status)"
        :disabled="busy || detail.requires_review"
        @click="update('in_progress')"
      >
        开始处理
      </button></template
    >
    <button
      v-if="
        detail.requires_review &&
        detail.status === 'submitted' &&
        auth.can(detail.project_id)
      "
      :disabled="busy"
      @click="update('cancelled')"
    >
      取消需复核的旧任务
    </button>
    <template v-if="tab === 'feedback'"
      ><form
        v-if="
          executor &&
          ['todo', 'in_progress', 'returned'].includes(detail.status) &&
          !detail.requires_review
        "
        class="form-section"
        @submit.prevent="feedback"
      >
        <label
          >处理情况与执行结果 *<textarea
            v-model="comment"
            rows="5"
            required
            maxlength="4000"
          /></label
        ><label
          >来源 / 证据说明 *<textarea
            v-model="evidence"
            required
            maxlength="500"
            rows="2"
          /></label
        ><label class="checkbox-line"
          ><input
            v-model="claimed"
            type="checkbox"
          />声称此项准备动作已完成（仍需独立核实）</label
        >
        <p class="notice">
          提交反馈 ≠ 确认节点完成。当前只保存证据引用，不冒充已上传正式附件。
        </p>
        <button class="primary" :disabled="busy">提交执行反馈</button>
      </form>
      <p v-if="!detail.feedback.length" class="empty">尚无执行反馈。</p>
      <section v-for="f in detail.feedback" :key="f.id" class="form-section">
        <div class="section-title">
          <strong>{{ label(f.status) }}</strong
          ><small>{{ f.submitted_at.slice(0, 19) }}</small>
        </div>
        <p class="pre-wrap">{{ f.comment }}</p>
        <p class="muted">
          证据：{{ f.evidence_ref }} · 声称完成：{{
            f.claimed_completion ? "是" : "否"
          }}
        </p>
        <p v-if="f.verification">
          核实：{{ label(f.verification.decision) }} ·
          {{ f.verification.comment }}
        </p>
        <template
          v-if="
            f.status === 'submitted' &&
            auth.can(detail.project_id, 'review') &&
            f.submitted_by !== auth.user?.user_id &&
            !detail.requires_review
          "
          ><label
            >核实意见 *<textarea v-model="review" required maxlength="500" />
          </label>
          <div class="actions">
            <button
              class="primary"
              :disabled="busy"
              @click="verify(f.id, 'accepted')"
            >
              核实接受</button
            ><button :disabled="busy" @click="verify(f.id, 'returned')">
              退回反馈</button
            ><button :disabled="busy" @click="verify(f.id, 'disputed')">
              标记异议
            </button>
          </div></template
        >
      </section></template
    >
    <template v-if="tab === 'audit'"
      ><section v-for="(e, i) in audit" :key="i" class="form-section">
        <strong>{{ e.action }}</strong>
        <p class="muted">
          {{ e.occurred_at }} · 操作人{{
            catalog.users.find((u) => u.id === e.actor_id)?.display_name ||
            e.actor_id
          }}
        </p>
      </section>
      <p v-if="!audit.length" class="empty">尚无操作记录。</p></template
    >
    <template #footer
      ><button :disabled="busy" @click="emit('close')">关闭</button></template
    >
  </Modal>
</template>

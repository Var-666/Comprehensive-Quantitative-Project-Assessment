<script setup lang="ts">
import { useUnsavedChanges } from "../useUnsavedChanges";
import OperationToast from "./OperationToast.vue";
import { ElButton } from "element-plus/es/components/button/index";
import FormSelect from "./FormSelect.vue";
import FormDate from "./FormDate.vue";
import { ElOption } from "element-plus/es/components/select/index";
import { ElInput } from "element-plus/es/components/input/index";
import { ElCheckbox } from "element-plus/es/components/checkbox/index";
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
const showCompletion = ref(false),
  actualDate = ref(""),
  nodeConfirmed = ref(false);
const completionGuard = useUnsavedChanges(
  () => ({ actualDate: actualDate.value, nodeConfirmed: nodeConfirmed.value }),
  () => showCompletion.value,
  () => busy.value,
);
const executor = computed(
  () => detail.value.assignee_id === auth.user?.user_id,
);
const guard = useUnsavedChanges(
  () => ({
    assignee: assignee.value,
    comment: comment.value,
    evidence: evidence.value,
    claimed: claimed.value,
    review: review.value,
  }),
  () => true,
  () => busy.value,
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
  if (!error.value)
    guard.markSaved(status ? ["comment"] : ["assignee", "comment"]);
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
  if (!error.value) guard.markSaved(["comment", "evidence", "claimed"]);
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
    "核实结果已留痕",
  );
  if (!error.value) {
    guard.markSaved(["review"]);
    if (detail.value.milestone_completion?.can_confirm) openCompletion();
  }
}
function openCompletion() {
  actualDate.value = "";
  nodeConfirmed.value = false;
  showCompletion.value = true;
}
async function completeMilestone() {
  const state = detail.value.milestone_completion;
  if (!state?.can_confirm || !actualDate.value || !nodeConfirmed.value) return;
  await perform(
    () =>
      api(`/tasks/${detail.value.id}/complete-milestone`, {
        method: "POST",
        headers: versionHeader(state.row_version),
        body: json({
          actual_date: actualDate.value,
          confirmed: nodeConfirmed.value,
        }),
      }),
    "节点已核销，沿用已核实任务凭证，无需再次提交审核",
  );
  if (!error.value) {
    completionGuard.markSaved();
    showCompletion.value = false;
  }
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
  <Modal
    :before-close="guard.confirmDiscard"
    class="task-drawer"
    title="任务执行反馈"
    :subtitle="task.title"
    drawer
    :busy="busy"
    @close="emit('close')"
  >
    <template #navigation>
      <div class="drawer-tabs">
        <ElButton
          :class="{ primary: tab === 'details' }"
          @click="tab = 'details'"
          native-type="submit"
          :type="tab === 'details' ? 'primary' : 'default'"
        >
          任务详情</ElButton
        ><ElButton
          :class="{ primary: tab === 'feedback' }"
          @click="tab = 'feedback'"
          native-type="submit"
          :type="
            { primary: tab === 'feedback' }.primary ? 'primary' : 'default'
          "
        >
          执行反馈</ElButton
        ><ElButton
          :class="{ primary: tab === 'audit' }"
          @click="tab = 'audit'"
          native-type="submit"
          :type="tab === 'audit' ? 'primary' : 'default'"
        >
          操作记录
        </ElButton>
      </div>
    </template>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <OperationToast v-model="success" :busy="busy" />
    <section v-if="detail.milestone_completion" class="notice" role="status">
      <strong>{{ detail.milestone_completion.milestone_name }}</strong>
      <p>
        标准动作已核实 {{ detail.milestone_completion.completed_tasks }} /
        {{ detail.milestone_completion.total_tasks }} 项
      </p>
      <p v-if="detail.milestone_completion.actual_date">
        节点已核销，实际完成日期：{{ detail.milestone_completion.actual_date }}
      </p>
      <template v-else-if="detail.milestone_completion.ready">
        <p>所有前置动作已达标，可沿用任务凭证确认节点实际完成。</p>
        <ElButton
          v-if="detail.milestone_completion.can_confirm"
          type="primary"
          :disabled="busy"
          @click="openCompletion"
          >一键核销节点</ElButton
        >
        <p v-else>
          请由未参与任务反馈提交的项目审核人确认节点实际完成，无需重复录入凭证。
        </p>
      </template>
      <p v-else>{{ detail.milestone_completion.reason }}</p>
    </section>
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
          >分派执行人 *<FormSelect
            v-model="assignee"
            required
            :aria-label="'分派执行人 *'"
          >
            <ElOption
              data-ui-value=""
              value=""
              :label="'请选择具有项目编辑权限的账号'"
            />
            <ElOption
              :data-ui-value="u.id"
              v-for="u in catalog.users"
              :key="u.id"
              :value="u.id"
              :label="String(u.display_name)"
            /> </FormSelect
        ></label>
        <p class="muted">
          后端验证项目编辑权限及可用账号，只读角色不能执行任务。
        </p>
        <ElButton
          :disabled="busy || detail.requires_review"
          class="primary"
          native-type="submit"
          type="primary"
        >
          保存任务分派</ElButton
        ><ElButton
          :disabled="busy"
          @click="update('cancelled')"
          native-type="button"
        >
          取消旧任务
        </ElButton>
      </form>
      <ElButton
        v-if="executor && ['todo', 'returned'].includes(detail.status)"
        :disabled="busy || detail.requires_review"
        @click="update('in_progress')"
        native-type="submit"
      >
        开始处理
      </ElButton></template
    >
    <ElButton
      v-if="
        detail.requires_review &&
        detail.status === 'submitted' &&
        auth.can(detail.project_id)
      "
      :disabled="busy"
      @click="update('cancelled')"
      native-type="submit"
    >
      取消需复核的旧任务
    </ElButton>
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
          >处理情况与执行结果 *<ElInput
            v-model="comment"
            :rows="5"
            required
            maxlength="4000"
            type="textarea"
            :aria-label="'处理情况与执行结果 *'" /></label
        ><label
          >来源 / 证据说明 *<ElInput
            v-model="evidence"
            required
            maxlength="500"
            :rows="2"
            type="textarea"
            :aria-label="'来源 / 证据说明 *'" /></label
        ><ElCheckbox class="checkbox-line" v-model="claimed"
          >声称此项准备动作已完成（仍需独立核实）</ElCheckbox
        >
        <p class="notice">
          提交反馈 ≠ 确认节点完成。当前只保存证据引用，不冒充已上传正式附件。
        </p>
        <ElButton
          class="primary"
          :disabled="busy"
          native-type="submit"
          type="primary"
          >提交执行反馈</ElButton
        >
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
            >核实意见 *<ElInput
              v-model="review"
              required
              maxlength="500"
              type="textarea"
              :aria-label="'核实意见 *'"
            />
          </label>
          <div class="actions">
            <ElButton
              class="primary"
              :disabled="busy"
              @click="verify(f.id, 'accepted')"
              native-type="submit"
              type="primary"
            >
              核实接受</ElButton
            ><ElButton
              :disabled="busy"
              @click="verify(f.id, 'returned')"
              native-type="submit"
            >
              退回反馈</ElButton
            ><ElButton
              :disabled="busy"
              @click="verify(f.id, 'disputed')"
              native-type="submit"
            >
              标记异议
            </ElButton>
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
    <template #footer="{ close }"
      ><ElButton :disabled="busy" @click="close" native-type="submit"
        >关闭</ElButton
      ></template
    >
  </Modal>
  <Modal
    v-if="showCompletion"
    title="确认节点实际完成"
    :busy="busy"
    :before-close="completionGuard.confirmDiscard"
    @close="showCompletion = false"
  >
    <p class="notice">
      全部标准动作已核实。系统将沿用已有任务凭证，确认后直接核销节点，无需再次申请或审核。备好发票不代表款项到账，请确认节点本身确已完成。
    </p>
    <form id="complete-milestone" @submit.prevent="completeMilestone">
      <label
        >节点实际完成日期 *<FormDate
          v-model="actualDate"
          required
          :disabled="busy"
          aria-label="节点实际完成日期 *"
      /></label>
      <ElCheckbox v-model="nodeConfirmed" :disabled="busy"
        >我已确认节点本身实际完成，沿用已核实的任务凭证核销</ElCheckbox
      >
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
    <template #footer="{ close }">
      <ElButton :disabled="busy" @click="close">暂不核销</ElButton>
      <ElButton
        type="primary"
        native-type="submit"
        form="complete-milestone"
        :disabled="busy || !actualDate || !nodeConfirmed"
        >确认核销节点</ElButton
      >
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import type { Milestone } from "../types";
import Modal from "./Modal.vue";
import StatusBadge from "./StatusBadge.vue";
import { useAuth } from "../store";
import NodeActions from "./NodeActions.vue";
const auth = useAuth();
const props = defineProps<{ node: Milestone; planId: string }>();
const emit = defineEmits<{ close: []; changed: [] }>();
const detail = ref<Milestone>(props.node),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  comment = ref("");
const cancelReason = ref("");
async function cancelNode() {
  busy.value = true;
  error.value = "";
  try {
    await api(`/milestones/${props.node.id}/cancel`, {
      method: "POST",
      headers: versionHeader(detail.value.row_version),
      body: json({ reason: cancelReason.value }),
    });
    await load();
    success.value = "节点已取消，旧待发提醒已失效，历史保留";
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
const form = reactive({
  completion_flag: "unknown",
  actual_date: "",
  evidence_ref: "",
});
async function load() {
  try {
    detail.value = await api<Milestone>(
      `/milestones/${props.node.id}?plan_version_id=${props.planId}`,
    );
  } catch (e) {
    error.value = errorMessage(e);
  }
}
async function submit() {
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await api(`/milestones/${props.node.id}/actuals`, {
      method: "POST",
      body: json({
        completion_flag:
          form.completion_flag === "unknown"
            ? null
            : form.completion_flag === "true",
        actual_date: form.completion_flag === "true" ? form.actual_date : null,
        evidence_ref: form.evidence_ref,
      }),
    });
    success.value = "实际记录已提交，仍需独立核实";
    form.evidence_ref = "";
    await load();
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function verify(id: string, decision: string) {
  if (!comment.value.trim()) {
    error.value = "请填写核实意见";
    return;
  }
  busy.value = true;
  error.value = "";
  success.value = "";
  try {
    await api(`/milestone-actuals/${id}/verify`, {
      method: "POST",
      body: json({ decision, comment: comment.value }),
    });
    success.value = "核实结果已记录";
    comment.value = "";
    await load();
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
  <Modal
    :title="`${detail.milestone_code} · 节点详情`"
    drawer
    :busy="busy"
    @close="emit('close')"
  >
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="success" class="success" role="status">{{ success }}</p>
    <section class="form-section">
      <h3>
        {{ detail.milestone_name }}
        <StatusBadge :value="detail.verification_status" />
      </h3>
      <dl class="details">
        <div>
          <dt>计划日期</dt>
          <dd>{{ detail.plan_item.planned_date }}</dd>
        </div>
        <div>
          <dt>当前已核实实际日期</dt>
          <dd>
            {{ detail.current_actual?.actual_date || "未知 / 尚未确认完成" }}
          </dd>
        </div>
        <div>
          <dt>责任部门</dt>
          <dd>{{ detail.department_name || "未指定" }}</dd>
        </div>
        <div>
          <dt>日期依据</dt>
          <dd>{{ detail.plan_item.source_ref || "未录入" }}</dd>
        </div>
      </dl>
    </section>
    <NodeActions :key="detail.plan_item.id" :node="detail" />
    <section v-if="auth.can(detail.project_id)" class="form-section">
      <details v-if="detail.lifecycle_status === 'active'">
        <summary>取消节点</summary>
        <p class="notice">
          取消后不再产生新提醒。未发送旧稿会失效，已发送和执行记录保留。
        </p>
        <form @submit.prevent="cancelNode">
          <label
            >业务取消原因 *<textarea
              v-model="cancelReason"
              required
              maxlength="500"
            /></label
          ><button :disabled="busy">确认取消节点</button>
        </form>
      </details>
      <p v-else class="notice">节点已取消，保留历史计划及事实记录。</p>
    </section>
    <section v-if="auth.can(detail.project_id)" class="form-section">
      <h3>提交实际记录</h3>
      <form @submit.prevent="submit">
        <div class="form-grid">
          <label
            >完成事实<select
              v-model="form.completion_flag"
              aria-label="完成事实"
            >
              <option value="unknown">未知 / 待核对</option>
              <option value="true">已完成（待核实）</option>
              <option value="false">尚未完成（待核实）</option>
            </select></label
          ><label
            >实际完成日期<input
              v-model="form.actual_date"
              type="date"
              :disabled="form.completion_flag !== 'true'"
              :required="form.completion_flag === 'true'"
          /></label>
        </div>
        <label
          >来源 / 证据说明 *<textarea
            v-model="form.evidence_ref"
            required
            maxlength="500"
            rows="2"
          />
        </label>
        <p class="muted">
          来源说明不等于正式证据附件。提交不改变已核实事实，也不代表节点已完成。
        </p>
        <button class="primary" :disabled="busy">提交实际记录</button>
      </form>
    </section>
    <section class="form-section">
      <h3>实际记录与独立核实</h3>
      <p class="notice warning">
        仅本项目审核人员可以核实；提交人不能核实自己的记录。
      </p>
      <label>核实意见<input v-model="comment" maxlength="2000" /></label>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>提交时间</th>
              <th>完成事实</th>
              <th>实际日期</th>
              <th>核实状态</th>
              <th>来源</th>
              <th>审核操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in detail.actual_records" :key="a.id">
              <td>{{ a.submitted_at }}</td>
              <td>
                {{
                  a.completion_flag === true
                    ? "已完成"
                    : a.completion_flag === false
                      ? "尚未完成"
                      : "未知"
                }}<small v-if="a.is_current" class="subline"
                  >当前核实事实</small
                >
              </td>
              <td>{{ a.actual_date || "—" }}</td>
              <td><StatusBadge :value="a.verification_status" /></td>
              <td>
                {{ a.evidence_ref
                }}<small v-if="a.comment" class="subline">{{
                  a.comment
                }}</small>
              </td>
              <td>
                <div
                  v-if="
                    a.verification_status === 'submitted' &&
                    auth.can(detail.project_id, 'review') &&
                    a.submitted_by !== auth.user?.user_id
                  "
                  class="actions"
                >
                  <button :disabled="busy" @click="verify(a.id, 'verified')">
                    确认核实</button
                  ><button :disabled="busy" @click="verify(a.id, 'returned')">
                    退回</button
                  ><button :disabled="busy" @click="verify(a.id, 'disputed')">
                    争议
                  </button>
                </div>
                <span v-else>已处理</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!detail.actual_records.length" class="empty">尚无实际记录</p>
    </section>
    <section class="form-section">
      <h3>计划历史快照</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>快照</th>
              <th>计划日期</th>
              <th>节点名称</th>
              <th>变更原因</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in detail.history" :key="p.id">
              <td>{{ p.plan_version_id }}</td>
              <td>{{ p.planned_date }}</td>
              <td>{{ p.milestone_name }}</td>
              <td>{{ p.change_reason }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section class="form-section">
      <h3>变更留痕</h3>
      <details v-for="e in detail.audit_events" :key="e.id">
        <summary>
          {{ e.occurred_at }} · {{ e.action }} · {{ e.actor_id }}
        </summary>
        <pre>{{
          JSON.stringify(
            { before: e.before_json, after: e.after_json },
            null,
            2,
          )
        }}</pre>
      </details>
    </section>
    <template #footer
      ><button :disabled="busy" @click="emit('close')">关闭</button></template
    >
  </Modal>
</template>

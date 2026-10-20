<script setup lang="ts">
import { computed, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useAuth } from "../store";
import type { ConfigRecord } from "../workflowTypes";
import Modal from "./Modal.vue";
import Icon from "./Icon.vue";
const props = defineProps<{ item: ConfigRecord; path: string }>();
const emit = defineEmits<{ changed: [] }>();
const auth = useAuth(),
  busy = ref(false),
  error = ref(""),
  action = ref(""),
  basis = ref("");
const canReview = computed(
  () =>
    auth.user?.memberships.some((m) =>
      ["admin", "reviewer"].includes(m.role_code),
    ) && !props.item.editor_ids.includes(auth.user?.user_id || ""),
);
async function perform(kind: string) {
  busy.value = true;
  error.value = "";
  try {
    await api(`/${props.path}/${props.item.id}/${kind}`, {
      method: "POST",
      headers: versionHeader(props.item.row_version),
      ...(kind === "submit-review"
        ? {}
        : {
            body: json({
              decision: action.value === "returned" ? "returned" : "approved",
              approval_ref: basis.value,
            }),
          }),
    });
    action.value = "";
    emit("changed");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <div class="actions">
    <button
      v-if="item.status === 'draft' && auth.user?.is_system_admin"
      :disabled="busy"
      class="primary"
      @click="perform('submit-review')"
    >
      <Icon name="imgVectorSend" />提交业务确认
    </button>
    <template v-if="item.status === 'pending_review'">
      <button
        :disabled="busy || !canReview"
        class="primary"
        @click="
          action = 'approved';
          basis = '';
        "
      >
        独立批准
      </button>
      <button
        :disabled="busy || !canReview"
        @click="
          action = 'returned';
          basis = '';
        "
      >
        退回配置
      </button>
    </template>
    <button
      v-if="item.status === 'approved' && auth.user?.is_system_admin"
      :disabled="busy"
      @click="
        action = 'retire';
        basis = '';
      "
    >
      停用此版本
    </button>
  </div>
  <p v-if="item.approval_ref" class="muted">
    最近审核依据：{{ item.approval_ref }}
  </p>
  <Modal
    v-if="action"
    :title="action === 'retire' ? '停用配置' : '配置业务确认'"
    :busy="busy"
    @close="action = ''"
  >
    <p class="notice">
      批准后才会参与正式匹配和日期计算。请核对配置来源、适用范围和版本；已批准内容不可覆盖修改。
    </p>
    <form
      id="config-approval"
      @submit.prevent="perform(action === 'retire' ? 'retire' : 'review')"
    >
      <label
        >批准依据 / 退回或停用原因 *<textarea
          v-model="basis"
          required
          maxlength="500"
          rows="4"
        />
      </label>
    </form>
    <template #footer
      ><button :disabled="busy" @click="action = ''">取消</button
      ><button
        class="primary"
        type="submit"
        form="config-approval"
        :disabled="busy"
      >
        确认{{
          action === "retire" ? "停用" : action === "returned" ? "退回" : "批准"
        }}
      </button></template
    >
  </Modal>
</template>

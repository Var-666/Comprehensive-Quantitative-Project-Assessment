<script setup lang="ts">
import { ElButton } from "element-plus/es/components/button/index";
import { ElInput } from "element-plus/es/components/input/index";
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
    <ElButton
      v-if="item.status === 'draft' && auth.user?.is_system_admin"
      :disabled="busy"
      class="primary"
      @click="perform('submit-review')"
      native-type="submit"
      type="primary"
    >
      <Icon name="imgVectorSend" />提交业务确认
    </ElButton>
    <template v-if="item.status === 'pending_review'">
      <ElButton
        :disabled="busy || !canReview"
        class="primary"
        @click="
          action = 'approved';
          basis = '';
        "
        native-type="submit"
        type="primary"
      >
        独立批准
      </ElButton>
      <ElButton
        :disabled="busy || !canReview"
        @click="
          action = 'returned';
          basis = '';
        "
        native-type="submit"
      >
        退回配置
      </ElButton>
    </template>
    <ElButton
      v-if="item.status === 'approved' && auth.user?.is_system_admin"
      :disabled="busy"
      @click="
        action = 'retire';
        basis = '';
      "
      native-type="submit"
    >
      停用此版本
    </ElButton>
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
        >批准依据 / 退回或停用原因 *<ElInput
          v-model="basis"
          required
          maxlength="500"
          :rows="4"
          type="textarea"
          :aria-label="'批准依据 / 退回或停用原因 *'"
        />
      </label>
    </form>
    <template #footer
      ><ElButton :disabled="busy" @click="action = ''" native-type="submit"
        >取消</ElButton
      ><ElButton
        class="primary"
        form="config-approval"
        :disabled="busy"
        native-type="submit"
        type="primary"
      >
        确认{{
          action === "retire" ? "停用" : action === "returned" ? "退回" : "批准"
        }}
      </ElButton></template
    >
  </Modal>
</template>

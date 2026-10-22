<script setup lang="ts">
import { ElInput } from "element-plus/es/components/input/index";
import { ElButton } from "element-plus/es/components/button/index";
import { ref } from "vue";
import { useAuth } from "../store";
import { errorMessage } from "../api";
const auth = useAuth(),
  username = ref(""),
  password = ref(""),
  busy = ref(false),
  error = ref("");
async function login() {
  busy.value = true;
  error.value = "";
  try {
    await auth.login(username.value, password.value);
    password.value = "";
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="login-shell">
    <form class="card login-card" @submit.prevent="login">
      <img src="/icons/imgBrandMarkMetricMilestones.svg" alt="" />
      <h1>项目智能管控</h1>
      <p class="muted">请使用已配置的账号登录，权限按项目分配。</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <label
        >账号<ElInput
          v-model="username"
          autocomplete="username"
          required
          maxlength="80"
          :aria-label="'账号'" /></label
      ><label
        >密码<ElInput
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          maxlength="200"
          :aria-label="'密码'" /></label
      ><ElButton
        class="primary"
        :disabled="busy"
        native-type="submit"
        type="primary"
      >
        {{ busy ? "登录中…" : "登录" }}
      </ElButton>
      <p class="muted">
        首次使用：由本机运维通过账号配置命令创建账号。系统无默认密码。
      </p>
    </form>
  </main>
</template>

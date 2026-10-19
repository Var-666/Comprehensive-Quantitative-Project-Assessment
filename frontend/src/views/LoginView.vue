<script setup lang="ts">
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
        >账号<input
          v-model="username"
          autocomplete="username"
          required
          maxlength="80" /></label
      ><label
        >密码<input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          maxlength="200" /></label
      ><button class="primary" :disabled="busy">
        {{ busy ? "登录中…" : "登录" }}
      </button>
      <p class="muted">
        首次使用：由本机运维通过账号配置命令创建账号。系统无默认密码。
      </p>
    </form>
  </main>
</template>

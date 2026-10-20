<script setup lang="ts">
import { useRoute } from "vue-router";
import Icon from "./components/Icon.vue";
import { onMounted, onUnmounted } from "vue";
import { useAuth } from "./store";
import LoginView from "./views/LoginView.vue";
const auth = useAuth();
const expired = () => auth.clear();
onMounted(async () => {
  window.addEventListener("session-expired", expired);
  try {
    await auth.load();
  } catch {
    /* Login screen handles unauthenticated access. */
  }
});
onUnmounted(() => window.removeEventListener("session-expired", expired));
const route = useRoute();
const nav = [
  { path: "/", title: "项目总览", icon: "imgIconVector5" },
  { path: "/projects", title: "项目管理", icon: "imgIconVector4" },
  { path: "/milestones", title: "节点管理", icon: "imgIconVector3" },
  { path: "/actions", title: "标准动作", icon: "imgIconVector2" },
  { path: "/tasks", title: "提醒与待办", icon: "imgIconVector1" },
  { path: "/metrics", title: "量化评估", icon: "imgIconVector" },
  { path: "/analysis", title: "AI 智能分析", icon: "imgIconAiVector" },
];
</script>
<template>
  <p v-if="!auth.ready" class="empty" role="status">正在验证登录状态…</p>
  <LoginView v-else-if="!auth.user" />
  <template v-else>
    <aside class="sidebar">
      <RouterLink to="/" class="brand"
        ><img src="/icons/imgBrandMarkMetricMilestones.svg" alt="" />
        <div>
          <strong>项目智能管控</strong><small>PROJECT INTELLIGENCE</small>
        </div></RouterLink
      >
      <nav aria-label="主导航">
        <div class="nav-caption">工作空间</div>
        <RouterLink
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          :class="{
            active:
              item.path === '/'
                ? route.path === '/'
                : route.path.startsWith(item.path),
          }"
          ><Icon :name="item.icon" />{{ item.title }}</RouterLink
        >
        <RouterLink
          v-if="auth.user.is_system_admin"
          to="/settings/llm"
          :class="{ active: route.path.startsWith('/settings') }"
          ><Icon name="settings" />系统设置</RouterLink
        >
      </nav>
      <div class="sidebar-foot">
        <p>第一期 · 项目与执行管理</p>
        <small>{{
          auth.user.demo_mode ? "开发/测试 · 模拟数据" : "业务数据环境"
        }}</small>
      </div>
    </aside>
    <div class="main-shell">
      <header class="header">
        <span>工作台 / {{ route.meta.title }}</span>
        <div class="header-right">
          <span class="demo-label">{{
            auth.user.demo_mode ? "模拟数据" : "已登录"
          }}</span
          ><span class="avatar">项</span
          ><span>{{ auth.user.display_name }}</span
          ><button class="text-button" @click="auth.logout()">退出登录</button>
        </div>
      </header>
      <main><RouterView /></main>
    </div>
  </template>
</template>

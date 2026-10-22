<script setup lang="ts">
import { useRoute } from "vue-router";
import { ElConfigProvider } from "element-plus/es/components/config-provider/index";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import { Expand, Fold } from "@element-plus/icons-vue";
import Icon from "./components/Icon.vue";
import { onMounted, onUnmounted, ref } from "vue";
import { useAuth } from "./store";
import LoginView from "./views/LoginView.vue";
const auth = useAuth();
const sidebarCollapsed = ref(false);
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
  {
    path: "/",
    title: "项目总览",
    icon: "imgIconVector5",
    activeIcon: "nav-overview-active",
  },
  {
    path: "/projects",
    title: "项目管理",
    icon: "nav-projects",
    activeIcon: "imgIconVector4",
  },
  {
    path: "/milestones",
    title: "节点管理",
    icon: "imgIconVector3",
    activeIcon: "nav-milestones-active",
  },
  {
    path: "/actions",
    title: "标准动作",
    icon: "imgIconVector2",
    activeIcon: "nav-actions-active",
  },
  {
    path: "/tasks",
    title: "提醒与待办",
    icon: "imgIconVector1",
    activeIcon: "nav-tasks-active",
  },
  {
    path: "/metrics",
    title: "量化评估",
    icon: "imgIconVector",
    activeIcon: "nav-metrics-active",
  },
  {
    path: "/analysis",
    title: "AI 智能分析",
    icon: "imgIconAiVector",
    activeIcon: "nav-analysis-active",
  },
];
const isActive = (path: string) =>
  path === "/" ? route.path === "/" : route.path.startsWith(path);
</script>
<template>
  <p v-if="!auth.ready" class="empty" role="status">正在验证登录状态…</p>
  <LoginView v-else-if="!auth.user" />
  <template v-else>
    <aside class="sidebar" :class="{ 'is-collapsed': sidebarCollapsed }">
      <RouterLink
        to="/"
        class="brand"
        aria-label="项目智能管控"
        title="项目智能管控"
        ><img src="/icons/imgBrandMarkMetricMilestones.svg" alt="" />
        <div class="brand-copy">
          <strong>项目智能管控</strong><small>PROJECT INTELLIGENCE</small>
        </div></RouterLink
      >
      <nav id="workspace-navigation" aria-label="主导航">
        <div class="nav-caption">工作空间</div>
        <RouterLink
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          :class="{ active: isActive(item.path) }"
          :aria-label="item.title"
          :title="sidebarCollapsed ? item.title : undefined"
          ><Icon
            :name="isActive(item.path) ? item.activeIcon : item.icon"
          /><span class="nav-label">{{ item.title }}</span></RouterLink
        >
        <RouterLink
          v-if="auth.user.is_system_admin"
          to="/settings/llm"
          class="sidebar-settings"
          :class="{ active: route.path.startsWith('/settings') }"
          aria-label="系统设置"
          :title="sidebarCollapsed ? '系统设置' : undefined"
          ><Icon
            :name="
              route.path.startsWith('/settings') ? 'settings' : 'nav-settings'
            "
          /><span class="nav-label">系统设置</span></RouterLink
        >
      </nav>
    </aside>
    <div class="main-shell" :class="{ 'is-collapsed': sidebarCollapsed }">
      <header class="header">
        <div class="header-location">
          <button
            type="button"
            class="sidebar-toggle"
            aria-controls="workspace-navigation"
            :aria-expanded="!sidebarCollapsed"
            :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <component
              :is="sidebarCollapsed ? Expand : Fold"
              class="icon"
              aria-hidden="true"
            />
          </button>
          <span>工作台 / {{ route.meta.title }}</span>
        </div>
        <div class="header-right">
          <span class="demo-label">{{
            auth.user.demo_mode ? "模拟数据" : "已登录"
          }}</span
          ><span class="avatar">项</span
          ><span>{{ auth.user.display_name }}</span
          ><button class="text-button" @click="auth.logout()">退出登录</button>
        </div>
      </header>
      <main :class="`workspace-${route.path.split('/')[1] || 'overview'}`">
        <ElConfigProvider :locale="zhCn"
          ><RouterView v-slot="{ Component }"
            ><component
              :is="Component"
              :key="
                route.path === '/imports' ? route.fullPath : undefined
              " /></RouterView
        ></ElConfigProvider>
      </main>
    </div>
  </template>
</template>

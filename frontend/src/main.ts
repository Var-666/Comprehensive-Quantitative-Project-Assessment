import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import "element-plus/es/components/base/style/css";
import "element-plus/es/components/button/style/css";
import "element-plus/es/components/checkbox/style/css";
import "element-plus/es/components/date-picker/style/css";
import "element-plus/es/components/dialog/style/css";
import "element-plus/es/components/drawer/style/css";
import "element-plus/es/components/form/style/css";
import "element-plus/es/components/input/style/css";
import "element-plus/es/components/pagination/style/css";
import "element-plus/es/components/select/style/css";
import "element-plus/es/components/tag/style/css";
import "element-plus/es/components/upload/style/css";
import "@fontsource-variable/noto-sans-sc";
import "./style.css";
import "./element-plus.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: () => import("./views/OverviewView.vue"),
      meta: { title: "项目总览" },
    },
    {
      path: "/projects",
      component: () => import("./views/ProjectsView.vue"),
      meta: { title: "项目管理" },
    },
    {
      path: "/projects/:id",
      component: () => import("./views/ProjectDetail.vue"),
      meta: { title: "项目管理" },
    },
    {
      path: "/milestones",
      component: () => import("./views/MilestonesView.vue"),
      meta: { title: "节点管理" },
    },
    {
      path: "/actions",
      component: () => import("./views/ActionsView.vue"),
      meta: { title: "标准动作" },
    },
    {
      path: "/tasks",
      component: () => import("./views/WorkflowsView.vue"),
      meta: { title: "提醒与待办" },
    },
    {
      path: "/metrics",
      component: () => import("./views/MetricsView.vue"),
      meta: { title: "量化评估" },
    },
    {
      path: "/analysis",
      component: () => import("./views/AnalysisView.vue"),
      meta: { title: "AI 智能分析" },
    },
    {
      path: "/settings/llm",
      component: () => import("./views/LLMSettingsView.vue"),
      meta: { title: "系统设置" },
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
createApp(App).use(createPinia()).use(router).mount("#app");

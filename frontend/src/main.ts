import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import ProjectsView from "./views/ProjectsView.vue";
import ProjectDetail from "./views/ProjectDetail.vue";
import MilestonesView from "./views/MilestonesView.vue";
import OverviewView from "./views/OverviewView.vue";
import PendingView from "./views/PendingView.vue";
import "./style.css";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: OverviewView, meta: { title: "项目总览" } },
    { path: "/projects", component: ProjectsView, meta: { title: "项目管理" } },
    {
      path: "/projects/:id",
      component: ProjectDetail,
      meta: { title: "项目管理" },
    },
    {
      path: "/milestones",
      component: MilestonesView,
      meta: { title: "节点管理" },
    },
    ...[
      ["actions", "标准动作"],
      ["tasks", "提醒与待办"],
      ["metrics", "量化评估"],
      ["analysis", "AI 智能分析"],
    ].map(([path, title]) => ({
      path: `/${path}`,
      component: PendingView,
      meta: { title },
    })),
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
createApp(App).use(createPinia()).use(router).mount("#app");

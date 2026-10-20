import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import ProjectsView from "./views/ProjectsView.vue";
import ProjectDetail from "./views/ProjectDetail.vue";
import MilestonesView from "./views/MilestonesView.vue";
import OverviewView from "./views/OverviewView.vue";
import MetricsView from "./views/MetricsView.vue";
import AnalysisView from "./views/AnalysisView.vue";
import ActionsView from "./views/ActionsView.vue";
import WorkflowsView from "./views/WorkflowsView.vue";
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
    { path: "/actions", component: ActionsView, meta: { title: "标准动作" } },
    { path: "/tasks", component: WorkflowsView, meta: { title: "提醒与待办" } },
    { path: "/metrics", component: MetricsView, meta: { title: "量化评估" } },
    {
      path: "/analysis",
      component: AnalysisView,
      meta: { title: "AI 智能分析" },
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
createApp(App).use(createPinia()).use(router).mount("#app");

<script setup lang="ts">
import { useRoute } from "vue-router";
const route = useRoute();
</script>
<template>
  <div class="page-title">
    <div>
      <h1>{{ route.meta.title }}</h1>
      <p>第一期 · 分阶段实施</p>
    </div>
  </div>
  <section class="card empty pending">
    <h2>此模块尚未实现</h2>
    <p>计划在第三阶段开发，依赖提醒执行闭环与评价口径确认。</p>
    <p>当前尚未实现量化评分与 AI 分析结果。</p>
    <RouterLink class="button primary" to="/projects">前往项目管理</RouterLink>
  </section>
</template>

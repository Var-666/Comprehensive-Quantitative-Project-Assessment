<script setup lang="ts">
import { ElPagination } from "element-plus/es/components/pagination/index";
defineProps<{
  page: number;
  total: number;
  pageSize: number;
  disabled?: boolean;
}>();
defineEmits<{ change: [page: number] }>();
</script>
<template>
  <div class="pagination ui-pagination">
    <span>第 {{ page }} 页 · 每页 {{ pageSize }} 条 · 共 {{ total }} 条</span>
    <ElPagination
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      :disabled="disabled"
      layout="prev, pager, next"
      prev-text="上一页"
      next-text="下一页"
      @current-change="$emit('change', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { statuses } from "../types";
import { ElTag } from "element-plus/es/components/tag/index";
defineProps<{ value: string }>();
</script>
<template>
  <ElTag class="badge" :class="value" :disable-transitions="true">{{
    statuses[value] || value
  }}</ElTag>
</template>

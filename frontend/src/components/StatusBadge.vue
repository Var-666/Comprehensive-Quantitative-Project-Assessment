<script setup lang="ts">
import { statuses } from "../types";
defineProps<{ value: string }>();
</script>
<template>
  <span class="badge" :class="value">{{ statuses[value] || value }}</span>
</template>

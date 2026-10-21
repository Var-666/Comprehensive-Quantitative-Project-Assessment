<script setup lang="ts">
defineProps<{ category?: string }>();
const assets: Record<string, string> = {
  on_time_completed: "timeline-completed",
  late_completed: "timeline-late",
  pending_verification: "timeline-pending",
  confirmed_overdue_unfinished: "timeline-pending",
};
</script>
<template>
  <img
    class="timeline-dot"
    :src="`/icons/${assets[category || ''] || 'timeline-upcoming'}.svg`"
    alt=""
    aria-hidden="true"
  />
</template>

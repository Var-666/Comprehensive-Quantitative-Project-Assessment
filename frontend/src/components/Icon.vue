<script setup lang="ts">
defineProps<{ name: string }>();
</script>
<template>
  <img class="icon" :src="`/icons/${name}.svg`" alt="" aria-hidden="true" />
</template>

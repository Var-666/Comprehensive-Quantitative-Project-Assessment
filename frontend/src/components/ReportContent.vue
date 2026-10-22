<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ content: string }>();
const lines = computed(() =>
  props.content.split(/\r?\n/).map((text, index) => {
    const fact = text.match(/^\[([A-Z][A-Z0-9_]*)\]\s*(.*)$/);
    return {
      text,
      index,
      factId: fact?.[1],
      factText: fact?.[2],
      section: /^[一二三四五六七八九十]+、/.test(text),
      note: /^说明[：:]/.test(text),
    };
  }),
);
</script>
<template>
  <article class="report-copy" aria-label="报告正文">
    <template v-for="line in lines" :key="line.index">
      <h3 v-if="line.index === 0" class="report-body-title">{{ line.text }}</h3>
      <h4 v-else-if="line.section" class="report-section-heading">
        {{ line.text }}
      </h4>
      <p v-else-if="line.factId" class="report-fact">
        <span class="report-fact-ref">[{{ line.factId }}]</span>{{ " " }}
        <span>{{ line.factText }}</span>
      </p>
      <p
        v-else-if="line.text"
        :class="{
          'report-body-subtitle': line.index === 1,
          'report-body-note': line.note,
        }"
      >
        {{ line.text }}
      </p>
    </template>
  </article>
</template>

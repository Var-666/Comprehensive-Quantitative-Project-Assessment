<script setup lang="ts">
import type { Component } from "vue";
withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    icon: Component;
    tone?: "blue" | "green" | "amber" | "red";
    compact?: boolean;
  }>(),
  { tone: "blue", compact: false },
);
</script>
<template>
  <div
    class="card stat stat-card"
    :class="[`stat-tone-${tone}`, { 'is-compact': compact }]"
    role="group"
    :aria-label="label"
  >
    <span class="stat-label">{{ label }}</span>
    <div class="stat-value-row">
      <strong>{{ value }}</strong>
      <span class="stat-icon" aria-hidden="true"><component :is="icon" /></span>
    </div>
    <small v-if="$slots.default" class="stat-note"><slot /></small>
  </div>
</template>
<style scoped>
.stat.stat-card {
  --stat-color: var(--blue);
  --stat-tint: var(--light);
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 112px;
  padding: 18px 20px;
  margin-bottom: 0;
  align-items: stretch;
  gap: 10px;
  border-radius: 12px;
  box-shadow: 0 2px 6px #17233806;
}
.stat.stat-tone-green {
  --stat-color: var(--green);
  --stat-tint: #eaf6f0;
}
.stat.stat-tone-amber {
  --stat-color: var(--amber);
  --stat-tint: var(--amberlight);
}
.stat.stat-tone-red {
  --stat-color: var(--red);
  --stat-tint: var(--redlight);
}
.stat-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 18px;
  bottom: 18px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--stat-color);
}
.stat-card > .stat-label {
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
  color: var(--muted);
}
.stat-value-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.stat-card .stat-value-row > strong {
  min-width: 0;
  font-size: 30px;
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: -0.025em;
  font-variant-numeric: tabular-nums;
  color: var(--stat-color);
}
.stat-icon {
  display: grid;
  place-items: center;
  flex: 0 0 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--stat-tint);
  color: var(--stat-color);
}
.stat-icon svg {
  width: 20px;
  height: 20px;
}
.stat-card > .stat-note {
  padding-top: 10px;
  border-top: 1px solid var(--line);
  font-size: 11px;
  line-height: 1.6;
  color: var(--muted);
}
.stat.stat-card.is-compact {
  min-height: 92px;
  padding: 14px;
  gap: 8px;
}
.stat-card.is-compact > .stat-label {
  font-size: 11px;
}
.stat-card.is-compact .stat-value-row > strong {
  font-size: 23px;
}
.is-compact .stat-icon {
  flex-basis: 28px;
  height: 28px;
  border-radius: 8px;
}
.is-compact .stat-icon svg {
  width: 17px;
  height: 17px;
}
@media (max-width: 1200px) {
  .stat.stat-card {
    padding: 16px;
  }
  .stat-card .stat-value-row > strong {
    font-size: 25px;
  }
}
</style>

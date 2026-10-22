<script setup lang="ts">
import { computed, ref } from "vue";
import { ElButton } from "element-plus/es/components/button/index";
import { Bell, Connection } from "@element-plus/icons-vue";
import type { NodeConfiguration } from "../workflowTypes";
import StatusBadge from "./StatusBadge.vue";
const props = defineProps<{
  configuration: NodeConfiguration;
  saved?: boolean;
}>();
defineEmits<{
  actions: [event: Event, select: boolean];
  approve: [];
  refresh: [];
}>();
const showRules = ref(false);
const extraIssues = computed(() =>
  props.configuration.issues.filter(
    (issue) =>
      issue !== props.configuration.actions.label &&
      issue !== props.configuration.reminders.label,
  ),
);
const roles: Record<string, string> = {
  admin: "项目管理员",
  editor: "项目编辑人员",
  reviewer: "项目审核人员",
  viewer: "项目只读人员",
};
const actionText = computed(() => {
  const actions = props.configuration.actions;
  const templates = [
    ...new Set(
      actions.links
        ?.filter((l) => l.applicable)
        .map((l) => `${l.template_title} ${l.snapshot_json.version_label}`),
    ),
  ];
  return actions.status === "automatic"
    ? `已自动关联【${templates.join("、")}】，共 ${actions.action_count} 项标准动作`
    : actions.status === "conflict"
      ? `找到 ${actions.candidate_count} 个适用模板，请确认使用哪一套`
      : actions.label;
});
</script>
<template>
  <section class="form-section node-configuration" aria-label="节点配置检查">
    <div class="section-title">
      <h3>{{ saved ? "节点配置结果" : "节点配置检查" }}</h3>
      <span class="badge" :class="configuration.ready ? 'verified' : 'draft'"
        >{{ saved ? "已保存 · " : "" }}{{ configuration.label }}</span
      >
    </div>
    <ElButton link @click="$emit('refresh')">重新检查配置</ElButton>
    <dl class="configuration-facts">
      <div
        class="configuration-summary"
        :class="
          configuration.tracking_only
            ? 'is-neutral'
            : ['automatic', 'manual'].includes(configuration.actions.status)
              ? 'is-linked'
              : 'is-pending'
        "
      >
        <dt><Connection aria-hidden="true" />标准动作</dt>
        <dd>{{ actionText }}</dd>
      </div>
      <div
        class="configuration-summary"
        :class="
          configuration.tracking_only
            ? 'is-neutral'
            : configuration.reminders.status === 'ready'
              ? 'is-ready'
              : 'is-pending'
        "
      >
        <dt><Bell aria-hidden="true" />提醒规则</dt>
        <dd>
          {{
            configuration.reminders.rules.length
              ? configuration.reminders.rules
                  .map(
                    (r) =>
                      `提前 ${r.days_before} 个${r.day_basis === "workday" ? "工作日" : "自然日"}`,
                  )
                  .join("；")
              : configuration.reminders.label
          }}
        </dd>
      </div>
      <div class="configuration-plan">
        <dt>计划状态</dt>
        <dd>
          {{ configuration.plan.version_label }}
          <StatusBadge :value="configuration.plan.status" />
          <span v-if="configuration.plan.status === 'draft'" class="muted"
            >尚未批准，暂不触发正式提醒</span
          >
        </dd>
      </div>
    </dl>
    <ul v-if="extraIssues.length" class="configuration-issues">
      <li v-for="issue in extraIssues" :key="issue">{{ issue }}</li>
    </ul>
    <p class="configuration-next">{{ configuration.next_step }}</p>
    <div class="actions">
      <ElButton
        v-if="configuration.actions.action_count"
        @click="$emit('actions', $event, false)"
        >查看已关联动作</ElButton
      >
      <ElButton
        v-else-if="
          !configuration.tracking_only &&
          configuration.actions.can_modify &&
          configuration.actions.candidate_count
        "
        @click="$emit('actions', $event, true)"
        >{{
          configuration.actions.status === "conflict"
            ? "选择动作模板"
            : "关联标准动作"
        }}</ElButton
      >
      <ElButton
        v-if="!configuration.tracking_only"
        @click="showRules = !showRules"
        >{{ showRules ? "收起提醒规则" : "查看提醒规则" }}</ElButton
      >
      <ElButton v-if="configuration.plan.can_approve" @click="$emit('approve')"
        >前往计划审批</ElButton
      >
    </div>
    <p
      v-if="!configuration.tracking_only && !configuration.actions.can_modify"
      class="muted"
    >
      {{ configuration.actions.blocked_reason }}
    </p>
    <p
      v-if="
        !configuration.tracking_only &&
        !configuration.can_configure_public &&
        (!configuration.actions.candidate_count ||
          configuration.reminders.status !== 'ready')
      "
      class="muted"
    >
      请联系系统管理员配置公共模板、提醒规则或日历；由独立审核人员批准。
    </p>
    <div v-if="showRules" class="configuration-rules">
      <p v-if="!configuration.reminders.rules.length" class="muted">
        {{ configuration.reminders.label }}
      </p>
      <article
        v-for="rule in configuration.reminders.rules"
        :key="rule.id"
        :class="{ 'has-problem': rule.reason }"
      >
        <strong>{{ rule.rule_code }} · {{ rule.version_label }}</strong>
        <p>
          提前 {{ rule.days_before }} 个{{
            rule.day_basis === "workday" ? "工作日" : "自然日"
          }}
          · {{ roles[rule.recipient_role_code] }}（{{ rule.recipient_count }}
          个可用接收人）
        </p>
        <p v-if="rule.calendar_label">工作日历：{{ rule.calendar_label }}</p>
        <p>提醒日期：{{ rule.trigger_date || "暂不可计算" }}</p>
        <p v-if="rule.reason" class="configuration-problem">
          {{ rule.reason }}
        </p>
      </article>
      <RouterLink
        v-if="configuration.can_configure_public"
        to="/actions?tab=rules"
        >维护公共提醒规则 →</RouterLink
      >
    </div>
    <RouterLink
      v-if="
        configuration.can_configure_public &&
        !configuration.tracking_only &&
        !configuration.actions.candidate_count
      "
      to="/actions"
      >维护标准动作模板 →</RouterLink
    >
  </section>
</template>
<style scoped>
.node-configuration {
  display: grid;
  gap: 16px;
}
.node-configuration > * {
  min-width: 0;
  margin-block: 0;
}
.node-configuration > .el-button,
.node-configuration > a {
  justify-self: start;
}
.configuration-facts {
  display: grid;
  gap: 12px;
}
.configuration-facts > div {
  min-width: 0;
}
.configuration-facts .configuration-summary {
  --summary-color: var(--muted);
  --summary-tint: var(--pale);
  padding: 16px;
  border: 1px solid color-mix(in srgb, var(--summary-color) 20%, white);
  border-left: 3px solid var(--summary-color);
  border-radius: 10px;
  background: var(--summary-tint);
}
.configuration-summary.is-linked {
  --summary-color: var(--blue);
  --summary-tint: var(--light);
}
.configuration-summary.is-ready {
  --summary-color: var(--green);
  --summary-tint: #eaf6f0;
}
.configuration-summary.is-pending {
  --summary-color: var(--amber);
  --summary-tint: var(--amberlight);
}
.configuration-summary dt {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 8px;
  color: var(--summary-color);
  font-weight: 600;
}
.configuration-summary dt svg {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
}
.configuration-plan {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 12px;
  padding: 4px 0;
}
.configuration-plan dt {
  color: var(--muted);
}
.configuration-facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.configuration-issues {
  padding-left: 18px;
  color: #b76a13;
}
.configuration-next {
  padding: 12px;
  background: var(--light);
  border-radius: 8px;
}
.configuration-rules {
  display: grid;
  gap: 12px;
}
.configuration-rules article {
  border: 1px solid #d3e8df;
  border-radius: 8px;
  padding: 12px;
  background: #f4faf7;
}
.configuration-rules article.has-problem {
  border-color: #eed9b6;
  background: var(--amberlight);
}
.configuration-rules p {
  margin: 8px 0 0;
}
.configuration-problem {
  color: #b76a13;
}
</style>

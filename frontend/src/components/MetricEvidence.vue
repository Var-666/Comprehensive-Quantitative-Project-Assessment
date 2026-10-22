<script setup lang="ts">
import { ElButton } from "element-plus/es/components/button/index";
import type { Evidence, Metric } from "../evaluationTypes";
import { categoryLabels } from "../evaluationTypes";
import Modal from "./Modal.vue";
defineProps<{ row: Evidence; metric: Metric }>();
defineEmits<{ close: [] }>();
</script>
<template>
  <Modal
    class="metric-evidence-drawer"
    title="异常节点追溯"
    drawer
    @close="$emit('close')"
    ><div class="notice">
      冻结计算证据 · {{ metric.plan_version_label }} · 截止
      {{ metric.as_of_date }}<br />计算时间 {{ metric.computed_at }}
    </div>
    <h3>{{ row.milestone_code }} · {{ row.milestone_name }}</h3>
    <span class="badge">{{ categoryLabels[row.category] }}</span>
    <dl class="details">
      <dt>计划日期</dt>
      <dd>{{ row.planned_date }}</dd>
      <dt>已核实实际日期</dt>
      <dd>{{ row.actual_date || "暂无已核实日期" }}</dd>
      <dt>计划偏差</dt>
      <dd>
        {{
          row.deviation_days === null ? "不计算" : `${row.deviation_days} 天`
        }}
      </dd>
      <dt>责任部门</dt>
      <dd>{{ row.department || "未指定" }}</dd>
      <dt>计划来源</dt>
      <dd>{{ row.source_ref }}</dd>
      <dt>日期性质</dt>
      <dd>{{ row.date_kind }}</dd>
      <dt>计划项 ID</dt>
      <dd>{{ row.plan_item_id }}</dd>
      <dt>有效核实记录 ID</dt>
      <dd>{{ row.verified_actual_id || "暂无" }}</dd>
    </dl>
    <h3>后端判定依据</h3>
    <p>{{ row.reason }}</p>
    <p class="notice warning">
      待核对不直接认定延期。本次不判断责任、资金到账或后续节点因果影响。
    </p>
    <h3>冻结时实际记录</h3>
    <p v-if="!row.actual_records.length" class="empty">
      没有实际记录，不能认定已完成。
    </p>
    <div v-for="a in row.actual_records" :key="a.id" class="fact-box">
      <p>{{ a.id }} · {{ a.verification_status }}</p>
      <p>
        实际日期：{{ a.actual_date || "未填写" }}；完成标记：{{
          a.completion_flag === null
            ? "未明确"
            : a.completion_flag
              ? "已完成"
              : "尚未完成"
        }}
      </p>
      <p>来源：{{ a.evidence_ref }}</p>
      <p>
        提交人 {{ a.submitted_by }} / 核实人 {{ a.verified_by || "暂无" }} /
        {{ a.verified_at || "尚未核实" }}
      </p>
    </div>
    <small class="muted">来源摘要 {{ metric.source_digest }}</small
    ><template #footer
      ><RouterLink class="button" :to="`/projects/${metric.project_id}`"
        >查看当前项目记录</RouterLink
      ><ElButton @click="$emit('close')" native-type="submit"
        >关闭追溯</ElButton
      ></template
    ></Modal
  >
</template>

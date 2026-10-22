<script setup lang="ts">
import OperationToast from "../components/OperationToast.vue";
import PageNavigation from "../components/PageNavigation.vue";
import StatCard from "../components/StatCard.vue";
import {
  Calendar,
  TrendCharts,
  Warning,
  Clock,
  InfoFilled,
  ArrowRight,
} from "@element-plus/icons-vue";
import FormDate from "../components/FormDate.vue";
import { ElButton } from "element-plus/es/components/button/index";
import FormSelect from "../components/FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, errorMessage, json } from "../api";
import { useAuth } from "../store";
import {
  businessToday,
  categoryLabels,
  type MetricSummary,
  type Metric,
  type Evidence,
  type Snapshot,
  type Counts,
} from "../evaluationTypes";
import Modal from "../components/Modal.vue";
import Icon from "../components/Icon.vue";
import MetricEvidence from "../components/MetricEvidence.vue";
const router = useRouter();
const route = useRoute();
const auth = useAuth(),
  asOf = ref(businessToday()),
  loadedAsOf = ref(""),
  data = ref<MetricSummary>(),
  selected = ref<Metric>(),
  evidence = ref<Evidence>(),
  formula = ref(false),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  category = ref(""),
  history = ref<Snapshot[]>([]),
  snapshotId = ref(""),
  page = ref(1);
const counts = computed(() => selected.value?.counts || data.value?.counts);
const rows = computed(
  () =>
    selected.value?.evidence.filter(
      (r) => !category.value || r.category === category.value,
    ) || [],
);
const composition = computed(() =>
  Object.entries(categoryLabels).map(([key, label]) => ({
    key,
    label,
    value: Number(selected.value?.counts[key as keyof Counts] ?? 0),
  })),
);
const displayRows = computed(() =>
  rows.value.slice((page.value - 1) * 20, page.value * 20),
);
async function load() {
  busy.value = true;
  error.value = "";
  selected.value = undefined;
  try {
    data.value = await api<MetricSummary>(
      `/metrics/summary?as_of=${asOf.value}`,
    );
    loadedAsOf.value = asOf.value;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function choose(p: Metric) {
  selected.value = p;
  category.value = "";
  page.value = 1;
  snapshotId.value = "";
  error.value = "";
  try {
    history.value = await api<Snapshot[]>(
      `/projects/${p.project_id}/metric-snapshots`,
    );
  } catch (e) {
    error.value = errorMessage(e);
  }
}
async function freeze() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    const snap = await api<Snapshot>(
      `/projects/${selected.value.project_id}/metric-snapshots`,
      {
        method: "POST",
        body: json({
          as_of: selected.value.as_of_date,
          plan_version_id: selected.value.plan_version_id,
        }),
      },
    );
    selected.value = snap.payload_json;
    snapshotId.value = snap.id;
    history.value = await api<Snapshot[]>(
      `/projects/${selected.value.project_id}/metric-snapshots`,
    );
    success.value =
      "已保存评价快照；若数据期间发生变化，页面已更新为本次冻结结果。";
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function openSnapshot() {
  if (!snapshotId.value) return;
  busy.value = true;
  try {
    selected.value = (
      await api<Snapshot>(`/metric-snapshots/${snapshotId.value}`)
    ).payload_json;
    page.value = 1;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function prepareReport() {
  if (!selected.value) return;
  busy.value = true;
  error.value = "";
  try {
    if (!snapshotId.value) {
      const snap = await api<Snapshot>(
        `/projects/${selected.value.project_id}/metric-snapshots`,
        {
          method: "POST",
          body: json({
            as_of: selected.value.as_of_date,
            plan_version_id: selected.value.plan_version_id,
          }),
        },
      );
      snapshotId.value = snap.id;
      selected.value = snap.payload_json;
    }
    await router.push({
      path: "/analysis",
      query: {
        project: selected.value.project_id,
        as_of: selected.value.as_of_date,
        snapshot: snapshotId.value,
      },
    });
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  await load();
  const project = data.value?.projects.find(
    (p) => p.project_id === route.query.project,
  );
  if (project) await choose(project);
});
</script>
<template>
  <div class="page-title">
    <div>
      <h1>
        {{
          selected
            ? `${selected.project_code} 项目量化评估明细`
            : "项目量化评估"
        }}
      </h1>
      <p>以计划版本和核实事实为依据 · 试算指标，不生成综合考核得分</p>
    </div>
    <div class="actions">
      <div v-if="!selected" class="metric-date-controls">
        <label
          >业务统计截止日<FormDate
            v-model="asOf"
            :aria-label="'业务统计截止日'"
        /></label>
        <ElButton :disabled="busy || !asOf" @click="load" native-type="submit"
          >计算评价</ElButton
        >
      </div>
      <ElButton
        v-if="selected"
        @click="selected = undefined"
        native-type="submit"
        >返回项目评价</ElButton
      ><a
        v-else
        class="button primary"
        :href="`/api/v1/metrics/export?as_of=${loadedAsOf}`"
        ><Icon name="imgVectorFileDown" />导出评价数据</a
      ><ElButton
        v-if="selected"
        class="primary"
        :disabled="busy || !auth.can(selected.project_id)"
        @click="prepareReport"
        native-type="submit"
        type="primary"
      >
        生成阶段报告
      </ElButton>
    </div>
  </div>
  <p v-if="error" class="error" role="alert">
    {{ error }} <ElButton @click="load" native-type="submit">重新加载</ElButton>
  </p>
  <OperationToast v-model="success" :busy="busy" />
  <div v-if="selected" class="card filters">
    <span class="badge">{{ selected.plan_version_label }}</span
    ><span
      >截止 {{ selected.as_of_date }} ·
      {{ selected.sample ? "模拟测试数据" : "业务数据" }}</span
    ><span class="muted">计算 {{ selected.computed_at }}</span
    ><ElButton
      v-if="auth.can(selected.project_id)"
      :disabled="busy"
      @click="freeze"
      native-type="submit"
    >
      保存评价快照</ElButton
    ><label
      >已保存快照<FormSelect
        v-model="snapshotId"
        @change="openSnapshot"
        :aria-label="'已保存快照'"
      >
        <ElOption data-ui-value="" value="" :label="'当前计算结果'" />
        <ElOption
          :data-ui-value="s.id"
          v-for="s in history"
          :key="s.id"
          :value="s.id"
          :label="String(s.as_of_date) + ' · ' + String(s.created_at)"
        /> </FormSelect
    ></label>
  </div>
  <p v-if="busy" class="empty">正在计算或读取证据…</p>
  <template v-else-if="counts"
    ><div class="stat-grid">
      <StatCard label="应完成节点" :value="counts.due_total" :icon="Calendar">
        截止日到期且纳入计划
      </StatCard>
      <StatCard
        label="按期率（试算）"
        :value="
          counts.on_time_rate_pct === null ? '—' : `${counts.on_time_rate_pct}%`
        "
        :icon="TrendCharts"
        tone="green"
      >
        O / (O + L)
        <ElButton
          class="text-button"
          @click="formula = true"
          native-type="submit"
          link
        >
          查看口径
        </ElButton>
      </StatCard>
      <StatCard
        label="延期完成"
        :value="counts.late_completed"
        :icon="Warning"
        tone="red"
      >
        已有独立核实的完成事实
      </StatCard>
      <StatCard
        label="待核对"
        :value="counts.pending_verification"
        :icon="Clock"
        tone="amber"
      >
        事实不足，不直接归为延期
      </StatCard>
    </div>
    <div class="metric-panels">
      <section class="card metric-panel">
        <h3>{{ selected ? "节点评价构成" : "节点类型完成情况" }}</h3>
        <template v-if="selected"
          ><div
            v-for="item in composition"
            :key="item.key"
            class="metric-bar-row"
          >
            <span>{{ item.label }}</span
            ><progress
              :value="item.value as number"
              :max="selected.evidence.length || 1"
            /><strong>{{ item.value }}</strong>
          </div></template
        ><template v-else
          ><div
            v-for="g in data?.groups"
            :key="g.node_type_code"
            class="metric-bar-row"
          >
            <span>{{ g.node_type_code }}</span
            ><progress
              :value="g.on_time_completed + g.late_completed"
              :max="g.due_total || 1"
            /><span>{{
              g.completion_verification_coverage_pct === null
                ? "—"
                : `${g.completion_verification_coverage_pct}%`
            }}</span>
          </div></template
        >
      </section>
      <section
        class="card metric-panel metric-quality"
        aria-labelledby="quality-title"
      >
        <h3 id="quality-title">评价说明与数据质量</h3>
        <div class="quality-stats">
          <div class="quality-stat">
            <span>完成事实核实覆盖率</span>
            <strong class="quality-value coverage-value">{{
              counts.completion_verification_coverage_pct === null
                ? "—"
                : `${counts.completion_verification_coverage_pct}%`
            }}</strong>
            <progress
              v-if="counts.completion_verification_coverage_pct !== null"
              class="quality-coverage"
              :value="Number(counts.completion_verification_coverage_pct)"
              max="100"
              aria-label="完成事实核实覆盖率"
            />
          </div>
          <div class="quality-stat">
            <span>已核实逾期未完成</span>
            <strong class="quality-value overdue-value">{{
              counts.confirmed_overdue_unfinished
            }}</strong>
          </div>
        </div>
        <div class="quality-note">
          <InfoFilled class="icon" aria-hidden="true" />
          <p>逾期未完成单独列示，不计入试算按期率分母。</p>
        </div>
        <ElButton
          class="text-button quality-basis"
          @click="formula = true"
          native-type="button"
          link
        >
          查看评价口径与数据依据 <ArrowRight class="icon" aria-hidden="true" />
        </ElButton>
      </section>
    </div>
    <section v-if="!selected" class="card table-card">
      <div class="section-title">
        <h3>项目评价列表</h3>
      </div>
      <div class="table-wrap">
        <table class="metric-list-table">
          <thead>
            <tr>
              <th>项目编号</th>
              <th>项目名称</th>
              <th>计划版本</th>
              <th>应完成</th>
              <th>按期完成</th>
              <th>延期完成</th>
              <th>待核对</th>
              <th>已核实逾期未完成</th>
              <th>按期率</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in data?.projects" :key="p.project_id">
              <td>
                <strong>{{ p.project_code }}</strong>
              </td>
              <td>{{ p.project_name }}</td>
              <td>{{ p.plan_version_label }}</td>
              <td>{{ p.counts.due_total }}</td>
              <td>{{ p.counts.on_time_completed }}</td>
              <td>{{ p.counts.late_completed }}</td>
              <td>{{ p.counts.pending_verification }}</td>
              <td>{{ p.counts.confirmed_overdue_unfinished }}</td>
              <td>
                {{
                  p.counts.on_time_rate_pct === null
                    ? "—"
                    : `${p.counts.on_time_rate_pct}%`
                }}
              </td>
              <td>
                <ElButton
                  class="text-button"
                  @click="choose(p)"
                  native-type="submit"
                  link
                  >评价明细</ElButton
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!data?.projects.length" class="empty">尚无可评价的生效计划。</p>
      <p v-for="p in data?.unavailable" :key="p.project_id" class="muted">
        {{ p.project_code }}：{{ p.reason }}
      </p>
    </section>
    <section v-else class="card table-card">
      <div class="section-title">
        <h3>节点评价与异常追溯</h3>
        <label
          >评价分类<FormSelect
            v-model="category"
            @change="page = 1"
            :aria-label="'评价分类'"
          >
            <ElOption data-ui-value="" value="" :label="'全部节点'" />
            <ElOption
              :data-ui-value="key"
              v-for="(label, key) in categoryLabels"
              :key="key"
              :value="key"
              :label="String(label)"
            /> </FormSelect
        ></label>
      </div>
      <div class="table-wrap">
        <table class="metric-list-table">
          <thead>
            <tr>
              <th>节点编号</th>
              <th>节点名称</th>
              <th>节点类型</th>
              <th>责任部门</th>
              <th>计划日期</th>
              <th>已核实实际日期</th>
              <th>偏差天数</th>
              <th>评价结果</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in displayRows" :key="r.milestone_id">
              <td>{{ r.milestone_code }}</td>
              <td>{{ r.milestone_name }}</td>
              <td>{{ r.node_type_code }}</td>
              <td>{{ r.department }}</td>
              <td>{{ r.planned_date }}</td>
              <td>{{ r.actual_date || "待核对" }}</td>
              <td>{{ r.deviation_days ?? "—" }}</td>
              <td>
                <span class="badge">{{ categoryLabels[r.category] }}</span>
              </td>
              <td>
                <ElButton
                  class="text-button"
                  @click="evidence = r"
                  native-type="submit"
                  link
                >
                  证据追溯
                </ElButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!rows.length" class="empty">该分类没有节点。</p>
      <PageNavigation
        :page="page"
        :total="rows.length"
        :page-size="20"
        :disabled="busy"
        @change="page = $event"
      />
      <small class="muted"
        >来源摘要
        {{ selected.source_digest }}；表格与指标使用同一次计算证据。</small
      >
    </section></template
  >
  <Modal
    v-if="formula && counts"
    title="评价口径说明"
    class="metric-formula-drawer"
    drawer
    @close="formula = false"
    ><div class="notice">用户已确认试算基线 · trial_v1 · 非综合绩效评分</div>
    <h3>按期率的计算</h3>
    <p>O / (O + L) × 100%</p>
    <p>
      O = {{ counts.on_time_completed }}，L = {{ counts.late_completed }}；结果
      {{
        counts.on_time_rate_pct === null
          ? "无有效分母，不计算"
          : `${counts.on_time_rate_pct}%`
      }}。
    </p>
    <h3>核实覆盖率</h3>
    <p>
      (O + L) / 应完成节点 × 100% =
      {{ counts.completion_verification_coverage_pct ?? "无有效分母" }}%
    </p>
    <p>
      待核对 {{ counts.pending_verification }}；已核实逾期未完成
      {{ counts.confirmed_overdue_unfinished }}；尚未到期
      {{ counts.not_due }}；已排除 {{ counts.excluded }}。
    </p>
    <p>{{ data?.formula.boundary }}</p>
    <p class="notice warning">
      {{ data?.formula.score }}
      实际提交、执行反馈及通知批准均不等于节点已核实完成。
    </p></Modal
  ><MetricEvidence
    v-if="evidence && selected"
    :row="evidence"
    :metric="selected"
    @close="evidence = undefined"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
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
onMounted(load);
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
      <button v-if="selected" @click="selected = undefined">返回项目评价</button
      ><a
        v-else
        class="button primary"
        :href="`/api/v1/metrics/export?as_of=${loadedAsOf}`"
        ><Icon name="imgVectorFileDown" />导出评价数据</a
      ><button
        v-if="selected"
        class="primary"
        :disabled="busy || !auth.can(selected.project_id)"
        @click="prepareReport"
      >
        生成阶段报告
      </button>
    </div>
  </div>
  <p v-if="error" class="error" role="alert">
    {{ error }} <button @click="load">重新加载</button>
  </p>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <div v-if="!selected" class="card filters">
    <label>业务统计截止日<input v-model="asOf" type="date" /></label
    ><button :disabled="busy || !asOf" @click="load">计算评价</button
    ><span class="muted">汇总按节点数量计算，项目百分比不直接取平均。</span>
  </div>
  <div v-else class="card filters">
    <span class="badge">{{ selected.plan_version_label }}</span
    ><span
      >截止 {{ selected.as_of_date }} ·
      {{ selected.sample ? "模拟测试数据" : "业务数据" }}</span
    ><span class="muted">计算 {{ selected.computed_at }}</span
    ><button
      v-if="auth.can(selected.project_id)"
      :disabled="busy"
      @click="freeze"
    >
      保存评价快照</button
    ><label
      >已保存快照<select v-model="snapshotId" @change="openSnapshot">
        <option value="">当前计算结果</option>
        <option v-for="s in history" :key="s.id" :value="s.id">
          {{ s.as_of_date }} · {{ s.created_at }}
        </option>
      </select></label
    >
  </div>
  <p v-if="busy" class="empty">正在计算或读取证据…</p>
  <template v-else-if="counts"
    ><div class="stat-grid">
      <div class="card stat">
        <span>应完成节点</span><strong>{{ counts.due_total }}</strong
        ><small>截止日到期且纳入计划</small>
      </div>
      <div class="card stat">
        <span>按期率（试算）</span
        ><strong class="active">{{
          counts.on_time_rate_pct === null ? "—" : `${counts.on_time_rate_pct}%`
        }}</strong
        ><small
          >O / (O + L)
          <button class="text-button" @click="formula = true">
            查看口径
          </button></small
        >
      </div>
      <div class="card stat">
        <span>延期完成</span
        ><strong class="draft">{{ counts.late_completed }}</strong
        ><small>已有独立核实的完成事实</small>
      </div>
      <div class="card stat">
        <span>待核对</span><strong>{{ counts.pending_verification }}</strong
        ><small>事实不足，不直接归为延期</small>
      </div>
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
      <section class="card metric-panel">
        <h3>评价说明与数据质量</h3>
        <p>
          已核实逾期未完成：<strong>{{
            counts.confirmed_overdue_unfinished
          }}</strong
          >，单独列示，不进入试算按期率分母。
        </p>
        <p>
          完成事实核实覆盖率：<strong>{{
            counts.completion_verification_coverage_pct === null
              ? "—"
              : `${counts.completion_verification_coverage_pct}%`
          }}</strong>
        </p>
        <p class="muted">{{ data?.formula.boundary }}</p>
        <button class="text-button" @click="formula = true">
          查看评价口径与数据依据 →
        </button>
      </section>
    </div>
    <section v-if="!selected" class="card table-card">
      <div class="section-title">
        <h3>项目评价列表</h3>
        <span class="muted">统计截止 {{ loadedAsOf }} · trial_v1</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>项目编号 / 名称</th>
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
                <strong>{{ p.project_code }}</strong
                ><small class="block muted">{{ p.project_name }}</small>
              </td>
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
                <button class="text-button" @click="choose(p)">评价明细</button>
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
          >评价分类<select v-model="category" @change="page = 1">
            <option value="">全部节点</option>
            <option
              v-for="(label, key) in categoryLabels"
              :key="key"
              :value="key"
            >
              {{ label }}
            </option>
          </select></label
        >
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>节点编号 / 名称</th>
              <th>类型 / 部门</th>
              <th>计划日期</th>
              <th>已核实实际日期</th>
              <th>偏差天数</th>
              <th>评价结果</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in displayRows" :key="r.milestone_id">
              <td>
                {{ r.milestone_code
                }}<small class="block muted">{{ r.milestone_name }}</small>
              </td>
              <td>
                {{ r.node_type_code
                }}<small class="block muted">{{ r.department }}</small>
              </td>
              <td>{{ r.planned_date }}</td>
              <td>{{ r.actual_date || "待核对" }}</td>
              <td>{{ r.deviation_days ?? "—" }}</td>
              <td>
                <span class="badge">{{ categoryLabels[r.category] }}</span>
              </td>
              <td>
                <button class="text-button" @click="evidence = r">
                  证据追溯
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!rows.length" class="empty">该分类没有节点。</p>
      <div class="pagination">
        <span>共 {{ rows.length }} 条 · 第 {{ page }} 页</span
        ><button :disabled="page === 1" @click="page--">上一页</button
        ><button :disabled="page * 20 >= rows.length" @click="page++">
          下一页
        </button>
      </div>
      <small class="muted"
        >来源摘要
        {{ selected.source_digest }}；表格与指标使用同一次计算证据。</small
      >
    </section></template
  >
  <Modal
    v-if="formula && counts"
    title="评价口径说明"
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

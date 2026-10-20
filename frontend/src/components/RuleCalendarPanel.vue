<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useAuth, useCatalog } from "../store";
import type { ReminderRule, Calendar } from "../workflowTypes";
import { label } from "../workflowTypes";
import ConfigApproval from "./ConfigApproval.vue";
import Modal from "./Modal.vue";
const props = defineProps<{ kind: "rules" | "calendars" }>();
const auth = useAuth(),
  catalog = useCatalog(),
  rules = ref<ReminderRule[]>([]),
  calendars = ref<Calendar[]>([]),
  busy = ref(false),
  error = ref(""),
  show = ref(false),
  success = ref("");
const form = reactive({
  code: "",
  version: "V1",
  source: "",
  type: "",
  days: 0,
  basis: "calendar_day",
  calendar: "",
  role: "editor",
  catchup: 0,
  start: "",
  end: "",
  entries: "",
});
const previews = reactive<
  Record<string, { planned_date: string; result: string }>
>({});
const editing = ref<ReminderRule | Calendar>();
const copying = ref(false);
async function load() {
  busy.value = true;
  error.value = "";
  try {
    [rules.value, calendars.value] = await Promise.all([
      api<ReminderRule[]>("/reminder-rules"),
      api<Calendar[]>("/work-calendars"),
    ]);
    for (const rule of rules.value)
      previews[rule.id] ||= { planned_date: "", result: "" };
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function open(item?: ReminderRule | Calendar, copy = false) {
  editing.value = item;
  copying.value = copy;
  Object.assign(form, {
    code: "",
    version: "V1",
    source: "",
    type: "",
    days: 0,
    basis: "calendar_day",
    calendar: "",
    role: "editor",
    catchup: 0,
    start: "",
    end: "",
    entries: "",
  });
  if (item) {
    Object.assign(form, {
      code: "rule_code" in item ? item.rule_code : item.calendar_code,
      version: copy ? "" : item.version_label,
      source: item.source_ref,
    });
    if ("rule_code" in item)
      Object.assign(form, {
        type: item.node_type_code,
        days: item.days_before,
        basis: item.day_basis,
        calendar: item.calendar_id || "",
        role: item.recipient_role_code,
        catchup: item.catch_up_days,
      });
    else {
      try {
        const calendar = await api<Calendar>("/work-calendars/" + item.id);
        Object.assign(form, {
          start: calendar.start_date,
          end: calendar.end_date,
          entries:
            calendar.days
              ?.map(
                (d) =>
                  `${d.calendar_date},${d.is_workday ? "1" : "0"},${d.reason}`,
              )
              .join("\n") || "",
        });
      } catch (e) {
        error.value = errorMessage(e);
        return;
      }
    }
  }
  show.value = true;
}
function prefill() {
  if (!form.start || !form.end) return;
  const start = new Date(form.start + "T00:00:00Z"),
    end = new Date(form.end + "T00:00:00Z");
  if (end < start || (+end - +start) / 86400000 > 3659) {
    error.value = "日历范围需在3660天内";
    return;
  }
  const lines = [];
  for (let d = start; d <= end; d = new Date(+d + 86400000))
    lines.push(
      `${d.toISOString().slice(0, 10)},${[0, 6].includes(d.getUTCDay()) ? "0" : "1"},周末草稿待核对节假日及调休`,
    );
  form.entries = lines.join("\n");
}
async function save() {
  busy.value = true;
  error.value = "";
  try {
    const modifying = editing.value && !copying.value;
    const options = {
      method: modifying ? "PATCH" : "POST",
      headers: modifying ? versionHeader(editing.value!.row_version) : {},
    };
    if (props.kind === "rules")
      await api(
        "/reminder-rules" + (modifying ? "/" + editing.value!.id : ""),
        {
          ...options,
          body: json({
            rule_code: form.code,
            version_label: form.version,
            source_ref: form.source,
            node_type_code: form.type,
            days_before: form.days,
            day_basis: form.basis,
            calendar_id: form.basis === "workday" ? form.calendar : null,
            recipient_role_code: form.role,
            catch_up_days: form.catchup,
          }),
        },
      );
    else {
      const days = form.entries
        .split("\n")
        .filter((s) => s.trim())
        .map((s) => {
          const [day, flag, ...reason] = s.split(",");
          if (!["0", "1"].includes(flag?.trim()))
            throw new Error("工作日标记必须为1或0");
          return {
            calendar_date: day.trim(),
            is_workday: flag.trim() === "1",
            reason: reason.join(",").trim(),
          };
        });
      await api(
        "/work-calendars" + (modifying ? "/" + editing.value!.id : ""),
        {
          ...options,
          body: json({
            calendar_code: form.code,
            version_label: form.version,
            source_ref: form.source,
            timezone_name: "Asia/Shanghai",
            start_date: form.start,
            end_date: form.end,
            days,
          }),
        },
      );
    }
    show.value = false;
    success.value = "草稿已保存，需提交并经另一名审核人批准";
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
async function loadDays(calendar: Calendar) {
  try {
    calendar.days = (
      await api<Calendar>("/work-calendars/" + calendar.id)
    ).days;
  } catch (e) {
    error.value = errorMessage(e);
  }
}
async function calculate(rule: ReminderRule) {
  const preview = previews[rule.id];
  try {
    const r = await api<{ trigger_date: string | null; reason: string | null }>(
      "/reminder-rules/preview-trigger",
      {
        method: "POST",
        body: json({
          planned_date: preview.planned_date,
          days_before: rule.days_before,
          day_basis: rule.day_basis,
          calendar_id: rule.calendar_id,
        }),
      },
    );
    preview.result = r.trigger_date || label(r.reason || "不可计算");
  } catch (e) {
    error.value = errorMessage(e);
  }
}
onMounted(load);
</script>
<template>
  <div class="section-title">
    <h3>{{ kind === "rules" ? "提醒规则版本" : "企业工作日历版本" }}</h3>
    <button
      :disabled="busy || !auth.user?.is_system_admin"
      class="primary"
      @click="open()"
    >
      {{ kind === "rules" ? "新建提醒规则" : "新建企业日历" }}
    </button>
  </div>
  <p v-if="error" class="error" role="alert">
    {{ error }} <button @click="load">重试</button>
  </p>
  <p v-if="success" class="success" role="status">{{ success }}</p>
  <p v-if="busy && !show" class="empty" role="status">正在加载配置…</p>
  <template v-if="kind === 'rules'">
    <p class="notice">
      提前天数、追补窗口和接收角色逐条配置；默认追补0天表示仅在触发当天生成一次。只有生效计划、已批准动作及规则共同满足条件时才生成草稿。
    </p>
    <p v-if="!rules.length && !busy" class="empty">尚未配置提醒规则。</p>
    <section v-for="rule in rules" :key="rule.id" class="card workflow-config">
      <div class="section-title">
        <h3>{{ rule.rule_code }} · {{ rule.version_label }}</h3>
        <span class="badge" :class="rule.status">{{ label(rule.status) }}</span>
      </div>
      <p>
        {{ rule.node_type_code }} · 提前{{ rule.days_before }}个{{
          label(rule.day_basis)
        }}
        · 接收{{ label(rule.recipient_role_code) }} · 追补{{
          rule.catch_up_days
        }}天
      </p>
      <p class="muted">
        依据：{{ rule.source_ref
        }}<template v-if="rule.calendar_id">
          · 日历：{{
            calendars.find((c) => c.id === rule.calendar_id)?.calendar_code
          }}</template
        >
      </p>
      <div v-if="auth.user?.is_system_admin" class="actions">
        <button v-if="rule.status === 'draft'" @click="open(rule)">
          编辑规则草稿</button
        ><button @click="open(rule, true)">创建规则新版本</button>
      </div>
      <ConfigApproval :item="rule" path="reminder-rules" @changed="load" />
      <form class="actions" @submit.prevent="calculate(rule)">
        <label
          >试算节点日期<input
            v-model="previews[rule.id].planned_date"
            type="date"
            required /></label
        ><button>试算触发日</button
        ><span role="status">{{ previews[rule.id].result }}</span>
      </form>
    </section>
  </template>
  <template v-else>
    <p class="notice">
      未配置或未批准企业日历时，工作日计算返回“待配置”。每天的工作/休息标记必须显式录入；周末预填仅为编制便利，需另行核对真实节假日及调休后批准。
    </p>
    <p v-if="!calendars.length && !busy" class="empty">尚未配置企业日历。</p>
    <section
      v-for="calendar in calendars"
      :key="calendar.id"
      class="card workflow-config"
    >
      <div class="section-title">
        <h3>{{ calendar.calendar_code }} · {{ calendar.version_label }}</h3>
        <span class="badge" :class="calendar.status">{{
          label(calendar.status)
        }}</span>
      </div>
      <p>
        {{ calendar.start_date }} ～ {{ calendar.end_date }} ·
        {{ calendar.timezone_name }}
      </p>
      <p class="muted">依据：{{ calendar.source_ref }}</p>
      <button @click="loadDays(calendar)">查看日期明细</button>
      <div v-if="calendar.days" class="calendar-days">
        <span v-for="d in calendar.days" :key="d.calendar_date"
          >{{ d.calendar_date }} {{ d.is_workday ? "工作" : "休息" }} ·
          {{ d.reason }}</span
        >
      </div>
      <div v-if="auth.user?.is_system_admin" class="actions">
        <button v-if="calendar.status === 'draft'" @click="open(calendar)">
          编辑日历草稿</button
        ><button @click="open(calendar, true)">创建日历新版本</button>
      </div>
      <ConfigApproval :item="calendar" path="work-calendars" @changed="load" />
    </section>
  </template>
  <Modal
    v-if="show"
    :title="
      (editing && !copying ? '编辑' : '新建') +
      (kind === 'rules' ? '提醒规则' : '企业日历')
    "
    wide
    :busy="busy"
    @close="show = false"
  >
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form id="rule-calendar" @submit.prevent="save">
      <div class="form-grid">
        <label
          >配置编号 *<input
            v-model="form.code"
            :readonly="!!editing"
            required
            maxlength="64" /></label
        ><label
          >版本号 *<input
            v-model="form.version"
            :readonly="!!editing && !copying"
            required
            maxlength="30" /></label
        ><label class="full"
          >配置依据 *<textarea v-model="form.source" required maxlength="500" />
        </label>
        <template v-if="kind === 'rules'"
          ><label
            >适用节点类型 *<select v-model="form.type" required>
              <option value="">请选择</option>
              <option
                v-for="n in catalog.nodeTypes"
                :key="n.code"
                :value="n.code"
              >
                {{ n.display_name }}
              </option>
            </select></label
          ><label
            >提前天数 *<input
              v-model.number="form.days"
              required
              type="number"
              min="0"
              max="365" /></label
          ><label
            >日期口径<select v-model="form.basis">
              <option value="calendar_day">自然日</option>
              <option value="workday">工作日</option>
            </select></label
          ><label v-if="form.basis === 'workday'"
            >企业日历 *<select v-model="form.calendar" required>
              <option value="">请选择批准日历</option>
              <option
                v-for="c in calendars.filter((c) => c.status === 'approved')"
                :key="c.id"
                :value="c.id"
              >
                {{ c.calendar_code }} · {{ c.version_label }}
              </option>
            </select></label
          ><label
            >接收角色<select v-model="form.role">
              <option
                v-for="role in ['admin', 'editor', 'reviewer', 'viewer']"
                :key="role"
                :value="role"
              >
                {{ label(role) }}
              </option>
            </select></label
          ><label
            >追补窗口（自然日）<input
              v-model.number="form.catchup"
              type="number"
              min="0"
              max="365"
              required /></label
        ></template>
        <template v-else
          ><label
            >覆盖开始日期 *<input
              v-model="form.start"
              type="date"
              required /></label
          ><label
            >覆盖结束日期 *<input v-model="form.end" type="date" required
          /></label>
          <div class="full">
            <button type="button" @click="prefill">预填周末草稿</button>
            <p class="muted">预填不代表企业日历确认，必须核对节假日及调休。</p>
          </div>
          <label class="full"
            >逐日配置（日期,1工作/0休息,依据） *<textarea
              v-model="form.entries"
              rows="12"
              required
              spellcheck="false"
              placeholder="2026-10-24,1,经批准的调休依据"
            /></label
        ></template>
      </div>
    </form>
    <template #footer
      ><button :disabled="busy" @click="show = false">取消</button
      ><button
        type="submit"
        form="rule-calendar"
        class="primary"
        :disabled="busy"
      >
        保存配置草稿
      </button></template
    >
  </Modal>
</template>

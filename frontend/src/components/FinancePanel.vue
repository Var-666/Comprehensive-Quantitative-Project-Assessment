<script setup lang="ts">
import OperationToast from "./OperationToast.vue";
import { ElButton } from "element-plus/es/components/button/index";
import FormSelect from "./FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import { ElCheckbox } from "element-plus/es/components/checkbox/index";
import { ElInput } from "element-plus/es/components/input/index";
import FormDate from "./FormDate.vue";
import { computed, onMounted, reactive, ref, watch } from "vue";
import { api, errorMessage, json, versionHeader } from "../api";
import { useAuth, useCatalog } from "../store";
import type {
  FinanceSummary,
  FinancialAccess,
  FinancialActual,
} from "../evaluationTypes";
import Modal from "./Modal.vue";
import { useUnsavedChanges } from "../useUnsavedChanges";
const props = defineProps<{ projectId: string; asOf: string }>();
const auth = useAuth(),
  catalog = useCatalog(),
  data = ref<FinanceSummary>(),
  access = ref<FinancialAccess[]>([]),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  mode = ref(""),
  review = ref<FinancialActual>(),
  comment = ref(""),
  decision = ref("verified");
const me = computed(() =>
  access.value.find((a) => a.user_id === auth.user?.user_id),
);
const manager = computed(
  () => auth.can(props.projectId, "manage") || auth.user?.is_system_admin,
);
const grant = reactive({
  user_id: "",
  can_read: true,
  can_write: false,
  can_verify: false,
});
const form = reactive({
  record_code: "",
  direction: "receivable",
  date: "",
  amount: "",
  currency: "",
  source: "",
  financial_plan_id: "",
  date_source_kind: "unconfirmed",
});
async function load() {
  busy.value = true;
  error.value = "";
  data.value = undefined;
  try {
    await catalog.load();
    access.value = await api<FinancialAccess[]>(
      `/projects/${props.projectId}/financial-access`,
    );
    if (me.value?.can_read)
      data.value = await api<FinanceSummary>(
        `/projects/${props.projectId}/financial-records?as_of=${props.asOf}`,
      );
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
function open(kind: string) {
  Object.assign(form, {
    record_code: "",
    direction: kind === "plan" ? "receivable" : "receipt",
    date: "",
    amount: "",
    currency: "",
    source: "",
    financial_plan_id: "",
    date_source_kind: "unconfirmed",
  });
  mode.value = kind;
}
const guard = useUnsavedChanges(
  () => (mode.value === "access" ? grant : form),
  () => !!mode.value,
  () => busy.value,
);
async function save() {
  busy.value = true;
  error.value = "";
  try {
    if (mode.value === "access") {
      await api(`/projects/${props.projectId}/financial-access`, {
        method: "PUT",
        body: json(grant),
      });
    } else {
      const body =
        mode.value === "plan"
          ? {
              record_code: form.record_code,
              direction: form.direction,
              planned_date: form.date,
              planned_amount: form.amount,
              currency: form.currency,
              source_ref: form.source,
              date_source_kind: form.date_source_kind,
            }
          : {
              record_code: form.record_code,
              direction: form.direction,
              actual_date: form.date,
              actual_amount: form.amount,
              currency: form.currency,
              evidence_ref: form.source,
              financial_plan_id: form.financial_plan_id || null,
            };
      await api(
        `/projects/${props.projectId}/financial-${mode.value === "plan" ? "plans" : "actuals"}`,
        { method: "POST", body: json(body) },
      );
    }
    mode.value = "";
    success.value = "财务记录或授权已保存；实际记录仍需独立核实。";
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
const reviewGuard = useUnsavedChanges(
  () => ({ comment: comment.value, decision: decision.value }),
  () => !!review.value,
  () => busy.value,
);
async function verify() {
  if (!review.value) return;
  busy.value = true;
  try {
    await api(`/financial-actuals/${review.value.id}/verify`, {
      method: "POST",
      headers: versionHeader(review.value.row_version),
      body: json({ decision: decision.value, comment: comment.value }),
    });
    review.value = undefined;
    comment.value = "";
    success.value = "财务核实结果已记录。";
    await load();
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
watch(() => [props.projectId, props.asOf], load);
onMounted(load);
</script>
<template>
  <section class="card table-card">
    <div class="section-title">
      <h3>计划与实际收付款</h3>
      <div class="actions">
        <ElButton v-if="manager" @click="mode = 'access'" native-type="submit"
          >财务额外授权</ElButton
        ><ElButton
          v-if="me?.can_write && auth.can(projectId)"
          @click="open('plan')"
          native-type="submit"
        >
          录入财务计划</ElButton
        ><ElButton
          v-if="me?.can_write && auth.can(projectId)"
          @click="open('actual')"
          native-type="submit"
        >
          录入实际收付款</ElButton
        ><ElButton :disabled="busy" @click="load" native-type="submit"
          >刷新财务记录</ElButton
        >
      </div>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <OperationToast v-model="success" :busy="busy" />
    <p v-if="busy" class="empty">加载中…</p>
    <p v-else-if="!me?.can_read" class="notice warning">
      当前账户未获本项目金额访问授权。项目角色不会自动获得财务权限。
    </p>
    <template v-else-if="data"
      ><p class="notice warning">
        {{ data.completeness_note }} 本页面仅列出实际日期不晚于
        {{ asOf }} 的记录，不跨币种合计。
      </p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>币种 / 方向</th>
              <th>计划总额</th>
              <th>到期计划</th>
              <th>已核实实际金额</th>
              <th>待核实实际记录</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="g in data.groups" :key="g.currency + g.direction">
              <td>
                {{ g.currency }} ·
                {{ g.direction === "receivable" ? "收款" : "付款" }}
              </td>
              <td>{{ g.planned_total }}</td>
              <td>{{ g.planned_due_total }}</td>
              <td>{{ g.verified_actual_total ?? "待核实，不能认定为0" }}</td>
              <td>{{ g.unverified_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <h3>财务计划（不代表实际发生）</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>计划编号</th>
              <th>方向</th>
              <th>计划日期</th>
              <th>计划金额</th>
              <th>来源 / 性质</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in data.plans" :key="p.id">
              <td>{{ p.record_code }}</td>
              <td>
                {{ p.direction === "receivable" ? "计划收款" : "计划付款" }}
              </td>
              <td>{{ p.planned_date }}</td>
              <td>{{ p.currency }} {{ p.planned_amount }}</td>
              <td>{{ p.source_ref }} / {{ p.date_source_kind }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!data.plans.length" class="empty">暂无财务计划。</p>
      <h3>实际收付款（独立录入和核实）</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>实际编号</th>
              <th>方向</th>
              <th>实际日期</th>
              <th>实际金额</th>
              <th>核实状态 / 凭证来源</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in data.actuals" :key="a.id">
              <td>{{ a.record_code }}</td>
              <td>{{ a.direction === "receipt" ? "实际收款" : "实际付款" }}</td>
              <td>{{ a.actual_date }}</td>
              <td>{{ a.currency }} {{ a.actual_amount }}</td>
              <td>
                {{ a.verification_status
                }}<small class="block muted">{{ a.evidence_ref }}</small>
              </td>
              <td>
                <ElButton
                  v-if="
                    a.verification_status === 'submitted' &&
                    me.can_verify &&
                    auth.can(projectId, 'review')
                  "
                  :disabled="a.submitted_by === auth.user?.user_id"
                  @click="
                    review = a;
                    comment = '';
                    decision = 'verified';
                  "
                  native-type="submit"
                >
                  独立财务核实
                </ElButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!data.actuals.length" class="empty">
        没有符合截止日的实际记录；不能推断为未发生。
      </p></template
    >
  </section>
  <Modal
    class="form-drawer"
    drawer
    :before-close="guard.confirmDiscard"
    v-if="mode"
    :title="
      mode === 'access'
        ? '财务额外授权'
        : mode === 'plan'
          ? '录入财务计划'
          : '录入实际收付款'
    "
    :busy="busy"
    @close="mode = ''"
    ><form id="finance-form" @submit.prevent="save">
      <template v-if="mode === 'access'"
        ><p class="notice warning">
          仅为已存在的项目成员授权；读取与写入、核实须明确配置。核实仍要求另一人和项目审核角色。
        </p>
        <label
          >项目成员 *<FormSelect
            v-model="grant.user_id"
            required
            :aria-label="'项目成员 *'"
          >
            <ElOption data-ui-value="" value="" :label="'选择成员'" />
            <ElOption
              :data-ui-value="u.id"
              v-for="u in catalog.users"
              :key="u.id"
              :value="u.id"
              :label="String(u.display_name)"
            /> </FormSelect></label
        ><ElCheckbox class="inline-label" v-model="grant.can_read"
          >金额读取</ElCheckbox
        ><ElCheckbox class="inline-label" v-model="grant.can_write"
          >财务录入</ElCheckbox
        ><ElCheckbox class="inline-label" v-model="grant.can_verify"
          >独立财务核实</ElCheckbox
        >
        <p class="muted">
          取消全部权限可撤销；已有含金额报告和导出也会停止访问。
        </p></template
      >
      <div v-else class="form-grid">
        <label
          >财务记录编号 *<ElInput
            v-model="form.record_code"
            required
            maxlength="64"
            :aria-label="'财务记录编号 *'" /></label
        ><label
          >收付款方向 *<FormSelect
            v-model="form.direction"
            :aria-label="'收付款方向 *'"
          >
            <ElOption
              :data-ui-value="mode === 'plan' ? 'receivable' : 'receipt'"
              :value="mode === 'plan' ? 'receivable' : 'receipt'"
              :label="String(mode === 'plan' ? '计划收款' : '实际收款')"
            />
            <ElOption
              :data-ui-value="mode === 'plan' ? 'payable' : 'payment'"
              :value="mode === 'plan' ? 'payable' : 'payment'"
              :label="String(mode === 'plan' ? '计划付款' : '实际付款')"
            /> </FormSelect></label
        ><label
          >{{ mode === "plan" ? "计划日期 *" : "实际发生日期 *"
          }}<FormDate
            v-model="form.date"
            required
            :aria-label="
              String(mode === 'plan' ? '计划日期 *' : '实际发生日期 *')
            " /></label
        ><label
          >{{ mode === "plan" ? "计划金额 *" : "实际金额 *"
          }}<ElInput
            v-model="form.amount"
            required
            type="text"
            inputmode="decimal"
            pattern="[0-9]+(\.[0-9]{1,2})?"
            :aria-label="
              String(mode === 'plan' ? '计划金额 *' : '实际金额 *')
            " /></label
        ><label
          >币种（三位大写） *<ElInput
            v-model="form.currency"
            required
            pattern="[A-Z]{3}"
            maxlength="3"
            placeholder="例如 CNY"
            :aria-label="'币种（三位大写） *'" /></label
        ><label v-if="mode === 'actual'"
          >关联财务计划<FormSelect
            v-model="form.financial_plan_id"
            :aria-label="'关联财务计划'"
          >
            <ElOption data-ui-value="" value="" :label="'不关联计划'" />
            <ElOption
              :data-ui-value="p.id"
              v-for="p in data?.plans"
              :key="p.id"
              :value="p.id"
              :label="String(p.record_code) + ' · ' + String(p.currency)"
            /> </FormSelect></label
        ><label v-else
          >日期来源性质<FormSelect
            v-model="form.date_source_kind"
            :aria-label="'日期来源性质'"
          >
            <ElOption
              data-ui-value="unconfirmed"
              value="unconfirmed"
              :label="'待确认'"
            />
            <ElOption
              data-ui-value="contractual"
              value="contractual"
              :label="'合同约定'"
            />
            <ElOption
              data-ui-value="internal_plan"
              value="internal_plan"
              :label="'内部计划'"
            /> </FormSelect></label
        ><label class="full"
          >{{ mode === "plan" ? "计划依据 *" : "实际凭证来源 *"
          }}<ElInput
            v-model="form.source"
            required
            maxlength="500"
            type="textarea"
            :aria-label="
              String(mode === 'plan' ? '计划依据 *' : '实际凭证来源 *')
            "
          />
        </label>
        <p class="notice warning full">
          计划日期与金额不会自动填入实际字段；录入实际事实后仍需另一名获授权人员核实。
        </p>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
    <template #footer="{ close }"
      ><ElButton :disabled="busy" @click="close" native-type="submit"
        >取消</ElButton
      ><ElButton
        form="finance-form"
        class="primary"
        :disabled="busy"
        native-type="submit"
        type="primary"
      >
        保存财务记录
      </ElButton></template
    ></Modal
  >
  <Modal
    v-if="review"
    :before-close="reviewGuard.confirmDiscard"
    title="独立财务核实"
    :busy="busy"
    @close="review = undefined"
    ><p>
      {{ review.record_code }} · {{ review.currency }}
      {{ review.actual_amount }} · {{ review.evidence_ref }}
    </p>
    <form id="finance-review" @submit.prevent="verify">
      <label
        >核实结论<FormSelect v-model="decision" :aria-label="'核实结论'">
          <ElOption
            data-ui-value="verified"
            value="verified"
            :label="'核实通过'"
          />
          <ElOption
            data-ui-value="returned"
            value="returned"
            :label="'退回补充'"
          />
          <ElOption
            data-ui-value="disputed"
            value="disputed"
            :label="'存在争议'"
          /> </FormSelect></label
      ><label
        >财务核实依据 *<ElInput
          v-model="comment"
          required
          maxlength="2000"
          type="textarea"
          :aria-label="'财务核实依据 *'"
        />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </form>
    <template #footer
      ><ElButton
        form="finance-review"
        class="primary"
        :disabled="busy"
        native-type="submit"
        type="primary"
      >
        确认财务核实
      </ElButton></template
    ></Modal
  >
</template>

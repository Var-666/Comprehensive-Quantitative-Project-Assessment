<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElButton } from "element-plus/es/components/button/index";
import { api, errorMessage } from "../api";
import type { Workbench } from "../workbenchTypes";
const data = ref<Workbench>(),
  busy = ref(false),
  error = ref("");
async function load() {
  busy.value = true;
  error.value = "";
  try {
    data.value = await api<Workbench>("/workbench/next-actions");
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <section class="card workbench-guide" aria-labelledby="next-action-title">
    <div class="section-title workbench-guide-heading">
      <h2 id="next-action-title">待处理事项</h2>
    </div>
    <p v-if="busy" role="status" class="muted">正在加载待处理事项…</p>
    <p v-else-if="error" class="error" role="alert">
      {{ error }} <ElButton @click="load">重试业务引导</ElButton>
    </p>
    <div v-else-if="data" class="workbench-guide-actions">
      <article class="workbench-primary">
        <div class="workbench-primary-meta">
          <span class="workbench-priority">优先处理</span>
          <time v-if="data.primary.due_date" :datetime="data.primary.due_date">
            截止 {{ data.primary.due_date }}
          </time>
        </div>
        <p v-if="data.primary.project_id" class="workbench-project">
          <span>{{ data.primary.project_code }}</span
          >{{ data.primary.project_name }}
        </p>
        <h3>
          {{
            data.primary.action_type === "create_project"
              ? "暂无可访问项目"
              : data.primary.title
          }}
        </h3>
        <p v-if="data.primary.blocked_reason" class="workbench-blocked">
          {{ data.primary.blocked_reason }}
        </p>
        <div
          v-if="data.primary.actionable && data.primary.target_path"
          class="workbench-guide-operation"
        >
          <RouterLink class="button primary" :to="data.primary.target_path">
            {{
              data.primary.action_type === "create_project"
                ? "进入项目管理"
                : data.primary.button_label
            }}
            →
          </RouterLink>
        </div>
      </article>
      <aside class="workbench-secondary" aria-label="其他待处理事项">
        <h3>其他事项</h3>
        <article v-for="item in data.secondary" :key="item.recommendation_id">
          <div>
            <p v-if="item.project_code" class="workbench-project">
              <span>{{ item.project_code }}</span
              >{{ item.project_name }}
            </p>
            <strong>{{ item.title }}</strong>
            <time v-if="item.due_date" :datetime="item.due_date"
              >截止 {{ item.due_date }}</time
            >
            <p v-if="item.blocked_reason" class="workbench-blocked">
              {{ item.blocked_reason }}
            </p>
            <RouterLink
              v-if="item.actionable && item.target_path"
              :to="item.target_path"
            >
              {{
                item.action_type === "create_project"
                  ? "进入项目管理"
                  : item.button_label
              }}
              →
            </RouterLink>
          </div>
        </article>
        <p v-if="!data.secondary.length" class="muted">暂无其他待处理事项。</p>
      </aside>
    </div>
  </section>
</template>

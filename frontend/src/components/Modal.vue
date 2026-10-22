<script setup lang="ts">
import { computed, useAttrs, useId } from "vue";
import { ElDialog } from "element-plus/es/components/dialog/index";
import { ElDrawer } from "element-plus/es/components/drawer/index";
import { ElButton } from "element-plus/es/components/button/index";
defineOptions({ inheritAttrs: false });
const props = defineProps<{
  title: string;
  subtitle?: string;
  wide?: boolean;
  drawer?: boolean;
  busy?: boolean;
  beforeClose?: () => Promise<boolean>;
}>();
const emit = defineEmits<{ close: [] }>();
const attrs = useAttrs();
const titleId = useId();
const workspaceOverlay = computed(() =>
  /llm-(key|manual|result)-modal/.test(String(attrs.class || "")),
);
async function close() {
  if (!props.busy && (!props.beforeClose || (await props.beforeClose())))
    emit("close");
}
</script>
<template>
  <component
    :is="drawer ? ElDrawer : ElDialog"
    v-bind="$attrs"
    :model-value="true"
    :title="title"
    class="modal"
    :class="{ wide, drawer }"
    :modal-class="
      workspaceOverlay
        ? 'ui-modal-overlay ui-workspace-overlay'
        : 'ui-modal-overlay'
    "
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="!busy"
    :before-close="close"
    :size="drawer ? 'var(--ui-drawer-width, 520px)' : undefined"
    @update:model-value="!$event && close()"
  >
    <template #header>
      <div class="modal-head">
        <div v-if="subtitle">
          <h2 :id="titleId">{{ title }}</h2>
          <p class="modal-subtitle">{{ subtitle }}</p>
        </div>
        <h2 v-else :id="titleId">{{ title }}</h2>
        <ElButton
          native-type="button"
          class="icon-button"
          aria-label="关闭"
          :disabled="busy"
          @click="close"
        >
          ×
        </ElButton>
      </div>
    </template>
    <div v-if="$slots.navigation" class="modal-navigation">
      <slot name="navigation" />
    </div>
    <div class="modal-body"><slot /></div>
    <template v-if="$slots.footer" #footer>
      <div class="modal-footer"><slot name="footer" :close="close" /></div>
    </template>
  </component>
</template>

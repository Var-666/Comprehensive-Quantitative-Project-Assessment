<script setup lang="ts">
import { getCurrentInstance, h, onBeforeUnmount, watch } from "vue";
import {
  ElMessage,
  type MessageHandler,
} from "element-plus/es/components/message/index";
const message = defineModel<string>({ required: true });
const props = defineProps<{ busy?: boolean }>();
const context = getCurrentInstance()?.appContext;
let toast: MessageHandler | undefined;
let generation = 0;
watch(
  () => [message.value, props.busy],
  () => {
    const current = ++generation;
    if (props.busy && toast) message.value = "";
    toast?.close();
    toast = undefined;
    if (!message.value || props.busy) return;
    const text = message.value;
    toast = ElMessage(
      {
        message: h("span", { role: "status", "aria-live": "polite" }, text),
        type: "success",
        duration: 4500,
        showClose: true,
        onClose: () => {
          if (current === generation && message.value === text)
            message.value = "";
        },
      },
      context,
    );
  },
  { immediate: true },
);
onBeforeUnmount(() => toast?.close());
</script>
<template></template>

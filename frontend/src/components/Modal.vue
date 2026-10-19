<script setup lang="ts">
import { onMounted, ref } from "vue";
defineProps<{
  title: string;
  wide?: boolean;
  drawer?: boolean;
  busy?: boolean;
}>();
const emit = defineEmits<{ close: [] }>();
const dialog = ref<HTMLDialogElement>();
onMounted(() => dialog.value?.showModal());
</script>
<template>
  <dialog
    ref="dialog"
    class="modal"
    :class="{ wide, drawer }"
    aria-labelledby="modal-title"
    @cancel.prevent="!busy && emit('close')"
  >
    <div class="modal-head">
      <h2 id="modal-title">{{ title }}</h2>
      <button
        type="button"
        class="icon-button"
        aria-label="关闭"
        :disabled="busy"
        @click="emit('close')"
      >
        ×
      </button>
    </div>
    <div class="modal-body"><slot /></div>
    <div v-if="$slots.footer" class="modal-footer"><slot name="footer" /></div>
  </dialog>
</template>

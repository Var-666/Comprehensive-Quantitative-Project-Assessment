<script setup lang="ts">
import { ref, watch } from "vue";
import { ElDatePicker } from "element-plus/es/components/date-picker/index";
defineOptions({ inheritAttrs: false });
const props = defineProps<{
  required?: boolean;
  disabled?: boolean;
  min?: string;
  max?: string;
}>();
const model = defineModel<string>();
const picker = ref<{ focus: () => void }>();
const invalid = ref(false);
watch([model, () => props.required], () => (invalid.value = false));
function disabledDate(date: Date) {
  const value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  return !!(
    (props.min && value < props.min) ||
    (props.max && value > props.max)
  );
}
function showRequired() {
  invalid.value = true;
  picker.value?.focus();
}
</script>
<template>
  <div class="ui-date-field" :class="{ 'is-invalid': invalid }">
    <ElDatePicker
      ref="picker"
      v-bind="$attrs"
      :model-value="model || null"
      @update:model-value="model = $event || ''"
      type="date"
      format="YYYY-MM-DD"
      value-format="YYYY-MM-DD"
      :disabled="props.disabled"
      :disabled-date="disabledDate"
      :aria-required="props.required || undefined"
      :aria-invalid="invalid || undefined"
      popper-class="project-element-popper"
    />
    <input
      v-if="props.required"
      class="ui-validity-proxy"
      type="date"
      aria-hidden="true"
      tabindex="-1"
      required
      :value="model || ''"
      :min="props.min"
      :max="props.max"
      :disabled="props.disabled"
      @invalid.prevent="showRequired"
    />
    <span v-if="invalid" class="ui-field-error" role="alert"
      >请选择有效日期</span
    >
  </div>
</template>

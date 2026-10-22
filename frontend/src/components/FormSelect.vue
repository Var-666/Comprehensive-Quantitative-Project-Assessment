<script setup lang="ts">
import { ref, watch } from "vue";
import { ElSelect } from "element-plus/es/components/select/index";
defineOptions({ inheritAttrs: false });
const props = defineProps<{ required?: boolean; disabled?: boolean }>();
const model = defineModel<string | number | null>();
const select = ref<InstanceType<typeof ElSelect>>();
const invalid = ref(false);
watch(model, () => (invalid.value = false));
function showRequired() {
  invalid.value = true;
  select.value?.focus();
}
</script>
<template>
  <div class="ui-select-field" :class="{ 'is-invalid': invalid }">
    <ElSelect
      ref="select"
      :model-value="model ?? ''"
      @update:model-value="model = $event"
      :empty-values="[null, undefined]"
      v-bind="$attrs"
      :disabled="props.disabled"
      :aria-required="props.required || undefined"
      :aria-invalid="invalid || undefined"
      filterable
      popper-class="project-element-popper"
      ><slot
    /></ElSelect>
    <!-- Preserve native form validation because ElSelect has no required input. -->
    <input
      v-if="props.required"
      class="ui-validity-proxy"
      aria-hidden="true"
      tabindex="-1"
      required
      :value="model ?? ''"
      :disabled="props.disabled"
      @invalid.prevent="showRequired"
    />
    <span v-if="invalid" class="ui-field-error" role="alert">请选择必填项</span>
  </div>
</template>

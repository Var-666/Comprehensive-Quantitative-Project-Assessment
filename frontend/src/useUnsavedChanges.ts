import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate } from "vue-router";
import { ElMessageBox } from "element-plus/es/components/message-box/index";

export function useUnsavedChanges<T extends Record<string, unknown>>(
  value: () => T,
  active: () => boolean = () => true,
  busy: () => boolean = () => false,
) {
  const snapshot = () => JSON.stringify(value());
  const baseline = ref(snapshot());
  const dirty = computed(() => active() && snapshot() !== baseline.value);
  function markSaved(keys?: (keyof T)[]) {
    if (!keys) baseline.value = snapshot();
    else {
      const saved = JSON.parse(baseline.value);
      const current = JSON.parse(snapshot());
      for (const key of keys) saved[key] = current[key];
      baseline.value = JSON.stringify(saved);
    }
  }
  watch(active, () => markSaved(), { flush: "post" });
  let confirmation: Promise<boolean> | undefined;
  function confirmDiscard(): Promise<boolean> {
    if (!dirty.value) return Promise.resolve(true);
    if (busy()) return Promise.resolve(false);
    if (!confirmation)
      confirmation = ElMessageBox.confirm(
        "当前修改尚未保存，离开后将丢失这些修改。",
        "放弃未保存的修改？",
        {
          confirmButtonText: "放弃修改",
          cancelButtonText: "继续编辑",
          type: "warning",
          closeOnClickModal: false,
          distinguishCancelAndClose: true,
        },
      )
        .then(() => true)
        .catch(() => false)
        .finally(() => {
          confirmation = undefined;
        });
    return confirmation;
  }
  function beforeUnload(event: BeforeUnloadEvent) {
    if (dirty.value || (active() && busy())) {
      event.preventDefault();
      event.returnValue = "";
    }
  }
  onBeforeRouteLeave(confirmDiscard);
  onBeforeRouteUpdate(confirmDiscard);
  onMounted(() => window.addEventListener("beforeunload", beforeUnload));
  onBeforeUnmount(() =>
    window.removeEventListener("beforeunload", beforeUnload),
  );
  return { dirty, markSaved, confirmDiscard };
}

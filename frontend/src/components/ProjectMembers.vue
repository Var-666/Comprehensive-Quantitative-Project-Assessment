<script setup lang="ts">
import FormSelect from "./FormSelect.vue";
import { ElOption } from "element-plus/es/components/select/index";
import { ElButton } from "element-plus/es/components/button/index";
import { onMounted, ref } from "vue";
import { api, errorMessage, json } from "../api";
import { useAuth, useCatalog } from "../store";
const props = defineProps<{ projectId: string }>(),
  auth = useAuth(),
  catalog = useCatalog();
interface Member {
  id: string;
  user_id: string;
  role_code: string;
  active: boolean;
  display_name: string;
}
const members = ref<Member[]>([]),
  userId = ref(""),
  role = ref("reviewer"),
  error = ref(""),
  busy = ref(false);
const labels: Record<string, string> = {
  admin: "项目管理员",
  editor: "编辑",
  reviewer: "审核",
  viewer: "只读",
};
async function load() {
  try {
    await catalog.load();
    members.value = await api<Member[]>(`/projects/${props.projectId}/members`);
  } catch (e) {
    error.value = errorMessage(e);
  }
}
async function save(
  user_id = userId.value,
  role_code = role.value,
  active = true,
) {
  busy.value = true;
  error.value = "";
  try {
    await api(`/projects/${props.projectId}/members`, {
      method: "PUT",
      body: json({ user_id, role_code, active }),
    });
    await Promise.all([load(), auth.load()]);
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <section class="card table-card">
    <h3>项目成员与权限</h3>
    <p class="muted">
      编制人与批准人、实际提交人与核实人必须分离。授权对象需要已配置登录账号。
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <form
      v-if="auth.user?.is_system_admin || auth.can(projectId, 'manage')"
      class="filters compact"
      @submit.prevent="save()"
    >
      <label
        >授权人员<FormSelect v-model="userId" required aria-label="授权人员">
          <ElOption data-ui-value="" value="" disabled :label="'请选择'" />
          <ElOption
            :data-ui-value="u.id"
            v-for="u in catalog.users"
            :key="u.id"
            :value="u.id"
            :label="String(u.display_name)"
          /> </FormSelect></label
      ><label
        >项目角色<FormSelect v-model="role" aria-label="项目角色">
          <ElOption
            :data-ui-value="key"
            v-for="(label, key) in labels"
            :key="key"
            :value="key"
            :label="String(label)"
          /> </FormSelect></label
      ><ElButton
        class="primary"
        :disabled="busy"
        native-type="submit"
        type="primary"
        >授权成员</ElButton
      >
    </form>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>成员</th>
            <th>角色</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in members" :key="m.id">
            <td>{{ m.display_name }}</td>
            <td>{{ labels[m.role_code] }}</td>
            <td>{{ m.active ? "有效" : "已撤销" }}</td>
            <td>
              <ElButton
                v-if="
                  auth.user?.is_system_admin || auth.can(projectId, 'manage')
                "
                :disabled="busy"
                @click="save(m.user_id, m.role_code, !m.active)"
                native-type="submit"
              >
                {{ m.active ? "撤销授权" : "恢复授权" }}</ElButton
              ><span v-else>只读</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

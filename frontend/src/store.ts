import { defineStore } from "pinia";
import { ref } from "vue";
import { api, json, setCsrfToken } from "./api";

interface Identity {
  user_id: string;
  username: string;
  display_name: string;
  is_system_admin: boolean;
  csrf_token: string;
  memberships: { project_id: string; role_code: string }[];
  demo_mode: boolean;
}
export const useAuth = defineStore("auth", () => {
  const user = ref<Identity>(),
    ready = ref(false);
  async function load() {
    try {
      user.value = await api<Identity>("/auth/me");
      setCsrfToken(user.value.csrf_token);
    } finally {
      ready.value = true;
    }
  }
  async function login(username: string, password: string) {
    const r = await api<Identity>("/auth/login", {
      method: "POST",
      body: json({ username, password }),
    });
    setCsrfToken(r.csrf_token);
    await load();
  }
  function clear() {
    user.value = undefined;
    setCsrfToken("");
  }
  async function logout() {
    await api("/auth/logout", { method: "POST" });
    clear();
  }
  function can(
    projectId: string,
    action: "write" | "review" | "manage" = "write",
  ) {
    const roles =
      action === "write"
        ? ["admin", "editor"]
        : action === "review"
          ? ["admin", "reviewer"]
          : ["admin"];
    return !!user.value?.memberships.some(
      (m) => m.project_id === projectId && roles.includes(m.role_code),
    );
  }
  return { user, ready, load, login, logout, clear, can };
});

export const useCatalog = defineStore("catalog", () => {
  const departments = ref<{ id: string; dept_name: string }[]>([]);
  const users = ref<{ id: string; display_name: string }[]>([]);
  const nodeTypes = ref<{ code: string; display_name: string }[]>([]);
  const loaded = ref(false);
  async function load() {
    if (loaded.value) return;
    const [d, u, n] = await Promise.all([
      api<typeof departments.value>("/departments"),
      api<typeof users.value>("/users"),
      api<typeof nodeTypes.value>("/dictionaries/node-types"),
    ]);
    departments.value = d;
    users.value = u;
    nodeTypes.value = n;
    loaded.value = true;
  }
  return { departments, users, nodeTypes, load };
});

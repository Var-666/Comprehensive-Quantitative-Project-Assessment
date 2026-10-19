const base = "/api/v1";
let csrfToken = "";
export const setCsrfToken = (token: string) => {
  csrfToken = token;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (
    options.method &&
    !["GET", "HEAD"].includes(options.method.toUpperCase()) &&
    csrfToken
  )
    headers.set("X-CSRF-Token", csrfToken);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(base + path, { ...options, headers });
  } catch {
    throw new Error("无法连接后端，请检查 API 服务后重试");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.success) {
    if (response.status === 401 && path !== "/auth/login")
      window.dispatchEvent(new Event("session-expired"));
    const detail = body?.error;
    const fields = detail?.fields
      ?.map((f: { field: string; reason: string }) => `${f.field}: ${f.reason}`)
      .join("；");
    throw new ApiError(
      response.status,
      detail?.code || "INVALID_RESPONSE",
      (detail?.message || "后端响应异常") + (fields ? `（${fields}）` : ""),
      body?.meta?.request_id || "",
    );
  }
  return body.data as T;
}
export const json = (value: unknown) => JSON.stringify(value);
export const versionHeader = (version: number) => ({
  "If-Match": String(version),
});
export const errorMessage = (e: unknown) =>
  e instanceof Error ? e.message : "操作失败";

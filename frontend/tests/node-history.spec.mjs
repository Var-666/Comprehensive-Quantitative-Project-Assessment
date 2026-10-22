import { test, expect } from "@playwright/test";

test("node history shows readable versions, people, local times and field changes", async ({
  page,
}) => {
  await page.goto("/projects");
  await page.getByLabel("账号", { exact: true }).fill("accept-editor");
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "项目管理", exact: true }),
  ).toBeVisible();
  const identity = (await (await page.request.get("/api/v1/auth/me")).json())
    .data;
  const headers = { "X-CSRF-Token": identity.csrf_token };
  const result = await page.request.post("/api/v1/projects", {
    headers,
    data: {
      project_code: "P-HISTORY",
      project_name: "历史记录可读性验收",
      project_status: "draft",
    },
  });
  expect(result.status()).toBe(201);
  const project = (await result.json()).data;
  const [plan] = (
    await (
      await page.request.get(`/api/v1/projects/${project.id}/plan-versions`)
    ).json()
  ).data;
  const payload = {
    plan_version_id: plan.id,
    milestone_code: "HISTORY-N001",
    milestone_name: "图纸评审",
    node_type_code: "设计资料",
    planned_date: "2026-11-01",
  };
  const created = await page.request.post(
    `/api/v1/projects/${project.id}/milestones`,
    { headers, data: payload },
  );
  expect(created.status()).toBe(201);
  const node = (await created.json()).data;
  const updated = await page.request.patch(
    `/api/v1/milestones/${node.id}/plan-item`,
    {
      headers: { ...headers, "If-Match": String(node.row_version) },
      data: {
        ...payload,
        planned_date: "2026-11-03",
        owner_id: identity.user_id,
        change_reason: "等待图纸确认，后延两天",
      },
    },
  );
  expect(updated.status()).toBe(200);
  const submitted = await page.request.post(
    `/api/v1/milestones/${node.id}/actuals`,
    {
      headers,
      data: { completion_flag: false, evidence_ref: "图纸尚未确认" },
    },
  );
  expect(submitted.status()).toBe(201);
  await page.goto(`/milestones?project=${project.id}&plan=${plan.id}`);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "变更历史", exact: true }).click();
  const versions = dialog.locator(".node-version-list");
  await expect(versions).toContainText("V1");
  await expect(versions).toContainText("草稿");
  await expect(versions).toContainText("2026-11-03");
  const logs = dialog.locator(".node-audit-list");
  await expect(logs).toContainText(identity.display_name);
  await expect(logs).toContainText("新增节点");
  await expect(logs).toContainText("提交实际记录");
  await expect(logs).toContainText("尚未完成");
  const submission = logs.locator("li").filter({ hasText: "提交实际记录" });
  await expect(submission).not.toContainText("历史记录");
  await expect(submission).not.toContainText("核实意见");
  const edit = logs.locator("li").filter({ hasText: "修改节点计划" });
  await expect(edit).toContainText("2026-11-01 → 2026-11-03");
  await expect(edit).toContainText(`未填写 → ${identity.display_name}`);
  await expect(edit).toContainText("等待图纸确认，后延两天");
  const detail = (
    await (
      await page.request.get(
        `/api/v1/milestones/${node.id}?plan_version_id=${plan.id}`,
      )
    ).json()
  ).data;
  const event = detail.audit_events.find((e) => e.action === "edit_draft");
  const localTime = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    dateStyle: "short",
    timeStyle: "medium",
    hour12: false,
  }).format(new Date(event.occurred_at));
  await expect(edit.locator("time")).toHaveText(localTime);
  expect((await versions.innerText()) + (await logs.innerText())).not.toMatch(
    /[0-9a-f]{8}-[0-9a-f-]{27,}|before_json|row_version|edit_draft|\d{2}:\d{2}:\d{2}\.\d+\+00:00/,
  );
  for (const width of [1302, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    await dialog.getByRole("button", { name: "变更历史", exact: true }).click();
    expect(
      await dialog
        .locator(".modal-body")
        .evaluate((el) => el.scrollWidth <= el.clientWidth),
    ).toBe(true);
    await page.screenshot({ path: `test-results/node-history-${width}.png` });
  }
});

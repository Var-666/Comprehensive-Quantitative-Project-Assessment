import { test, expect } from "@playwright/test";
import { choose, setChecked } from "./ui-controls.mjs";

async function login(page, username = "accept-editor") {
  await page.goto("/");
  await page.getByLabel("账号", { exact: true }).fill(username);
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "待处理事项", exact: true }),
  ).toBeVisible();
  return (await (await page.request.get("/api/v1/auth/me")).json()).data;
}
async function write(request, token, path, data, version, method = "POST") {
  const response = await request.fetch("/api/v1" + path, {
    method,
    data,
    headers: {
      "X-CSRF-Token": token,
      ...(version ? { "If-Match": String(version) } : {}),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()).data;
}
async function prepare(page, request, identity, code, projectType) {
  const reviewerLogin = await request.post("/api/v1/auth/login", {
    data: {
      username: "accept-reviewer",
      password: process.env.ACCEPTANCE_PASSWORD,
    },
  });
  expect(reviewerLogin.ok()).toBe(true);
  const reviewer = (await (await request.get("/api/v1/auth/me")).json()).data;
  const project = await write(page.request, identity.csrf_token, "/projects", {
    project_code: code,
    project_name: "真实接口工作台验证",
    project_type: projectType,
  });
  await write(
    page.request,
    identity.csrf_token,
    `/projects/${project.id}/members`,
    { user_id: reviewer.user_id, role_code: "reviewer" },
    undefined,
    "PUT",
  );
  const plan = (
    await (
      await page.request.get(`/api/v1/projects/${project.id}/plan-versions`)
    ).json()
  ).data[0];
  const department = (
    await (await page.request.get("/api/v1/departments")).json()
  ).data[0];
  return { project, plan, department, reviewer };
}
async function approve(page, request, identity, reviewer, path, obj) {
  const submitted = await write(
    page.request,
    identity.csrf_token,
    `${path}/${obj.id}/submit-review`,
    undefined,
    obj.row_version,
  );
  return write(
    request,
    reviewer.csrf_token,
    `${path}/${obj.id}/review`,
    { decision: "approved", approval_ref: "隔离浏览器验证独立批准" },
    submitted.row_version,
  );
}
async function addTemplate(page, request, identity, setup, code) {
  const template = await write(
    page.request,
    identity.csrf_token,
    "/action-templates",
    {
      template_code: code,
      version_label: "V1",
      title: code + "资料准备模板",
      node_type_code: "设计资料",
      source_ref: "隔离浏览器测试依据",
      applicability_json: { project_type: setup.project.project_type },
      items: [
        {
          item_code: "01",
          title: code + "资料核对",
          completion_criteria: "凭证和清单经过独立核对",
          materials_required_json: ["图纸清单"],
          default_department_id: setup.department.id,
        },
      ],
    },
  );
  await approve(
    page,
    request,
    identity,
    setup.reviewer,
    "/action-templates",
    template,
  );
  return template;
}

test("real unique auto matching feeds the personal workbench and task navigation at desktop widths", async ({
  page,
  request,
}) => {
  const identity = await login(page);
  const setup = await prepare(
    page,
    request,
    identity,
    "A-WB-LIVE",
    "BROWSER-WB-UNIQUE",
  );
  const template = await addTemplate(
    page,
    request,
    identity,
    setup,
    "AT-WB-UNIQUE",
  );
  const today = (
    await (await page.request.get("/api/v1/workbench/next-actions")).json()
  ).data.as_of;
  const day = new Date(today + "T00:00:00Z");
  day.setUTCDate(day.getUTCDate() - 1);
  const due = day.toISOString().slice(0, 10);
  await page.goto(`/milestones?project=${setup.project.id}`);
  await page
    .getByRole("button", { name: "添加节点", exact: true })
    .first()
    .click();
  const form = page.getByRole("dialog", { name: "新增项目节点", exact: true });
  await form.getByLabel("节点编号", { exact: true }).fill("N-WB");
  await form
    .getByLabel("节点名称 *", { exact: true })
    .fill("工作台自动动作测试节点");
  await choose(form.getByLabel("节点类型 *", { exact: true }), "设计资料");
  await form.getByLabel("计划完成日期 *", { exact: true }).fill(due);
  await form.getByLabel("计划完成日期 *", { exact: true }).press("Tab");
  await form
    .getByLabel("日期依据说明", { exact: true })
    .fill("隔离测试日期依据");

  await form.getByRole("button", { name: "保存节点", exact: true }).click();
  await expect(form).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '节点配置结果', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '查看已关联动作', exact: true }).click();
  const detail = page.getByRole("dialog").first();
  await expect(detail).toContainText("系统已自动匹配");
  await expect(detail).toContainText("V1");
  await expect(detail).toContainText(setup.department.dept_name);
  await expect(detail).toContainText("凭证和清单经过独立核对");
  await expect(detail).toContainText("系统自动匹配（新建节点）");
  await detail
    .getByRole("button", { name: "返回节点列表", exact: true })
    .last()
    .click();
  const rule = await write(
    page.request,
    identity.csrf_token,
    "/reminder-rules",
    {
      rule_code: "RR-WB-LIVE",
      version_label: "V1",
      node_type_code: "设计资料",
      source_ref: "隔离验证触发规则",
      days_before: 0,
      day_basis: "calendar_day",
      recipient_role_code: "admin",
      catch_up_days: 0,
    },
  );
  await approve(
    page,
    request,
    identity,
    setup.reviewer,
    "/reminder-rules",
    rule,
  );
  const currentPlan = (
    await (
      await page.request.get(
        `/api/v1/projects/${setup.project.id}/plan-versions`,
      )
    ).json()
  ).data[0];
  await write(
    request,
    setup.reviewer.csrf_token,
    `/plan-versions/${currentPlan.id}/activate`,
    { approval_ref: "独立确认测试计划生效" },
    currentPlan.row_version,
  );
  await write(page.request, identity.csrf_token, "/reminder-jobs/run", {
    as_of: due,
    project_ids: [setup.project.id],
  });
  const task = (
    await (
      await page.request.get(`/api/v1/tasks?project_id=${setup.project.id}`)
    ).json()
  ).data.items[0];
  await write(
    page.request,
    identity.csrf_token,
    `/tasks/${task.id}`,
    { assignee_id: identity.user_id, reason: "明确分派给当前登录人" },
    task.row_version,
    "PATCH",
  );
  await page.goto("/");
  const guide = page.locator(".workbench-guide");
  await expect(guide.locator(".workbench-primary")).toContainText(
    setup.project.project_code,
  );
  await expect(guide.locator(".workbench-primary")).toContainText(
    template.items[0].title,
  );
  await expect(
    guide.getByRole("link", { name: "处理我的任务 →", exact: true }),
  ).toBeVisible();
  await expect(guide.locator(".workbench-secondary article")).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "新建项目", exact: true }),
  ).toHaveCount(0);
  await expect(guide.locator(".workbench-path")).toHaveCount(0);
  await expect(guide).not.toContainText("业务阶段：");
  await expect(guide).not.toContainText("推荐原因：");
  await expect(guide).not.toContainText("依据实际业务状态和当前账号权限");
  await expect(guide.locator(".workbench-primary time")).toHaveAttribute(
    "datetime",
    due,
  );
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      await page
        .locator("img")
        .evaluateAll((images) =>
          images.every((img) => img.complete && img.naturalWidth > 0),
        ),
    ).toBe(true);
    expect(
      await guide
        .locator("p,h2,h3")
        .evaluateAll((elements) =>
          elements.every(
            (el) =>
              el.scrollWidth <= el.clientWidth + 1 &&
              el.scrollHeight <= el.clientHeight + 1,
          ),
        ),
    ).toBe(true);
    const before = await guide.boundingBox();
    const stats = await page.locator(".overview-stats").boundingBox();
    expect(before.y + before.height).toBeLessThanOrEqual(stats.y);
    await expect(
      page.getByRole("heading", { name: "节点履约趋势", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "重点项目进展", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `test-results/workbench-compact-${width}.png`,
      fullPage: true,
    });
  }
  await guide
    .getByRole("link", { name: "处理我的任务 →", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "任务执行反馈", exact: true }),
  ).toContainText(template.items[0].title);
});

test("conflicting templates require a human choice and readonly users have no write entry", async ({
  page,
  request,
}) => {
  const identity = await login(page);
  const setup = await prepare(
    page,
    request,
    identity,
    "A-WB-CONFLICT",
    "BROWSER-WB-CONFLICT",
  );
  const first = await addTemplate(
    page,
    request,
    identity,
    setup,
    "AT-WB-CONFLICT-A",
  );
  const second = await addTemplate(
    page,
    request,
    identity,
    setup,
    "AT-WB-CONFLICT-B",
  );
  const node = await write(
    page.request,
    identity.csrf_token,
    `/projects/${setup.project.id}/milestones`,
    {
      plan_version_id: setup.plan.id,
      milestone_code: "N-CONFLICT",
      milestone_name: "候选人工确认节点",
      node_type_code: "设计资料",
      planned_date: "2026-10-26",
      source_ref: "测试计划来源",
      change_reason: "验证多模板候选",
    },
  );
  expect(node.action_matching.status).toBe("conflict");
  await page.goto(
    `/milestones?project=${setup.project.id}&plan=${setup.plan.id}&node=${node.id}`,
  );
  const detail = page.getByRole("dialog").first();
  await expect(detail).toContainText("存在多个候选待确认");
  await detail
    .getByRole("button", { name: "关联动作模板", exact: true })
    .click();
  const picker = page.getByRole("region", {
    name: "选择标准动作模板",
    exact: true,
  });
  await expect(picker).toContainText(first.title);
  await expect(picker).toContainText(second.title);
  await expect(
    picker.getByRole("button", { name: "保存关联配置", exact: true }),
  ).toBeDisabled();
  await setChecked(picker.getByRole("checkbox").first(), true);
  await picker
    .getByRole("button", { name: "保存关联配置", exact: true })
    .click();
  await expect(picker).toHaveCount(0);
  await expect(detail).toContainText("已人工关联");
  await expect(detail).toContainText("人工关联（含历史配置）");
  await detail
    .getByRole("button", { name: "关闭", exact: true })
    .last()
    .click();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await login(page, "accept-viewer");
  const guide = page.locator(".workbench-guide");
  await expect(guide.locator(".workbench-primary")).toContainText(
    "请由项目编辑或配置管理员",
  );
  await expect(guide.locator(".workbench-primary a.button")).toHaveCount(0);
});

test("empty workbench routes to project management without creating projects on the overview", async ({
  page,
}) => {
  await login(page);
  await page.route("**/api/v1/workbench/next-actions", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          as_of: "2026-10-22",
          projects: [],
          secondary: [],
          primary: {
            recommendation_id: "no-projects",
            project_id: null,
            project_code: null,
            project_name: null,
            action_type: "create_project",
            business_type: "项目准备",
            title: "创建第一个项目",
            description: "先创建项目，再录入节点计划与标准动作。",
            reason_code: "NO_ACCESSIBLE_PROJECTS",
            priority: 30,
            target_path: "/projects",
            button_label: "新建项目",
            actionable: true,
            blocked_reason: "",
            stage: "项目准备",
            status: "项目准备",
            due_date: null,
          },
        },
        meta: {},
      }),
    }),
  );
  await page.goto("/");
  const guide = page.locator(".workbench-guide");
  await expect(guide).toContainText("暂无可访问项目");
  await expect(
    page.getByRole("button", { name: "新建项目", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".workbench-path")).toHaveCount(0);
  await guide
    .getByRole("link", { name: "进入项目管理 →", exact: true })
    .click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "新建项目", exact: true }),
  ).toBeVisible();
});

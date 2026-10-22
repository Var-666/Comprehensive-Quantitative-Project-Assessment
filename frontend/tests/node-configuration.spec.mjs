import { test, expect } from "@playwright/test";
import { choose, setChecked } from "./ui-controls.mjs";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

async function write(request, identity, url, data, version, method = "POST") {
  const response = await request.fetch("/api/v1" + url, {
    method,
    data,
    headers: {
      "X-CSRF-Token": identity.csrf_token,
      ...(version ? { "If-Match": String(version) } : {}),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()).data;
}
async function setup(page, request, tag) {
  await page.goto("/milestones");
  await page.getByLabel("账号", { exact: true }).fill("accept-editor");
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "项目节点管理", exact: true }),
  ).toBeVisible();
  const identity = (await (await page.request.get("/api/v1/auth/me")).json())
    .data;
  await request.post("/api/v1/auth/login", {
    data: {
      username: "accept-reviewer",
      password: process.env.ACCEPTANCE_PASSWORD,
    },
  });
  const reviewer = (await (await request.get("/api/v1/auth/me")).json()).data;
  const project = await write(page.request, identity, "/projects", {
    project_code: `P-CFG-${tag}`,
    project_name: "节点配置引导验收",
    project_type: tag,
  });
  await write(
    page.request,
    identity,
    `/projects/${project.id}/members`,
    { user_id: reviewer.user_id, role_code: "reviewer" },
    undefined,
    "PUT",
  );
  const [plan] = (
    await (
      await page.request.get(`/api/v1/projects/${project.id}/plan-versions`)
    ).json()
  ).data;
  return { identity, reviewer, project, plan };
}
async function approve(page, request, setup, route, obj) {
  const pending = await write(
    page.request,
    setup.identity,
    `${route}/${obj.id}/submit-review`,
    undefined,
    obj.row_version,
  );
  return write(
    request,
    setup.reviewer,
    `${route}/${obj.id}/review`,
    { decision: "approved", approval_ref: "独立配置验收" },
    pending.row_version,
  );
}
async function template(
  page,
  request,
  setup,
  code,
  approved = true,
  nodeType = "合同签订",
) {
  const obj = await write(page.request, setup.identity, "/action-templates", {
    template_code: code,
    version_label: "V1",
    title: `准备清单 ${code}`,
    node_type_code: nodeType,
    applicability_json: { project_type: setup.project.project_type },
    source_ref: "经核对的业务要求",
    items: [
      {
        item_code: "01",
        title: "核对资料",
        completion_criteria: "经独立核对的资料清单",
        materials_required_json: ["资料清单"],
      },
    ],
  });
  if (approved) await approve(page, request, setup, "/action-templates", obj);
  return obj;
}
async function createInUi(page, name, tracking = false) {
  await page
    .getByRole("button", { name: "添加节点", exact: true })
    .first()
    .click();
  const form = page.getByRole("dialog", { name: "新增项目节点", exact: true });
  await form.getByLabel("节点名称 *", { exact: true }).fill(name);
  await choose(form.getByLabel("节点类型 *", { exact: true }), "合同签订");
  await form.getByLabel("计划完成日期 *", { exact: true }).fill("2026-11-20");
  await form.getByLabel("计划完成日期 *", { exact: true }).press("Tab");
  await form
    .getByLabel("日期依据说明", { exact: true })
    .fill("经核对的项目计划");
  if (tracking)
    await setChecked(
      form.getByRole("checkbox", { name: /仅进行节点计划/ }),
      true,
    );
  await form.getByRole("button", { name: "保存节点", exact: true }).click();
  await expect(form).toHaveCount(0);
  const detail = page.getByRole("dialog");
  await expect(
    detail.getByRole("heading", { name: "节点配置结果", exact: true }),
  ).toBeVisible();
  return detail;
}

test("saved node opens configuration results, checks rules and continues with persistent tracking-only choice", async ({
  page,
  request,
}) => {
  const s = await setup(page, request, "READY");
  await template(page, request, s, "AT-CFG-READY");
  await page.goto(`/milestones?project=${s.project.id}&plan=${s.plan.id}`);
  let detail = await createInUi(page, "阶段准备");
  const config = detail.getByRole("region", {
    name: "节点配置检查",
    exact: true,
  });
  await expect(config).toContainText(
    "已自动关联【准备清单 AT-CFG-READY V1】，共 1 项标准动作",
  );
  await expect(config).toContainText("暂无已批准提醒规则");
  const rule = await write(page.request, s.identity, "/reminder-rules", {
    rule_code: "RR-CFG-READY",
    version_label: "V1",
    node_type_code: "合同签订",
    source_ref: "业务核定规则",
    days_before: 7,
    day_basis: "calendar_day",
    recipient_role_code: "admin",
  });
  await approve(page, request, s, "/reminder-rules", rule);
  await detail
    .getByRole("button", { name: "重新检查配置", exact: true })
    .click();
  await expect(config).toContainText("配置就绪");
  await expect(page.locator(".milestone-list-table")).toContainText("配置就绪");
  await expect(config).toContainText("尚未批准");
  await detail
    .getByRole("button", { name: "查看提醒规则", exact: true })
    .click();
  await expect(config).toContainText("2026-11-13");
  await expect(config).toContainText("1 个可用接收人");
  await detail
    .getByRole("button", { name: "查看已关联动作", exact: true })
    .click();
  const actionCard = detail.getByRole("article", {
    name: "核对资料",
    exact: true,
  });
  await expect(actionCard.locator(".linked-action-status")).toHaveText(
    "已关联",
  );
  await expect(actionCard).toContainText("经独立核对的资料清单");
  await expect(actionCard.locator(".linked-action-materials")).toContainText(
    "资料清单",
  );
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    await detail.getByRole("button", { name: "配置检查", exact: true }).click();
    expect(
      await detail
        .locator(".modal-body")
        .evaluate((e) => e.scrollWidth <= e.clientWidth),
    ).toBe(true);
    const sectionGaps = await detail.locator(".modal-body").evaluate((body) => {
      const sections = [
        ...body.querySelectorAll(
          ":scope > .form-section, :scope > div[data-node-section] > .form-section",
        ),
      ];
      return sections
        .slice(1)
        .map(
          (section, index) =>
            section.getBoundingClientRect().top -
            sections[index].getBoundingClientRect().bottom,
        );
    });
    expect(sectionGaps.length).toBeGreaterThan(3);
    for (const gap of sectionGaps) expect(gap).toBeCloseTo(16, 0);
    await page.screenshot({
      path: `test-results/node-configuration-${width}.png`,
    });
    await detail.getByRole("button", { name: "标准动作", exact: true }).click();
    await actionCard.scrollIntoViewIfNeeded();
    expect(
      await actionCard.evaluate((e) => e.scrollWidth <= e.clientWidth),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/node-action-cards-${width}.png`,
    });
  }
  await detail
    .getByRole("button", { name: "继续添加节点", exact: true })
    .click();
  const next = page.getByRole("dialog", { name: "新增项目节点", exact: true });
  await expect(next.getByLabel("节点名称 *", { exact: true })).toHaveValue("");
  await next.getByLabel("节点名称 *", { exact: true }).fill("只记录时间");
  await choose(next.getByLabel("节点类型 *", { exact: true }), "合同签订");
  await next.getByLabel("计划完成日期 *", { exact: true }).fill("2026-11-21");
  await next.getByLabel("计划完成日期 *", { exact: true }).press("Tab");
  await setChecked(
    next.getByRole("checkbox", { name: /仅进行节点计划/ }),
    true,
  );
  await next.getByRole("button", { name: "保存节点", exact: true }).click();
  detail = page.getByRole("dialog");
  await expect(
    detail.getByRole("region", { name: "节点配置检查" }),
  ).toContainText("仅时间记录");
  await detail
    .getByRole("button", { name: "返回节点列表", exact: true })
    .click();
  await page.reload();
  await choose(page.getByLabel("配置状态", { exact: true }), "tracking_only");
  await expect(page.locator(".milestone-list-table tbody tr")).toHaveCount(1);
  await expect(page.locator(".milestone-list-table")).toContainText(
    "只记录时间",
  );
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "节点配置检查" }),
  ).toContainText("不生成准备任务和提醒");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "标准动作", exact: true })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "关联动作模板", exact: true }),
  ).toHaveCount(0);
  await expect(
    page
      .getByRole("dialog")
      .getByRole("link", { name: "维护标准动作配置 →", exact: true }),
  ).toHaveCount(0);
  const nodesUrl = page.url();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "关闭", exact: true })
    .last()
    .click();
  await choose(page.getByLabel("配置状态", { exact: true }), "");
  const linkedRow = page
    .locator(".milestone-list-table tbody tr")
    .filter({ hasText: "阶段准备" });
  await linkedRow.getByRole("button", { name: "编辑", exact: true }).click();
  const editor = page.getByRole("dialog", {
    name: "编辑节点计划草稿",
    exact: true,
  });
  await setChecked(
    editor.getByRole("checkbox", { name: /仅进行节点计划/ }),
    true,
  );
  await editor
    .getByLabel("变更原因 *", { exact: true })
    .fill("本节点仅记录进展，保留原动作快照");
  await editor.getByRole("button", { name: "保存节点", exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(linkedRow).toContainText("仅时间记录");
  await linkedRow
    .getByRole("button", { name: "查看详情", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "标准动作", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("已保存快照，暂不执行");
  await expect(page.getByRole("dialog")).toContainText("经独立核对的资料清单");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "关闭", exact: true })
    .last()
    .click();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await page.getByLabel("账号", { exact: true }).fill("accept-reviewer");
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "退出登录", exact: true }),
  ).toBeVisible();
  await page.goto(nodesUrl);
  await page
    .getByRole("button", { name: "查看详情", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "前往计划审批", exact: true }).click();
  const approval = page.getByRole("dialog", {
    name: "批准计划生效",
    exact: true,
  });
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await approval
    .getByLabel("批准依据 *", { exact: true })
    .fill("整版节点与配置已独立核对");
  await approval
    .getByRole("button", { name: "批准计划生效", exact: true })
    .click();
  await expect(approval).toHaveCount(0);
  const [effective] = (
    await (
      await page.request.get(`/api/v1/projects/${s.project.id}/plan-versions`)
    ).json()
  ).data;
  expect(effective.status).toBe("effective");
});

test("conflicting templates stay unselected, can be chosen inline and failed checks retry", async ({
  page,
  request,
}) => {
  const s = await setup(page, request, "CONFLICT");
  await template(page, request, s, "AT-CFG-A");
  await template(page, request, s, "AT-CFG-B");
  await page.goto(`/milestones?project=${s.project.id}&plan=${s.plan.id}`);
  const detail = await createInUi(page, "人工确认模板");
  await expect(
    detail.getByRole("region", { name: "节点配置检查" }),
  ).toContainText("找到 2 个适用模板");
  await page.route("**/api/v1/milestones/*/suggested-actions?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { message: "候选模板读取暂不可用" } }),
    }),
  );
  await detail
    .getByRole("button", { name: "选择动作模板", exact: true })
    .click();
  const picker = detail.getByRole("region", {
    name: "选择标准动作模板",
    exact: true,
  });
  await expect(picker.getByRole("alert")).toContainText("候选模板读取暂不可用");
  await expect(
    picker.getByRole("button", { name: "保存关联配置" }),
  ).toBeDisabled();
  await page.unroute("**/api/v1/milestones/*/suggested-actions?*");
  await picker
    .getByRole("button", { name: "重试动作模板", exact: true })
    .click();
  await expect(picker.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(picker).toContainText("适用项目类型：CONFLICT");
  await expect(
    picker.getByRole("button", { name: "保存关联配置" }),
  ).toBeDisabled();
  await picker
    .getByRole("button", { name: "使用这套模板", exact: true })
    .first()
    .click();
  await picker.getByRole("button", { name: "保存关联配置" }).click();
  await expect(picker).toHaveCount(0);
  await expect(
    detail.getByRole("region", { name: "节点配置检查" }),
  ).toContainText("已人工关联");
  await page.route("**/api/v1/milestones/*?plan_version_id=*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { message: "配置检查暂不可用" } }),
    }),
  );
  await detail
    .getByRole("button", { name: "重新检查配置", exact: true })
    .click();
  await expect(detail.getByRole("alert")).toContainText("配置检查暂不可用");
  await page.unroute("**/api/v1/milestones/*?plan_version_id=*");
  await detail
    .getByRole("button", { name: "重试配置检查", exact: true })
    .click();
  await expect(detail.getByRole("alert")).toHaveCount(0);
});

test("Excel preview does not write nodes and commit shows real automatic, pending and tracking results", async ({
  page,
  request,
}) => {
  const s = await setup(page, request, "IMPORT");
  await template(page, request, s, "AT-CFG-IMPORT");
  await template(page, request, s, "AT-CFG-PENDING", false, "开工准备");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "node-configuration-"));
  const file = path.join(dir, "configuration.xlsx");
  try {
    execFileSync("../.venv/bin/python", [
      "-c",
      `from openpyxl import Workbook
import sys
w=Workbook();s=w.active;s.title='nodes'
s.append(['项目编号','节点编号','节点名称','节点类型','计划完成日期','责任部门','责任人','日期依据','仅时间记录'])
for code,name,kind,tracking in [('N-01','自动配置','合同签订','否'),('N-02','待批准模板','开工准备','否'),('N-03','仅记录','合同签订','是')]:
 s.append([sys.argv[2],code,name,kind,'2026-11-20',None,None,'核定计划',tracking])
w.save(sys.argv[1])`,
      file,
      s.project.project_code,
    ]);
    await page.goto(
      `/imports?target=milestones&project=${s.project.id}&plan=${s.plan.id}`,
    );
    await page.locator(".el-upload input[type=file]").setInputFiles(file);
    await page.getByLabel("工作表名称").fill("nodes");
    await page.getByLabel("表头行号").fill("1");
    await page.getByLabel("tracking_only", { exact: true }).fill("仅时间记录");
    await page.getByRole("button", { name: "下一步：校验预览" }).click();
    const summary = page.locator(".import-matching-summary");
    await expect(summary).toContainText("可自动匹配 1 个");
    await expect(summary).toContainText("模板待批准 1 个");
    await expect(summary).toContainText("仅时间记录 1 个");
    const before = (
      await (
        await page.request.get(
          `/api/v1/projects/${s.project.id}/milestones?plan_version_id=${s.plan.id}`,
        )
      ).json()
    ).data;
    expect(before.total).toBe(0);
    await setChecked(
      page.getByRole("checkbox", { name: /我已核对预览/ }),
      true,
    );
    await page.getByRole("button", { name: "确认导入", exact: true }).click();
    await expect(summary).toContainText("已自动关联 1 个");
    await expect(page.locator(".import-workspace")).toContainText("写入 3 行");
    const rows = page.locator(".preview-table tbody tr");
    await expect(rows.filter({ hasText: "N-01" })).toContainText(
      "系统已自动匹配",
    );
    await expect(rows.filter({ hasText: "N-02" })).toContainText(
      "模板待业务确认",
    );
    await expect(rows.filter({ hasText: "N-02" })).toContainText(
      "动作模板待批准",
    );
    await expect(rows.filter({ hasText: "N-03" })).toContainText("仅时间记录");
    await page.getByRole("button", { name: "完成", exact: true }).click();
    await expect(page.locator(".milestone-list-table tbody tr")).toHaveCount(3);
    await choose(
      page.getByLabel("配置状态", { exact: true }),
      "actions_approval",
    );
    await expect(page.locator(".milestone-list-table tbody tr")).toHaveCount(1);
    await expect(page.locator(".milestone-list-table")).toContainText("N-02");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

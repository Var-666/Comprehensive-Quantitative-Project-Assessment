import { test, expect } from '@playwright/test';

async function login(page) {
  await page.goto('/projects');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '项目管理', exact: true })).toBeVisible();
}
const confirmBox = page => page.getByRole('dialog', { name: '放弃未保存的修改？', exact: true });
const navigate = (page, name) => page.getByRole('link', { name, exact: true }).evaluate(link => link.click());

test('drawers protect dirty changes on cancel, Escape, header, refresh and route leave; failed saves retain input', async ({ page }) => {
  await login(page);
  const open = () => page.getByRole('button', { name: '新建项目', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: '新建项目', exact: true });
  await open();
  for (const width of [1440, 1024, 760]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(async () => {
      const box = await page.locator('.form-drawer:visible').boundingBox();
      return box.x >= 0 && box.y >= 0 && box.x + box.width <= width + 1 && box.height <= 901;
    }).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.mouse.click(10, 120);
  await expect(drawer).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  await open();
  const name = drawer.getByLabel('项目名称 *', { exact: true });
  await name.fill('修改后恢复'); await name.fill('');
  await drawer.getByRole('button', { name: '取消', exact: true }).click();
  await expect(confirmBox(page)).toHaveCount(0); await expect(drawer).toHaveCount(0);
  await open(); await name.fill('尚未保存的项目');
  const unloadCancelled = await page.evaluate(() => !window.dispatchEvent(new Event('beforeunload', { cancelable: true })));
  expect(unloadCancelled).toBe(true);
  for (const close of [
    () => drawer.getByRole('button', { name: '取消', exact: true }).click(),
    () => page.keyboard.press('Escape'),
    () => drawer.getByRole('button', { name: '关闭', exact: true }).click(),
    () => navigate(page, '项目总览'),
  ]) {
    await close(); await expect(confirmBox(page)).toBeVisible();
    await confirmBox(page).getByRole('button', { name: '继续编辑', exact: true }).click();
    await expect(confirmBox(page)).toHaveCount(0);
    await expect(name).toHaveValue('尚未保存的项目'); await expect(page).toHaveURL(/\/projects$/);
  }
  await drawer.getByLabel('项目编号 *', { exact: true }).fill('P-POPUP-UX');
  let release; const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/v1/projects', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await gate;
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'UX_FAILURE', message: '保存暂时失败，请重试', fields: [] }, meta: {} }) });
  });
  const saving = page.waitForRequest(r => r.method() === 'POST' && new URL(r.url()).pathname.endsWith('/projects'));
  await drawer.getByRole('button', { name: '保存并进入详情', exact: true }).click(); await saving;
  await expect(drawer.getByRole('button', { name: '关闭', exact: true })).toBeDisabled();
  await page.keyboard.press('Escape'); await expect(drawer).toBeVisible(); release();
  await expect(drawer.getByRole('alert')).toContainText('保存暂时失败');
  await expect(name).toHaveValue('尚未保存的项目');
  await drawer.getByRole('button', { name: '取消', exact: true }).click();
  await confirmBox(page).getByRole('button', { name: '继续编辑', exact: true }).click();
    await expect(confirmBox(page)).toHaveCount(0);
  await page.unroute('**/api/v1/projects');
  await drawer.getByRole('button', { name: '保存并进入详情', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('P-POPUP-UX');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: '编辑项目', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '编辑项目', exact: true });
  await editor.getByLabel('项目名称 *', { exact: true }).fill('放弃的修改');
  await navigate(page, '项目总览');
  await confirmBox(page).getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(await page.evaluate(() => window.dispatchEvent(new Event('beforeunload', { cancelable: true })))).toBe(true);
});

test('success Toast expires without shifting content and repeats; failures remain inline', async ({ page }) => {
  await login(page); await page.getByRole('link', { name: '量化评估', exact: true }).click();
  await page.getByRole('button', { name: '评价明细', exact: true }).first().click();
  const heading = page.getByRole('heading', { level: 1 });
  const y = (await heading.boundingBox()).y;
  const save = page.getByRole('button', { name: '保存评价快照', exact: true });
  for (let i = 0; i < 2; i++) {
    await save.click();
    await expect(page.getByRole('status')).toContainText('已保存评价快照');
    expect((await heading.boundingBox()).y).toBe(y);
    await expect(page.getByRole('status')).toHaveCount(0, { timeout: 6500 });
  }
  await page.route('**/api/v1/projects/*/metric-snapshots', route => route.request().method() === 'POST' ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'UX_FAILURE', message: '快照暂时无法保存', fields: [] }, meta: {} }) }) : route.continue());
  await save.click();
  await expect(page.getByRole('alert')).toContainText('快照暂时无法保存');
  await expect(page.getByRole('status')).toHaveCount(0);
});

test('import page validates route context and protects mappings before returning', async ({ page }) => {
  await login(page);
  await page.goto('/imports?target=milestones');
  await expect(page.getByRole('alert')).toContainText('缺少项目编辑权限或草稿计划');
  await expect(page.getByText('导入条件不满足', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '下一步：校验预览', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '返回来源页面', exact: true }).click();
  await page.getByRole('button', { name: '导入 Excel', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Excel 数据导入', exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByLabel('工作表名称').fill('changed');
  await page.getByRole('button', { name: '返回来源页面', exact: true }).click();
  await confirmBox(page).getByRole('button', { name: '继续编辑', exact: true }).click();
    await expect(confirmBox(page)).toHaveCount(0);
  await expect(page.getByLabel('工作表名称')).toHaveValue('changed');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await confirmBox(page).getByRole('button', { name: '放弃修改', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
});

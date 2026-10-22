import { test, expect } from '@playwright/test';

async function login(page) {
  await page.goto('/');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '项目总体概览', exact: true })).toBeVisible();
  await expect(page.locator('.overview-projects tbody tr')).toHaveCount(3);
}

test('overview keeps every project fact in a compact single-line row', async ({ page }) => {
  await login(page);
  const asOf = await page.evaluate(() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()));
  const projects = (await (await page.request.get(`/api/v1/metrics/dashboard?as_of=${asOf}`)).json()).data.projects;
  const table = page.locator('.overview-projects table');
  await expect(table.locator('th')).toHaveCount(9);
  for (const width of [1440, 1223, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    const rows = await table.locator('tbody tr').evaluateAll(items => items.map(row => ({
      cells: [...row.cells].map(cell => cell.textContent.trim()),
      height: row.getBoundingClientRect().height,
      singleLine: [...row.cells].every(cell => getComputedStyle(cell).whiteSpace === 'nowrap'),
    })));
    expect(rows.every(row => row.height <= 44 && row.singleLine)).toBe(true);
    expect(rows.map(row => row.cells)).toEqual(projects.map(p => [
      p.project_code, p.project_name, p.owner_name || '未指定', String(p.milestone_count),
      p.counts ? String(p.counts.verified_completed) : '无生效计划', p.current_plan_label || '尚无生效计划',
      p.next_milestone?.milestone_name || '—', p.next_milestone?.planned_date || '—',
      p.project_status === 'active' ? '进行中' : '草稿',
    ]));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const wrap = page.locator('.overview-projects .table-wrap');
    await wrap.evaluate(el => { el.scrollLeft = el.scrollWidth; });
    await expect(table.getByRole('columnheader', { name: '状态', exact: true })).toBeInViewport();
    await wrap.evaluate(el => { el.scrollLeft = 0; });
    if (width === 1223) await page.screenshot({ path: 'test-results/overview-single-line-1223.png', animations: 'disabled' });
  }
});

test('sidebar collapses across navigation while names, active state and modal alignment remain usable', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  const screens = [
    ['项目总览', '项目总体概览'], ['项目管理', '项目管理'], ['节点管理', '项目节点管理'],
    ['标准动作', '标准动作配置'], ['提醒与待办', '提醒与待办'], ['量化评估', '项目量化评估'],
    ['AI 智能分析', 'AI 阶段报告工作台'], ['系统设置', '系统设置'],
  ];
  await expect(page.locator('.sidebar-foot')).toHaveCount(0);
  async function expectSettingsAtBottom() {
    const sidebar = await page.locator('.sidebar').boundingBox();
    const settings = await page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '系统设置', exact: true }).boundingBox();
    const gap = sidebar.y + sidebar.height - settings.y - settings.height;
    expect(gap).toBeGreaterThanOrEqual(0);
    expect(gap).toBeLessThanOrEqual(16);
  }
  for (const width of [1223, 1024, 900]) {
    await page.setViewportSize({ width, height: 984 });
    await expectSettingsAtBottom();
    const collapse = page.getByRole('button', { name: '收起侧边栏', exact: true });
    await expect(collapse).toBeVisible();
    await collapse.focus(); await collapse.press('Enter');
    await expect(page.getByRole('button', { name: '展开侧边栏', exact: true })).toHaveAttribute('aria-expanded', 'false');
    await expectSettingsAtBottom();
    for (const [name, heading] of screens) {
      const menu = page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name, exact: true });
      await expect(menu).toHaveAttribute('title', name);
      await menu.click();
      // Wait for route completion: the workbench loads its component asynchronously.
      await expect(menu).toHaveClass(/active/, { timeout: 15000 });
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
      await page.waitForLoadState('networkidle');
      const layout = await page.evaluate(() => ({
        sidebar: document.querySelector('.sidebar').getBoundingClientRect().toJSON(),
        main: document.querySelector('.main-shell').getBoundingClientRect().toJSON(),
        overflow: document.documentElement.scrollWidth > innerWidth,
      }));
      expect(layout.sidebar.width).toBe(72);
      expect(layout.sidebar.height).toBe(984);
      expect(layout.main.x).toBe(72);
      expect(layout.overflow).toBe(false);
      await expect(page.locator('.sidebar .nav-label:visible')).toHaveCount(0);
      if (width === 1223 && name === '项目总览') await page.screenshot({ path: 'test-results/sidebar-collapsed-1223.png', animations: 'disabled' });
    }
    await page.getByRole('button', { name: '设置 / 更换 Key', exact: true }).click();
    const dialog = page.getByRole('dialog');
    const bounds = await dialog.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(72);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    expect(await page.locator('.ui-workspace-overlay').evaluate(el => el.getBoundingClientRect().left)).toBe(72);
    await expect(dialog.getByLabel('新的 API Key *')).toHaveAttribute('type', 'password');
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByRole('button', { name: '展开侧边栏', exact: true }).click();
    await expect(page.getByRole('button', { name: '收起侧边栏', exact: true })).toHaveAttribute('aria-expanded', 'true');
    expect((await page.locator('.sidebar').boundingBox()).width).toBe(width <= 900 ? 205 : 236);
    expect((await page.locator('.main-shell').boundingBox()).x).toBe(width <= 900 ? 205 : 236);
    await expectSettingsAtBottom();
  }
  expect(errors).toEqual([]);
});

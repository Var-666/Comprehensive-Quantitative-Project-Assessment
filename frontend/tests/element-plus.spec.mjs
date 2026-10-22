import { test, expect } from '@playwright/test';

async function login(page) {
  await page.goto('/tasks');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '提醒与待办', exact: true })).toBeVisible();
  await page.waitForLoadState('networkidle');
}
async function contained(locator) {
  const box = await locator.boundingBox(), viewport = locator.page().viewportSize();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1);
}

test('toolbar wraps the complete filter group without clipping task controls', async ({ page }) => {
  await login(page);
  for (const width of [1600, 1440, 1366, 1284, 1280, 1100, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    for (const name of ['通知队列', '执行任务']) {
      const loaded = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/${name === '执行任务' ? 'tasks' : 'notifications'}` && response.status() === 200);
      await page.getByRole('button', { name, exact: true }).click();
      await loaded;
      await expect(page.getByRole('button', { name: '查询工作', exact: true })).toBeEnabled();
      await page.waitForLoadState('networkidle');
      const layout = await page.locator('.workbench-toolbar').evaluate(toolbar => {
        const tabs = toolbar.querySelector('.tabs').getBoundingClientRect();
        const form = toolbar.querySelector('form');
        const filters = form.getBoundingClientRect();
        const children = [...form.children].map(el => {
          const box = el.getBoundingClientRect();
          return { center: box.y + box.height / 2, left: box.left, right: box.right, clipped: el.scrollWidth > el.clientWidth + 1 };
        });
        return { tabs: { top: tabs.top, bottom: tabs.bottom }, filters: { top: filters.top, bottom: filters.bottom }, children, right: toolbar.getBoundingClientRect().right };
      });
      // The query and "assigned to me" control belong to the same filter row.
      // Checking only page overflow misses a squeezed checkbox and an orphaned query button.
      const centers = layout.children.map(child => child.center);
      expect(Math.max(...centers) - Math.min(...centers), `${width}px ${name}: filter row alignment`).toBeLessThanOrEqual(1);
      expect(layout.children.every(child => !child.clipped && child.right <= layout.right + 1)).toBe(true);
      expect(layout.filters.top >= layout.tabs.bottom - 1 || Math.abs(layout.filters.top - layout.tabs.top) <= 1).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (name === '执行任务' && [1284, 1024].includes(width)) {
        await page.screenshot({ path: `test-results/element-toolbar-tasks-${width}.png`, animations: 'disabled' });
      }
    }
  }
});

test('Element project search and status filters preserve API values and accessible menus', async ({ page }) => {
  await login(page);
  const projects = (await (await page.request.get('/api/v1/projects')).json()).data.items;
  const project = projects.find(p => p.project_code === 'P-H028');
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    const select = page.getByRole('combobox', { name: '筛选项目', exact: true });
    await page.locator('.el-select').filter({ has: select }).click();
    await select.fill('H028');
    await contained(page.locator('.el-popper.project-element-popper:visible'));
    await page.getByRole('option', { name: /P-H028/ }).click();
    const status = page.getByRole('combobox', { name: '工作状态', exact: true });
    await page.locator('.el-select').filter({ has: status }).click();
    await page.getByRole('option', { name: '草稿', exact: true }).click();
    const request = page.waitForRequest(r => r.url().includes('/api/v1/notifications?'));
    await page.getByRole('button', { name: '查询工作', exact: true }).click();
    const query = new URL((await request).url()).searchParams;
    expect(query.get('project_id')).toBe(project.id);
    expect(query.get('status')).toBe('draft');
    await page.waitForLoadState('networkidle');
    await page.locator('.el-select').filter({ has: select }).click(); await select.press('Escape');
    await expect(page.locator('.el-popper.project-element-popper:visible')).toHaveCount(0);
    await page.locator('.el-select').filter({ has: select }).click();
    await expect(page.getByRole('listbox')).toBeVisible();
    await page.getByRole('heading', { name: '提醒与待办', exact: true }).click();
    await expect(page.locator('.el-popper.project-element-popper:visible')).toHaveCount(0);
    await page.screenshot({ path: `test-results/element-tasks-${width}.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/v1/notifications?*', async route => { await gate; await route.continue(); });
  const pending = page.waitForRequest(r => r.url().includes('/api/v1/notifications?'));
  await page.getByRole('button', { name: '查询工作', exact: true }).click();
  await pending;
  try {
    await expect(page.getByRole('button', { name: '查询工作', exact: true })).toBeDisabled();
    await expect(page.getByRole('combobox', { name: '筛选项目', exact: true })).toBeDisabled();
  } finally { release(); }
  await expect(page.getByRole('button', { name: '查询工作', exact: true })).toBeEnabled();
});

test('Element calendar submits business date strings and invalidates an earlier scan preview', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: '提醒扫描', exact: true }).click();
  const project = page.getByRole('combobox', { name: '扫描项目 *', exact: true });
  await page.locator('.el-select').filter({ has: project }).click();
  await page.getByRole('option', { name: /P-H028/ }).click();
  const date = page.getByLabel('统计 / 扫描日期 *', { exact: true });
  const generate = page.getByRole('button', { name: '确认生成草稿与待办', exact: true });
  await expect(generate).toBeDisabled();
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await date.fill('2026-10-19'); await date.press('Tab');
    const request = page.waitForRequest(r => r.url().endsWith('/reminder-jobs/simulate'));
    await page.getByRole('button', { name: '预览提醒计算', exact: true }).click();
    expect((await request).postDataJSON().as_of).toBe('2026-10-19');
    await expect(generate).toBeEnabled();
    await date.click();
    const calendar = page.locator('.el-popper.project-element-popper').filter({has: page.locator('.el-date-picker')});
    await expect(calendar).toBeVisible();
    await expect(calendar).toHaveCSS('opacity', '1');
    await contained(calendar);
    await page.screenshot({ path: `test-results/element-calendar-${width}.png`, animations: 'disabled' });
    await page.locator('.el-date-table td.available').filter({ hasText: /^21$/ }).click();
    await expect(date).toHaveValue('2026-10-21');
    await expect(generate).toBeDisabled();
  }
  // Required-date validation must prevent a malformed scan request, rather than relying on a server error.
  let submits = 0;
  page.on('request', r => { if (r.url().endsWith('/reminder-jobs/simulate')) submits++; });
  await date.fill(''); await date.press('Tab');
  await page.getByRole('button', { name: '预览提醒计算', exact: true }).click();
  await expect(page.getByText('请选择有效扫描日期', { exact: true })).toBeVisible();
  expect(submits).toBe(0);
});

test('Element pagination requests the selected page without losing records (UI HTTP fixture)', async ({ page }) => {
  await login(page);
  const requests = [];
  // Explicit UI fixture only: production and end-to-end business flows continue using the real API.
  await page.route('**/api/v1/tasks?*', async route => {
    const query = new URL(route.request().url()).searchParams;
    const current = Number(query.get('page'));
    requests.push(current);
    const records = Array.from({ length: 23 }, (_, i) => ({ id: `ui-task-${i}`, title: `分页验收任务 ${i + 1}`, due_date: '2026-10-21', status: 'todo', requires_review: false }));
    await route.fulfill({ json: { success: true, data: { items: records.slice((current - 1) * 20, current * 20), total: 23, page: current, page_size: 20 }, meta: { request_id: 'element-pagination-fixture' } } });
  });
  await page.getByRole('button', { name: '执行任务', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(20);
  const first = await page.locator('tbody tr td:first-child').allTextContents();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(3);
  const second = await page.locator('tbody tr td:first-child').allTextContents();
  expect(new Set([...first, ...second]).size).toBe(23);
  await page.getByRole('button', { name: '上一页', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(20);
  expect(requests).toEqual([1, 2, 1]);
});

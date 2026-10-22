import { test, expect } from '@playwright/test';
import { choose } from './ui-controls.mjs';

test('single-line project rows preserve notes, centered content and continuous action-cell borders', async ({ page }) => {
  await page.goto('/projects');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '项目管理', exact: true })).toBeVisible();
  const table = page.locator('.workspace-projects .table-wrap table');
  const row = table.getByRole('row').filter({ hasText: 'P-H014' });
  await expect(row).toBeVisible();
  const projects = (await (await page.request.get('/api/v1/projects')).json()).data.items;
  await expect(table.getByRole('columnheader', { name: '备注', exact: true })).toBeVisible();
  expect(await table.locator('tbody tr').evaluateAll(rows => rows.map(tr => [...tr.cells].map(td => td.textContent.trim())))).toEqual(projects.map(p => [
    p.project_code, p.project_name, p.project_type || '—', p.owner_name || '未指定', String(p.milestone_count),
    p.updated_at.slice(0, 10), p.project_status === 'active' ? '进行中' : '草稿', p.attention_note || '—', '',
  ]));
  for (const width of [1440, 1275, 1223, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    const layout = await row.evaluate(tr => {
      const cells = [...tr.cells];
      const last = cells.at(-1), box = last.getBoundingClientRect();
      const actions = [...last.querySelectorAll('a, button')].map(el => el.getBoundingClientRect());
      return {
        bottoms: cells.map(cell => cell.getBoundingClientRect().bottom),
        display: getComputedStyle(last).display,
        alignment: cells.map(cell => ({ horizontal: getComputedStyle(cell).textAlign, vertical: getComputedStyle(cell).verticalAlign })),
        cellCenter: box.x + box.width / 2,
        actionCenter: (Math.min(...actions.map(a => a.left)) + Math.max(...actions.map(a => a.right))) / 2,
        compactRows: [...tr.closest('tbody').rows].every(row => row.getBoundingClientRect().height <= 48
          && [...row.cells].every(cell => getComputedStyle(cell).whiteSpace === 'nowrap')),
      };
    });
    expect(layout.compactRows, `${width}px every row must remain compact and single-line`).toBe(true);
    expect(Math.max(...layout.bottoms) - Math.min(...layout.bottoms), `${width}px action border alignment`).toBeLessThanOrEqual(1);
    expect(layout.display).toBe('table-cell');
    expect(layout.alignment.every(a => a.horizontal === 'center' && a.vertical === 'middle')).toBe(true);
    expect(Math.abs(layout.cellCenter - layout.actionCenter)).toBeLessThanOrEqual(1);
    for (const header of await table.locator('th').all()) await expect(header).toHaveCSS('text-align', 'center');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const wrap = page.locator('.workspace-projects .table-wrap');
    await wrap.evaluate(el => { el.scrollLeft = el.scrollWidth; });
    await expect(table.getByRole('columnheader', { name: '操作', exact: true })).toBeInViewport();
    await expect(row.locator('td').nth(7)).toHaveText(projects.find(p => p.project_code === 'P-H014').attention_note);
    await wrap.evaluate(el => { el.scrollLeft = 0; });
    if (width === 1223) {
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: 'test-results/project-table-1223.png', animations: 'disabled' });
    }
  }
  // Keeping the icons inside a proper table cell must preserve the edit action.
  await row.getByRole('button', { name: '编辑 P-H014', exact: true }).click();
  await expect(page.getByRole('dialog').getByLabel('项目编号 *', { exact: true })).toHaveValue('P-H014');
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await row.getByRole('link', { name: '查看 P-H014', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('P-H014');
});

test('project filter controls align responsively and retain search, type selection and custom types', async ({ page }) => {
  await page.goto('/projects');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const form = page.locator('.workspace-projects > .filters');
  const search = page.getByRole('textbox', { name: '搜索项目', exact: true });
  const type = page.getByRole('combobox', { name: '项目类型', exact: true });
  const rows = page.locator('.project-list-table tbody tr');
  await expect(rows).toHaveCount(3);
  for (const width of [1440, 1275, 1024, 900]) {
    await page.setViewportSize({ width, height: 984 });
    const layout = await form.evaluate(el => {
      const bounds = el.getBoundingClientRect();
      return [...el.querySelectorAll('.el-input__wrapper, .el-select__wrapper, :scope > button')].map(control => {
        const rect = control.getBoundingClientRect();
        return { height: rect.height, inside: rect.left >= bounds.left && rect.right <= bounds.right && rect.bottom <= bounds.bottom };
      });
    });
    expect(layout).toHaveLength(5);
    expect(layout.every(control => control.height === 40 && control.inside)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await choose(type, '试制项目');
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText('P-H014');
    await choose(type, '');
    await expect(rows).toHaveCount(3);
    if (width === 1275) await page.screenshot({ path: 'test-results/project-filters-1275.png', animations: 'disabled' });
  }
  await search.fill('P-H028');
  await search.press('Enter');
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText('P-H028');
  await search.hover();
  await form.locator('.el-input__clear').click();
  await expect(search).toHaveValue('');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(rows).toHaveCount(3);
  await type.fill('自定义类型验收');
  await page.getByRole('option', { name: '自定义类型验收', exact: true }).click();
  await expect(page.getByText('暂无符合条件的项目。可新建项目或导入 Excel。', { exact: true })).toBeVisible();
  await expect(type.locator('xpath=ancestor::div[contains(@class,"el-select")][last()]')).toContainText('自定义类型验收');
  await page.getByRole('button', { name: '重置筛选', exact: true }).click();
  await expect(rows).toHaveCount(3);
});

import { test, expect } from '@playwright/test';
import { choose } from './ui-controls.mjs';

test('metric tables keep single-line facts and header actions stay vertically centered', async ({ page }) => {
  await page.goto('/metrics');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '项目量化评估', exact: true })).toBeVisible();
  await page.getByLabel('业务统计截止日', { exact: true }).fill('2026-10-19');
  const computed = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/metrics/summary' && new URL(r.url()).searchParams.get('as_of') === '2026-10-19');
  await page.getByRole('button', { name: '计算评价', exact: true }).click();
  const projects = (await (await computed).json()).data.projects;
  const table = page.locator('.metric-list-table');
  await expect(table.locator('tbody tr')).toHaveCount(projects.length);
  expect(await table.locator('tbody tr').evaluateAll(rows => rows.map(row => [...row.cells].map(cell => cell.textContent.trim())))).toEqual(projects.map(p => [
    p.project_code, p.project_name, p.plan_version_label, String(p.counts.due_total), String(p.counts.on_time_completed),
    String(p.counts.late_completed), String(p.counts.pending_verification), String(p.counts.confirmed_overdue_unfinished),
    p.counts.on_time_rate_pct === null ? '—' : `${p.counts.on_time_rate_pct}%`, '评价明细',
  ]));
  await expect(page.getByRole('link', { name: '导出评价数据', exact: true })).toHaveAttribute('href', '/api/v1/metrics/export?as_of=2026-10-19');
  async function checkRows(columns) {
    const rows = await table.locator('tbody tr').evaluateAll(items => items.map(row => ({
      height: row.getBoundingClientRect().height,
      cells: row.cells.length,
      singleLine: [...row.cells].every(cell => getComputedStyle(cell).whiteSpace === 'nowrap'),
    })));
    expect(rows.every(row => row.height <= 48 && row.cells === columns && row.singleLine)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const wrap = page.locator('.workspace-metrics .table-wrap');
    await wrap.evaluate(el => { el.scrollLeft = el.scrollWidth; });
    await expect(table.getByRole('columnheader', { name: '操作', exact: true })).toBeInViewport();
    await wrap.evaluate(el => { el.scrollLeft = 0; });
  }
  for (const width of [1440, 1275, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    await checkRows(10);
    await page.getByRole('heading', { name: '项目量化评估', exact: true }).scrollIntoViewIfNeeded();
    const layout = await page.locator('.workspace-metrics > .page-title').evaluate(el => {
      const bounds = el.getBoundingClientRect();
      const actions = el.querySelector('.actions').getBoundingClientRect();
      return { centerDelta: Math.abs((bounds.top + bounds.bottom - actions.top - actions.bottom) / 2),
        inside: actions.left >= bounds.left && actions.right <= bounds.right && actions.bottom <= bounds.bottom };
    });
    expect(layout.inside).toBe(true);
    if (width > 1200) expect(layout.centerDelta).toBeLessThanOrEqual(1);
    if (width === 1275) await page.screenshot({ path: 'test-results/metrics-single-line-1275.png', animations: 'disabled' });
  }
  const project = projects.find(p => p.project_code === 'P-H028');
  await table.getByRole('row').filter({ hasText: project.project_code }).getByRole('button', { name: '评价明细', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'P-H028 项目量化评估明细', exact: true })).toBeVisible();
  await expect(table.locator('tbody tr')).toHaveCount(20);
  for (const width of [1440, 1275, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    await checkRows(9);
    const filter = page.locator('.metric-category-filter');
    const layout = await filter.evaluate(el => {
      const label = el.querySelector('span').getBoundingClientRect();
      const select = el.querySelector('.ui-select-field').getBoundingClientRect();
      const heading = el.closest('.section-title').getBoundingClientRect();
      return {
        centerDelta: Math.abs((label.top + label.bottom - select.top - select.bottom) / 2),
        readable: select.width >= 160,
        contained: label.left >= heading.left && select.right <= heading.right,
      };
    });
    expect(layout.centerDelta).toBeLessThanOrEqual(1);
    expect(layout.readable && layout.contained).toBe(true);
    await expect(filter).toContainText('全部节点');
    if (width === 1275) {
      await filter.scrollIntoViewIfNeeded();
      await page.screenshot({ path: 'test-results/metric-category-filter-1275.png', animations: 'disabled' });
    }
  }
  const first = project.evidence[0];
  expect(await table.locator('tbody tr').first().locator('td').allTextContents()).toEqual([
    first.milestone_code, first.milestone_name, first.node_type_code, first.department, first.planned_date,
    first.actual_date || '待核对', String(first.deviation_days ?? '—'), expect.any(String), expect.any(String),
  ]);
  await choose(page.getByRole('combobox', { name: '评价分类', exact: true }), 'late_completed');
  const late = table.getByRole('row').filter({ hasText: 'H028-N006' });
  await late.getByRole('button', { name: '证据追溯', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('2026-10-12');
  await expect(dialog).toContainText('2026-10-15');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '返回项目评价', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(projects.length);
});

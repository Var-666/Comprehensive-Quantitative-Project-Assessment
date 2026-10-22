import { choose } from './ui-controls.mjs';
import { test, expect } from '@playwright/test';

async function openSample(page) {
  await page.goto('/milestones');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '项目节点管理', exact: true })).toBeVisible();
  const projects = (await (await page.request.get('/api/v1/projects')).json()).data.items;
  const project = projects.find(p => p.project_code === 'P-H014');
  await page.goto(`/milestones?project=${project.id}`);
  await expect(page.locator('main .table-wrap tbody')).toContainText('H014-N001');
  await expect(page.getByText('正在加载节点…', { exact: true })).toHaveCount(0);
  return project;
}

test('timeline rail reaches the last milestone after horizontal scrolling', async ({ page }) => {
  await openSample(page);
  const track = page.locator('.timeline');
  await expect(track.locator('.step-card')).toHaveCount(8);
  for (const width of [1440, 1275, 1223, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    const cards = await track.locator('.step-card').evaluateAll(items => items.map(card => {
      const fields = [...card.querySelectorAll('small, strong, :scope > span:not(.timeline-dot)')].map(el => el.getBoundingClientRect());
      const bounds = card.getBoundingClientRect();
      return fields.every((rect, index) => rect.left >= bounds.left && rect.right <= bounds.right
        && rect.bottom <= bounds.bottom && (index === 0 || rect.top >= fields[index - 1].bottom));
    }));
    expect(cards, `${width}px timeline fields must stack vertically inside each card`).toEqual(Array(8).fill(true));
    const stats = await page.locator('.node-stat').evaluateAll(items => items.map(card => {
      const label = card.querySelector('span').getBoundingClientRect();
      const value = card.querySelector('strong').getBoundingClientRect();
      return Math.abs(label.left - value.left) < 1 && value.top >= label.bottom;
    }));
    expect(stats).toEqual(Array(5).fill(true));
    if (width === 1275) await page.screenshot({ path: 'test-results/milestone-layout-1275.png', animations: 'disabled' });
    const rail = await track.evaluate(el => {
      const style = getComputedStyle(el, '::before');
      const start = el.getBoundingClientRect().left + parseFloat(style.left) - el.scrollLeft;
      const dots = [...el.querySelectorAll('.timeline-dot')].map(dot => {
        const rect = dot.getBoundingClientRect(); return rect.x + rect.width / 2;
      });
      return { start, end: start + parseFloat(style.width), dots };
    });
    expect(rail.start).toBeLessThanOrEqual(Math.min(...rail.dots));
    expect(rail.end, `${width}px rail must cover every dot, including offscreen milestones`).toBeGreaterThanOrEqual(Math.max(...rail.dots));
    const scroller = page.locator('.timeline-scroll');
    await scroller.evaluate(el => { el.scrollLeft = el.scrollWidth; });
    const lastDot = await track.locator('.timeline-dot').last().boundingBox();
    const bounds = await scroller.boundingBox();
    expect(lastDot.x + lastDot.width).toBeLessThanOrEqual(bounds.x + bounds.width + 1);
    expect(lastDot.x).toBeGreaterThanOrEqual(bounds.x);
    if (width === 1223) await page.screenshot({ path: 'test-results/milestone-timeline-tail-1223.png', animations: 'disabled' });
  }
  const last = track.locator('.step-card').last();
  const title = await last.locator('strong').textContent();
  await last.click();
  await expect(page.getByRole('dialog')).toContainText(title.trim());
});

test('compact single-line milestone rows paginate ten records without losing fields or records', async ({ page }) => {
  const project = await openSample(page);
  const plan = await page.getByRole('combobox', { name: '计划版本', exact: true }).inputValue();
  const reference = (await (await page.request.get(`/api/v1/projects/${project.id}/milestones?plan_version_id=${plan}&page_size=100`)).json()).data.items;
  await expect(page.locator('.node-stat').first().locator('strong')).toHaveText(String(reference.length));
  const table = page.locator('.workspace-milestones .table-wrap table');
  await expect(table.locator('tbody tr')).toHaveCount(10);
  await expect(table.getByRole('columnheader', { name: '节点名称', exact: true })).toBeVisible();
  await expect(table.getByRole('columnheader', { name: '节点类型', exact: true })).toBeVisible();
  for (const width of [1440, 1280, 1223, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    const rows = await table.locator('tbody tr').evaluateAll(items => items.map(row => ({
      height: row.getBoundingClientRect().height,
      cells: row.cells.length,
      singleLine: [...row.cells].every(cell => getComputedStyle(cell).whiteSpace === 'nowrap'),
    })));
    expect(rows.every(row => row.cells === 8 && row.singleLine && row.height <= 48)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width === 1223) {
      await table.scrollIntoViewIfNeeded();
      await page.screenshot({ path: 'test-results/milestone-table-1223.png', animations: 'disabled' });
    }
  }
  const first = await table.locator('tbody tr td:first-child').allTextContents();
  const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/milestones') && new URL(r.url()).searchParams.get('page') === '2');
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  expect(new URL((await response).url()).searchParams.get('page_size')).toBe('10');
  await expect(table.locator('tbody tr')).toHaveCount(reference.length - 10);
  const second = await table.locator('tbody tr td:first-child').allTextContents();
  expect([...first, ...second]).toEqual(reference.map(node => node.milestone_code));
  expect(new Set([...first, ...second]).size).toBe(reference.length);
  await expect(page.locator('.node-stat').first().locator('strong')).toHaveText(String(reference.length));
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '上一页', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(10);
  expect(await table.locator('tbody tr td:first-child').allTextContents()).toEqual(first);
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(table.locator('tbody tr')).toHaveCount(reference.length - 10);
  await choose(page.getByRole('combobox', { name: '节点类型', exact: true }), reference[0].node_type_code);
  await expect(page.locator('.pagination')).toContainText('第 1 页');
  const filtered = reference.filter(node => node.node_type_code === reference[0].node_type_code);
  await expect(table.locator('tbody tr')).toHaveCount(filtered.length);
});

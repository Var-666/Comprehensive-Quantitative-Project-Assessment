import { test, expect } from '@playwright/test';

async function login(page) {
  await page.goto('/metrics');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '项目量化评估', exact: true })).toBeVisible();
}

test('data quality card preserves server facts, null states, formula access and desktop layout', async ({ page }) => {
  await login(page);
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/metrics/summary' && new URL(r.url()).searchParams.get('as_of') === '2026-10-19');
  await page.getByLabel('业务统计截止日', { exact: true }).fill('2026-10-19');
  await page.getByRole('button', { name: '计算评价', exact: true }).click();
  const data = (await (await response).json()).data;
  const card = page.getByRole('region', { name: '评价说明与数据质量', exact: true });
  await expect(card.locator('.coverage-value')).toHaveText(`${data.counts.completion_verification_coverage_pct}%`);
  await expect(card.locator('.overdue-value')).toHaveText(String(data.counts.confirmed_overdue_unfinished));
  await expect(card.getByRole('progressbar')).toHaveAttribute('value', String(Number(data.counts.completion_verification_coverage_pct)));
  await expect(page.locator('.table-card .section-title')).toHaveText('项目评价列表');
  for (const width of [1609, 1275, 1024, 900]) {
    await page.setViewportSize({ width, height: 984 });
    const layout = await card.evaluate(el => {
      const outer = el.getBoundingClientRect();
      return {
        contained: [...el.querySelectorAll('.quality-stat, .quality-note, .quality-basis')].every(item => {
          const box = item.getBoundingClientRect();
          return box.left >= outer.left && box.right <= outer.right && box.bottom <= outer.bottom;
        }),
        clipped: el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1,
        pageOverflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    expect(layout, `${width}px quality layout`).toEqual({ contained: true, clipped: false, pageOverflow: false });
    if (width === 1275) await page.screenshot({ path: 'test-results/metric-quality-1275.png', animations: 'disabled' });
  }
  await card.getByRole('button', { name: '查看评价口径与数据依据', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText(data.formula.boundary);
  await page.keyboard.press('Escape');
  await page.locator('.metric-list-table tbody').getByRole('button', { name: '评价明细', exact: true }).first().click();
  const project = data.projects[0];
  await expect(card.locator('.coverage-value')).toHaveText(project.counts.completion_verification_coverage_pct === null ? '—' : `${project.counts.completion_verification_coverage_pct}%`);
  await expect(card.locator('.overdue-value')).toHaveText(String(project.counts.confirmed_overdue_unfinished));
  await page.getByRole('button', { name: '返回项目评价', exact: true }).click();
  await page.route('**/api/v1/metrics/summary?*', async route => {
    const payload = await (await route.fetch()).json();
    payload.data.counts.completion_verification_coverage_pct = null;
    payload.data.counts.confirmed_overdue_unfinished = 3;
    await route.fulfill({ json: payload });
  });
  await page.getByRole('button', { name: '计算评价', exact: true }).click();
  await expect(card.locator('.coverage-value')).toHaveText('—');
  await expect(card.locator('.overdue-value')).toHaveText('3');
  await expect(card.getByRole('progressbar')).toHaveCount(0);
});

test('workspace card headings omit repeated date, source and sort captions', async ({ page }) => {
  await login(page);
  const project = (await (await page.request.get('/api/v1/projects')).json()).data.items.find(p => p.project_code === 'P-H028');
  const screens = [
    ['/', '.overview-trend .section-title', '节点履约趋势'],
    ['/', '.overview-projects .section-title', '重点项目进展全部项目 →'],
    ['/projects', '.table-card .section-title', '试点项目台账'],
    ['/milestones', '.timeline-card .section-title', '关键里程碑时间轴'],
    ['/metrics', '.table-card .section-title', '项目评价列表'],
    ['/tasks?tab=tasks', '.table-card .section-title', '标准动作执行任务'],
  ];
  for (const [url, selector, title] of screens) {
    await page.goto(url);
    await expect(page.locator(selector)).toHaveText(title, { useInnerText: false });
    await expect(page.locator(`${selector} .muted`)).toHaveCount(0);
  }
  await page.goto('/actions');
  await expect(page.locator('.template-library-heading')).toBeVisible();
  await expect(page.locator('.template-library-caption')).toHaveCount(0);
  await page.goto(`/projects/${project.id}`);
  await expect(page.getByRole('heading', { name: '项目关键里程碑', exact: true })).toBeVisible();
  await expect(page.locator('.project-milestones > .muted, .project-todos > .muted')).toHaveCount(0);
});

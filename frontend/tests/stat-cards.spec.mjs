import { test, expect } from '@playwright/test';

test('shared statistic cards preserve API facts, semantic colors and left alignment across six pages', async ({ page }) => {
  await page.goto('/projects');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.stat-card')).toHaveCount(4);
  const get = async path => (await (await page.request.get('/api/v1' + path)).json()).data;
  const asOf = await page.evaluate(() => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()));
  const summary = await get('/summary');
  const dashboard = await get(`/metrics/dashboard?as_of=${asOf}`);
  const evaluation = await get(`/metrics/summary?as_of=${asOf}`);
  const project = (await get('/projects')).items.find(p => p.project_code === 'P-H014');
  const metric = await get(`/projects/${project.id}/metrics?as_of=${asOf}`);
  const rate = value => value === null ? '—' : value + '%';
  const checks = [
    ['projects', '/projects', [summary.total, summary.active, summary.draft, summary.completed]],
    ['overview', '/', [summary.total, summary.active, dashboard.pending_tasks, dashboard.counts.late_completed + dashboard.counts.confirmed_overdue_unfinished]],
    ['project-detail', `/projects/${project.id}`, [project.milestone_count, metric.counts.verified_completed, metric.counts.pending_verification, metric.counts.late_completed]],
    ['milestones', `/milestones?project=${project.id}`, [metric.evidence.length, metric.counts.verified_completed, metric.counts.not_due, metric.counts.pending_verification, metric.counts.late_completed]],
    ['metrics', '/metrics', [evaluation.counts.due_total, rate(evaluation.counts.on_time_rate_pct), evaluation.counts.late_completed, evaluation.counts.pending_verification]],
  ];
  async function checkCards(name, values) {
    const cards = page.locator('.stat-card');
    await expect(cards).toHaveCount(values.length);
    await expect(cards.locator('.stat-value-row > strong')).toHaveText(values.map(String));
    await expect(cards.locator('.stat-icon svg')).toHaveCount(values.length);
    for (const width of [1395, 1275, 1024, 900]) {
      await page.setViewportSize({ width, height: 984 });
      const geometry = await cards.evaluateAll(items => items.map(card => {
        const bounds = card.getBoundingClientRect();
        const label = card.querySelector('.stat-label').getBoundingClientRect();
        const value = card.querySelector('strong').getBoundingClientRect();
        const icon = card.querySelector('.stat-icon').getBoundingClientRect();
        return { aligned: Math.abs(value.left - label.left) < 1 && value.top >= label.bottom,
          separated: value.right <= icon.left - 6,
          contained: icon.right <= bounds.right && icon.bottom <= bounds.bottom && card.scrollWidth <= card.clientWidth + 1,
          color: getComputedStyle(card.querySelector('strong')).color,
          iconColor: getComputedStyle(card.querySelector('.stat-icon')).color,
          accent: getComputedStyle(card, '::before').backgroundColor };
      }));
      expect(geometry.every(card => card.aligned && card.separated && card.contained), `${name} at ${width}px`).toBe(true);
      expect(geometry.every(card => card.color === card.iconColor && card.color === card.accent)).toBe(true);
      expect(new Set(geometry.map(card => card.color)).size).toBeGreaterThanOrEqual(3);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (width === 1395 && ['projects', 'overview', 'milestones', 'analysis'].includes(name)) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({ path: `test-results/stat-cards-${name}-1395.png`, animations: 'disabled' });
      }
    }
  }
  for (const [name, url, values] of checks) {
    await page.goto(url);
    await checkCards(name, values);
    if (name === 'metrics') {
      await page.getByRole('button', { name: '查看口径', exact: true }).click();
      await expect(page.getByRole('dialog', { name: '评价口径说明', exact: true })).toBeVisible();
      await page.keyboard.press('Escape');
    }
  }
  await page.goto(`/analysis?project=${project.id}`);
  await expect(page.locator('.analysis-config .notice')).toContainText('Mock');
  const generated = page.waitForResponse(r => r.url().endsWith('/reports/draft') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '生成报告草稿', exact: true }).click();
  const report = (await (await generated).json()).data;
  const counts = report.fact_bundle_json.metric_payload.counts;
  await checkCards('analysis', [counts.due_total, rate(counts.on_time_rate_pct), counts.late_completed, counts.pending_verification]);
});

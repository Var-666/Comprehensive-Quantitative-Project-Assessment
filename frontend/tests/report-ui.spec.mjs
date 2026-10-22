import { test, expect } from '@playwright/test';

test('report typography preserves literal facts and confirmed deletion updates persisted history', async ({ page }) => {
  await page.goto('/analysis');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'AI 阶段报告工作台', exact: true })).toBeVisible();
  await expect(page.locator('.analysis-config .notice')).toContainText('Mock');
  const generate = page.getByRole('button', { name: '生成报告草稿', exact: true });
  const created = [];
  for (let i = 0; i < 3; i++) {
    const response = page.waitForResponse(r => r.url().endsWith('/reports/draft') && r.request().method() === 'POST');
    await generate.click();
    const report = (await (await response).json()).data;
    created.push(report);
    await expect(page.locator('.report-copy')).toBeVisible();
    await expect(page.locator('.report-history-entry')).toHaveCount(i + 1);
  }
  const selected = created[2];
  const older = created[1];
  const entry = page.locator(`[data-report-id="${selected.id}"]`);
  await expect(entry.locator('time')).toHaveAttribute('datetime', selected.generated_at);
  // Explicit UI response fixture: untrusted text must stay literal, never become HTML.
  const literal = '<img src=x onerror="window.reportHtmlExecuted=true">';
  const detailPath = `**/api/v1/reports/${selected.id}`;
  await page.route(detailPath, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    body.data.content += `\n${literal}\n自定义补充段落`;
    await route.fulfill({ response, json: body });
  });
  await entry.locator('.queue-item').click();
  const copy = page.getByRole('article', { name: '报告正文', exact: true });
  for (const line of selected.content.split('\n').filter(Boolean)) await expect(copy).toContainText(line);
  await expect(copy).toContainText(literal);
  await expect(copy).toContainText('自定义补充段落');
  await expect(copy.locator('img, script')).toHaveCount(0);
  expect(await page.evaluate(() => window.reportHtmlExecuted)).toBeUndefined();
  await expect(copy.locator('.report-section-heading')).toHaveCount(3);
  expect(await copy.locator('.report-fact-ref').allTextContents()).toEqual(selected.content.match(/\[[A-Z][A-Z0-9_]*\]/g));
  for (const width of [1440, 1275, 1024]) {
    await page.setViewportSize({ width, height: 984 });
    expect(await copy.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width === 1275) {
      await page.getByRole('heading', { name: 'AI 阶段报告工作台', exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: 'test-results/report-formatted-1275.png', animations: 'disabled', fullPage: true });
    }
  }
  const dialog = page.getByRole('dialog', { name: '删除报告', exact: true });
  await page.locator(`[data-report-id="${created[0].id}"]`).getByRole('button', { name: /^删除报告/ }).click();
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click();
  await expect(page.locator('.report-history-entry')).toHaveCount(2);
  await expect(entry.locator('.queue-item')).toHaveClass(/selected/);
  await expect(copy).toContainText(literal);
  let deletes = 0;
  page.on('request', r => { if (r.method() === 'DELETE' && new URL(r.url()).pathname.startsWith('/api/v1/reports/')) deletes++; });
  await entry.getByRole('button', { name: /^删除报告/ }).click();
  await expect(dialog).toContainText('审核记录和操作日志仍保留');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  expect(deletes).toBe(0);
  await expect(entry).toBeVisible();
  // A failed request keeps the report, selection and confirmation available for retry.
  await page.unroute(detailPath);
  await page.route(detailPath, async route => {
    if (route.request().method() !== 'DELETE') return route.continue();
    await route.fulfill({ status: 409, json: { success: false, error: { code: 'STALE_VERSION', message: '记录已更新，请刷新后重试' } } });
  });
  await entry.getByRole('button', { name: /^删除报告/ }).click();
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('记录已更新');
  await expect(entry).toBeVisible();
  await expect(entry.locator('.queue-item')).toHaveClass(/selected/);
  await page.unroute(detailPath);
  const deleted = page.waitForResponse(r => r.url().endsWith(`/reports/${selected.id}`) && r.request().method() === 'DELETE');
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click();
  const result = await deleted;
  expect(result.status()).toBe(200);
  expect(result.request().headers()['if-match']).toBe(String(selected.row_version));
  await expect(dialog).toHaveCount(0);
  await expect(entry).toHaveCount(0);
  await expect(page.locator(`[data-report-id="${older.id}"] .queue-item`)).toHaveClass(/selected/);
  for (const line of older.content.split('\n').filter(Boolean)) await expect(copy).toContainText(line);
  await page.reload();
  await expect(page.locator('.report-history-entry')).toHaveCount(1);
  expect((await page.request.get(`/api/v1/reports/${selected.id}`)).status()).toBe(404);
  await page.locator('.report-history-entry').getByRole('button', { name: /^删除报告/ }).click();
  await dialog.getByRole('button', { name: '确认删除', exact: true }).click();
  await expect(page.locator('.report-history-entry')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '报告预览', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('暂无可访问的报告。', { exact: true })).toBeVisible();
  await generate.click();
  await expect(page.locator('.report-history-entry')).toHaveCount(1);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.getByLabel('账号', { exact: true }).fill('accept-viewer');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'AI 阶段报告工作台', exact: true })).toBeVisible();
  await expect(page.locator('.report-history-entry')).toHaveCount(1);
  await expect(page.getByRole('article', { name: '报告正文', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /^删除报告/ })).toHaveCount(0);
});

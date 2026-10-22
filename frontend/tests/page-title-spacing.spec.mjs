import { test, expect } from '@playwright/test';

test('workspace titles share the same top inset at desktop breakpoints', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('账号', { exact: true }).fill('accept-editor');
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '项目总体概览', exact: true })).toBeVisible();
  const projects = (await (await page.request.get('/api/v1/projects')).json()).data.items;
  const project = projects.find(p => p.project_code === 'P-H028');
  const screens = ['/', '/projects', `/projects/${project.id}`, '/milestones', '/actions', '/tasks', '/metrics', '/analysis', '/settings/llm', '/imports?target=projects'];
  for (const width of [1561, 1275, 1024, 900]) {
    await page.setViewportSize({ width, height: 984 });
    for (const url of screens) {
      await page.goto(url);
      await expect(page.locator('main .page-title h1')).toBeVisible();
      const geometry = await page.locator('main .page-title').evaluate(title => {
        const header = document.querySelector('.header').getBoundingClientRect();
        const heading = title.querySelector('h1').getBoundingClientRect();
        return {
          headingGap: heading.top - header.bottom,
          titleGap: title.getBoundingClientRect().top - header.bottom,
          padding: parseFloat(getComputedStyle(document.querySelector('main')).paddingTop),
          overflow: document.documentElement.scrollWidth > innerWidth,
        };
      });
      const inset = width > 1200 ? 28 : width > 900 ? 22 : 18;
      expect(geometry.padding, `${url} at ${width}px`).toBe(inset);
      expect(geometry.titleGap, `${url} title at ${width}px`).toBeCloseTo(inset, 1);
      expect(geometry.headingGap, `${url} heading at ${width}px`).toBeCloseTo(inset, 1);
      expect(geometry.overflow, `${url} overflow at ${width}px`).toBe(false);
    }
  }
});

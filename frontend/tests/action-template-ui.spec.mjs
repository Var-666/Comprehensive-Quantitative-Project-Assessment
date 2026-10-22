import { test, expect } from '@playwright/test';
import { choose } from './ui-controls.mjs';
import { execFileSync } from 'node:child_process';

async function login(page, username = 'accept-editor') {
  await page.goto('/actions');
  await page.getByLabel('账号', { exact: true }).fill(username);
  await page.getByLabel('密码', { exact: true }).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.template-list')).toBeVisible();
}

test('template directory preserves all source and action facts with responsive detail layout', async ({ page }) => {
  await login(page);
  // The isolated acceptance DB starts without action drafts; import original Excel rows through the real API.
  const rows = JSON.parse(execFileSync('../.venv/bin/python', ['-c', `
import json
from openpyxl import load_workbook
workbook = load_workbook('../模拟业务测试数据 V0.1.xlsx', read_only=True, data_only=True)
print(json.dumps([list(row) for row in list(workbook['03_标准动作'].values)[6:] if row and row[0]], ensure_ascii=False))
workbook.close()
  `], { encoding: 'utf8' }));
  const departments = (await (await page.request.get('/api/v1/departments')).json()).data;
  const csrf = (await (await page.request.get('/api/v1/auth/me')).json()).data.csrf_token;
  const groups = new Map();
  for (const row of rows) {
    const code = row[0].slice(0, row[0].lastIndexOf('-'));
    if (!groups.has(code)) groups.set(code, []);
    groups.get(code).push(row);
  }
  for (const [code, items] of groups) {
    const first = items[0];
    const response = await page.request.post('/api/v1/action-templates', {
      headers: { 'X-CSRF-Token': csrf },
      data: {
        template_code: code, version_label: 'SAMPLE-V1', title: first[1] + '准备（模拟草案）',
        node_type_code: first[1], applicability_json: {},
        source_ref: `模拟业务测试数据 V0.1.xlsx / 03_标准动作；适用条件、接收人、核实依据待业务确认；来源规则${first[10]}，提前${first[6]}${first[7]}`,
        items: items.map(row => ({ item_code: row[0], title: row[3], materials_required_json: row[4] ? [row[4]] : [],
          default_department_id: departments.find(d => d.dept_name === row[5])?.id || null,
          completion_criteria: '待业务确认；来源列示材料：' + (row[4] || '未提供') })),
      },
    });
    expect(response.status()).toBe(201);
  }
  await page.reload();
  const templates = (await (await page.request.get('/api/v1/action-templates?page_size=20')).json()).data.items;
  const choices = page.locator('.template-choice');
  const detail = page.locator('.template-detail');
  await expect(choices).toHaveCount(templates.length);
  for (const [index, template] of templates.entries()) {
    await choices.nth(index).click();
    await expect(choices.nth(index)).toHaveAttribute('aria-pressed', 'true');
    await expect(detail.getByRole('heading', { level: 2 })).toHaveText(template.title);
    await expect(detail.locator('.template-version')).toContainText(template.template_code);
    await expect(detail.locator('.template-version')).toContainText(template.version_label);
    await expect(detail.locator('.template-source dd')).toHaveText(template.source_ref);
    await expect(detail.locator('.template-action')).toHaveCount(template.items.length);
    for (const [i, action] of template.items.entries()) {
      const card = detail.locator('.template-action').nth(i);
      await expect(card.getByRole('heading', { level: 4 })).toHaveText(action.title);
      await expect(card.locator('.badge')).toHaveText(action.item_code);
      expect((await card.locator('dd').allTextContents()).map(text => text.trim())).toEqual([
        departments.find(d => d.id === action.default_department_id)?.dept_name || '沿用节点责任部门',
        action.completion_criteria, action.materials_required_json.join('、') || '无单独材料要求',
      ]);
    }
  }
  await choices.first().focus();
  await choices.first().press('Enter');
  await expect(detail.getByRole('heading', { level: 2 })).toHaveText(templates[0].title);
  for (const width of [1440, 1275, 1024, 900]) {
    await page.setViewportSize({ width, height: 984 });
    const geometry = await page.locator('.template-split').evaluate(el => {
      const directory = el.querySelector('.queue').getBoundingClientRect();
      const detail = el.querySelector('.template-detail').getBoundingClientRect();
      const source = el.querySelector('.template-source').getBoundingClientRect();
      const summary = el.querySelector('.template-summary').getBoundingClientRect();
      const controls = [...el.querySelectorAll('.template-filters .el-select')].map(control => ({ width: control.clientWidth, scroll: control.scrollWidth }));
      return { directory: directory.toJSON(), detail: detail.toJSON(), sourceWidth: source.width, summaryWidth: summary.width, controls };
    });
    if (width > 950) {
      expect(Math.abs(geometry.directory.y - geometry.detail.y)).toBeLessThanOrEqual(1);
      expect(geometry.directory.right).toBeLessThan(geometry.detail.left);
    } else expect(geometry.directory.bottom).toBeLessThan(geometry.detail.top);
    expect(Math.abs(geometry.sourceWidth - geometry.summaryWidth)).toBeLessThanOrEqual(1);
    expect(geometry.controls.every(control => control.width > 80 && control.scroll <= control.width + 1)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width === 1275) {
      await page.locator('.template-list').evaluate(el => { el.scrollTop = 0; });
      await page.getByRole('heading', { name: '标准动作配置', exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: 'test-results/action-template-redesign-1275.png', animations: 'disabled' });
    }
  }
  await page.setViewportSize({ width: 1275, height: 984 });
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await choose(page.getByRole('combobox', { name: '节点类型', exact: true }), templates[0].node_type_code);
  await page.getByRole('button', { name: '查询模板', exact: true }).click();
  await expect(choices).toHaveCount(templates.filter(t => t.node_type_code === templates[0].node_type_code).length);
  await choose(page.getByRole('combobox', { name: '模板状态', exact: true }), 'approved');
  await page.getByRole('button', { name: '查询模板', exact: true }).click();
  await expect(choices).toHaveCount(0);
  await expect(page.getByText('暂无模板，请创建后提交业务确认。', { exact: true })).toBeVisible();
});

test('redesigned template detail retains editing, new versions and independent approval', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: '创建动作模板', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('模板编号 *', { exact: true }).fill('AT-UI-REDESIGN');
  await dialog.getByLabel('模板名称 *', { exact: true }).fill('模板界面业务回归');
  await choose(dialog.getByLabel('适用节点类型 *', { exact: true }), '设计资料');
  const source = '模拟模板依据，非企业正式规则。'.repeat(15);
  await dialog.getByLabel('模板来源 *', { exact: true }).fill(source);
  await dialog.getByLabel('动作名称 *', { exact: true }).fill('整理并独立核对设计资料');
  await dialog.getByLabel('完成判定及核实依据 *', { exact: true }).fill('测试资料清单经独立核对');
  await dialog.getByLabel('所需材料（每行一项）', { exact: true }).fill('模拟资料清单\n模拟签收记录');
  await dialog.getByRole('button', { name: '保存草稿', exact: true }).click();
  const detail = page.locator('.template-detail');
  await expect(detail.getByRole('heading', { level: 2 })).toHaveText('模板界面业务回归');
  await expect(detail.locator('.template-source dd')).toHaveText(source);
  await detail.getByRole('button', { name: '编辑草稿', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('完成判定及核实依据 *', { exact: true }).fill('修改后的测试核实依据');
  await dialog.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(detail).toContainText('修改后的测试核实依据');
  await detail.getByRole('button', { name: '创建新版本', exact: true }).click();
  dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('版本号 *', { exact: true })).toHaveValue('');
  await dialog.getByLabel('版本号 *', { exact: true }).fill('V2');
  await dialog.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(detail.locator('.template-version')).toContainText('V2');
  await detail.getByRole('button', { name: '提交业务确认', exact: true }).click();
  await expect(detail.getByRole('button', { name: '独立批准', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await login(page, 'accept-reviewer');
  await page.locator('.template-choice').filter({ hasText: 'AT-UI-REDESIGN' }).filter({ hasText: 'V2' }).click();
  await detail.getByRole('button', { name: '独立批准', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('批准依据 / 退回或停用原因 *', { exact: true }).fill('仅为界面回归独立核对，不是正式业务批准');
  await dialog.getByRole('button', { name: '确认批准', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(detail.getByRole('button', { name: '编辑草稿', exact: true })).toHaveCount(0);
  await expect(detail).toContainText('仅为界面回归独立核对');
  const saved = (await (await page.request.get('/api/v1/action-templates?page_size=100')).json()).data.items.filter(t => t.template_code === 'AT-UI-REDESIGN');
  expect(saved.map(t => t.version_label).sort()).toEqual(['V1', 'V2']);
  expect(saved.find(t => t.version_label === 'V2').status).toBe('approved');
  expect(saved.every(t => t.source_ref === source)).toBe(true);
});

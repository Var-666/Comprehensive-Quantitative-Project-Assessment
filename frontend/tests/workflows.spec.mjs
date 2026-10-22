import { choose, setChecked } from './ui-controls.mjs';
import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

async function login(page, username='accept-editor') {
  await page.goto('/projects');
  await page.getByLabel('账号', {exact:true}).fill(username);
  await page.getByLabel('密码', {exact:true}).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await expect(page.getByRole('link',{name:'项目管理',exact:true})).toBeVisible();
}
async function switchAccount(page, username) { await page.getByRole('button',{name:'退出登录'}).click(); await login(page,username); }
test.beforeEach(async({page}) => { await login(page); });

test('project and node edits persist; plan revision preserves the original schedule', async ({ page }) => {
  await page.goto('/projects');
  await page.getByRole('button', { name: '新建项目', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByLabel('项目编号 *', { exact: true }).fill('P-E2E');
  await dialog.getByLabel('项目名称 *', { exact: true }).fill('浏览器验证项目');
  await dialog.getByRole('button', { name: '保存并进入详情' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('P-E2E');
  await page.getByRole('button', { name: '编辑项目', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('项目名称 *', { exact: true }).fill('浏览器修改后项目');
  await dialog.getByRole('button', { name: '保存并进入详情' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('浏览器修改后项目');
  await choose(page.getByLabel('授权人员', {exact:true}), {label:'验收审核人员'});
  await page.getByRole('button',{name:'授权成员',exact:true}).click();
  await expect(page.getByRole('row').filter({hasText:'验收审核人员'})).toBeVisible();
  await page.getByRole('button', { name: '查看节点计划' }).click();
  await expect(page.getByRole('heading', { name: '项目节点管理', exact: true })).toBeVisible();
  const nodesUrl=page.url();
  await page.getByRole('button', { name: '添加节点', exact: true }).first().click();
  dialog = page.getByRole('dialog');
  fs.mkdirSync(path.resolve('../docs/figma-ui/after'),{recursive:true});
  for(const width of [1440,1280,1024]) {
    await page.setViewportSize({width,height:900});
    const surface=page.locator('.modal:visible');await expect.poll(async()=>{const r=await surface.boundingBox();return r.y>=0&&r.y+r.height<=901;}).toBe(true);const rect=await surface.boundingBox();expect(rect.width).toBe(690);expect(rect.y).toBeGreaterThanOrEqual(0);expect(rect.y+rect.height).toBeLessThanOrEqual(901);
    await page.screenshot({path:path.resolve(`../docs/figma-ui/after/node-form-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:1000});
  await dialog.getByLabel('节点编号 *', { exact: true }).fill('E2E-N001');
  await dialog.getByLabel('节点名称 *', { exact: true }).fill('浏览器测试节点');
  await dialog.getByLabel('录入 / 变更原因 *').fill('验证计划持久化');
  let nodeWrites=0;page.on('request',r=>{if(r.method()==='POST'&&/\/projects\/[^/]+\/milestones$/.test(new URL(r.url()).pathname))nodeWrites++;});
  await dialog.getByRole('button',{name:'保存节点',exact:true}).click();
  expect(nodeWrites).toBe(0);
  expect(await dialog.locator('#node-form').evaluate(f=>f.checkValidity())).toBe(false);
  await choose(dialog.getByLabel('节点类型 *'), '设计资料');
  await dialog.getByLabel('计划完成日期 *').fill('2026-11-01');
  await dialog.getByLabel('计划完成日期 *').press('Tab');
  await dialog.getByRole('button', { name: '保存节点' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('main .table-wrap tbody')).toContainText('E2E-N001');
  await expect(page.getByRole('button', { name: '批准生效' })).toBeDisabled();
  await switchAccount(page,'accept-reviewer');
  await page.goto(nodesUrl);
  await page.getByRole('button', { name: '批准生效' }).click();
  await page.getByRole('dialog').getByRole('textbox').fill('仅浏览器演示确认');
  await page.getByRole('dialog').getByRole('button', { name: '批准计划生效', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await switchAccount(page,'accept-editor');
  await page.goto(nodesUrl);
  await expect(page.getByRole('button', { name: '新建变更草稿' })).toBeEnabled();
  await page.getByRole('button', { name: '新建变更草稿' }).click();
  await page.getByRole('dialog').getByRole('textbox').fill('演示计划延期');
  await page.getByRole('dialog').getByRole('button', { name: '创建变更草稿', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.locator('main .table-wrap tbody').getByRole('button', { name: '编辑', exact: true }).click();
  dialog = page.getByRole('dialog');
  await dialog.getByLabel('计划完成日期 *').fill('2026-11-04');
  await dialog.getByLabel('录入 / 变更原因 *').fill('调整三天并保留旧版');
  await dialog.getByRole('button', { name: '保存节点' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('main .table-wrap tbody')).toContainText('2026-11-04');
  await page.getByRole('button', { name: '查看详情', exact: true }).click();
  dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('2026-11-01');
  await expect(dialog).toContainText('2026-11-04');
  await choose(dialog.getByLabel('完成事实', { exact: true }), 'true');
  await dialog.getByLabel('来源 / 证据说明 *').fill('虚构完成记录，用于验证');
  await dialog.getByRole('button', {name:'提交实际记录',exact:true}).click();
  await expect(dialog.getByText('请选择有效日期',{exact:true})).toBeVisible();
  await choose(dialog.getByLabel('完成事实',{exact:true}),'false');
  await expect(dialog.getByText('请选择有效日期',{exact:true})).toHaveCount(0);
  await choose(dialog.getByLabel('完成事实',{exact:true}),'true');
  await dialog.getByLabel('实际完成日期', { exact: true }).fill('2026-11-02');
  await dialog.getByLabel('来源 / 证据说明 *').fill('虚构完成记录，用于验证');
  await dialog.getByRole('button', { name: '提交实际记录', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('仍需独立核实');
  await expect(dialog.getByText('未知 / 尚未确认完成', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button',{name:'确认核实',exact:true})).toHaveCount(0);
  await dialog.getByRole('button',{name:'关闭',exact:true}).last().click();
  await switchAccount(page,'accept-reviewer');
  await page.goto(nodesUrl);
  await page.getByRole('button',{name:'查看详情',exact:true}).click();
  dialog=page.getByRole('dialog');
  await dialog.getByLabel('核实意见', { exact: true }).fill('独立核实确认');
  await dialog.getByRole('button', { name: '确认核实', exact: true }).click();
  await expect(dialog).toContainText('当前核实事实');
  await page.screenshot({ path: 'test-results/node-detail-1440.png', fullPage: true });
  await dialog.getByRole('button', { name: '关闭', exact: true }).last().click();
  await page.reload();
  await choose(page.getByLabel('计划版本', { exact: true }), { label: 'V1 · 已生效' });
  await expect(page.locator('main .table-wrap tbody')).toContainText('2026-11-01');
  await expect(page.locator('main .table-wrap tbody')).not.toContainText('2026-11-04');
});

test('Excel preview requires confirmation and duplicate upload cannot overwrite data', async ({ page }) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'project-eval-upload-'));
  const file = path.join(directory, 'valid.xlsx');
  execFileSync('../.venv/bin/python', ['-c', `from openpyxl import Workbook
import sys
w=Workbook(); s=w.active; s.title='data'
s.append(['项目编号','项目名称','项目类型','项目负责人','责任部门','项目状态','计划开始','计划结束'])
s.append(['P-E2E-IMPORT','浏览器导入项目','船舶建造','张工','项目部','进行中','2026-10-01','2027-01-01'])
n=w.create_sheet('nodes')
n.append(['项目编号','节点编号','节点名称','节点类型','计划完成日期','责任部门','责任人','日期依据'])
n.append(['P-E2E-IMPORT','IMPORT-N001','页面导入节点','设计资料','2026-11-10','项目部','张工','内部计划演示'])
w.save(sys.argv[1])`, file]);
  await page.goto('/projects');
  async function upload() {
    await page.getByRole('button', { name: '导入 Excel', exact: true }).click();
    await expect(page).toHaveURL(/\/imports\?target=projects/);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const dialog = page.locator('.import-workspace');
    await dialog.locator('.el-upload input[type=file]').setInputFiles(file);
    await dialog.locator('.el-upload input[type=file]').setInputFiles(file);
    await expect(dialog.locator('.el-upload-list__item')).toHaveCount(1);
    await dialog.getByLabel('工作表名称').fill('data');
    await dialog.getByLabel('表头行号').fill('1');
    await dialog.getByRole('button', { name: '下一步：校验预览' }).click();
    return dialog;
  }
  let dialog = await upload();
  await expect(dialog).toContainText('合法 1 行');
  await expect(dialog.getByRole('button', { name: '确认导入', exact: true })).toBeDisabled();
  await setChecked(dialog.getByRole('checkbox'), true);
  await dialog.getByRole('button', { name: '确认导入', exact: true }).click();
  await expect(dialog).toContainText('写入 1 行');
  await dialog.getByRole('button', { name: '完成', exact: true }).click();
  await page.reload();
  await expect(page.locator('main .table-wrap tbody')).toContainText('P-E2E-IMPORT');
  dialog = await upload();
  await expect(dialog).toContainText('错误/重复 1 行');
  await expect(dialog.getByRole('button', { name: '确认导入', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('button', { name: '放弃修改', exact: true }).click();
  await page.getByRole('link', { name: 'P-E2E-IMPORT', exact: true }).click();
  await page.getByRole('button', { name: '查看节点计划' }).click();
  await page.getByRole('button', { name: '导入 Excel', exact: true }).click();
  dialog = page.locator('.import-workspace');
  await dialog.locator('.el-upload input[type=file]').setInputFiles(file);
  await dialog.getByLabel('工作表名称').fill('nodes');
  await dialog.getByLabel('表头行号').fill('1');
  await dialog.getByRole('button', { name: '下一步：校验预览' }).click();
  await expect(dialog).toContainText('合法 1 行');
  await setChecked(dialog.getByRole('checkbox'), true);
  await dialog.getByRole('button', { name: '确认导入', exact: true }).click();
  await expect(dialog).toContainText('写入 1 行');
  await dialog.getByRole('button', { name: '完成', exact: true }).click();
  await page.reload();
  await expect(page.locator('main .table-wrap tbody')).toContainText('IMPORT-N001');
  fs.rmSync(directory, { recursive: true });
});

test('navigation, errors and desktop geometry expose real state', async ({ page }) => {
  const consoleErrors = [];
  page.on('pageerror', e => consoleErrors.push(e.message));
  await page.goto('/projects');
  await expect(page.locator('main .table-wrap tbody')).toContainText('P-H028');
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    const geometry = await page.evaluate(() => ({ sidebar: document.querySelector('.sidebar').getBoundingClientRect().height, height: innerHeight, pageWidth: document.documentElement.scrollWidth, viewport: innerWidth, broken: [...document.images].filter(i => !i.complete || i.naturalWidth===0).length }));
    expect(geometry.sidebar).toBe(geometry.height);
    expect(geometry.pageWidth).toBeLessThanOrEqual(geometry.viewport);
    expect(geometry.broken).toBe(0);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: 'test-results/projects-1440.png', fullPage: true });
  await page.getByRole('link', { name: '标准动作', exact: true }).click();
  await expect(page.getByRole('heading', { name: '标准动作配置' })).toBeVisible();
  await page.goto('/projects');
  await page.route('**/api/v1/projects?**', route => route.abort());
  await page.getByLabel('搜索项目').fill('故障测试');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test('project filters, archive and viewer restrictions are usable through the page', async ({page}) => {
  await page.goto('/projects');
  await page.getByRole('button',{name:'新建项目',exact:true}).click();
  let dialog=page.getByRole('dialog');
  await dialog.getByLabel('项目编号 *',{exact:true}).fill('P-ARCHIVE');
  await dialog.getByLabel('项目名称 *',{exact:true}).fill('页面归档验收');
  await dialog.getByRole('button',{name:'保存并进入详情'}).click();
  await page.getByRole('button',{name:'归档项目',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'确认归档',exact:true}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.detail-card')).toContainText('已归档');
  await switchAccount(page,'accept-viewer');
  await expect(page.getByRole('button',{name:'新建项目',exact:true})).toBeDisabled();
  await choose(page.getByLabel('项目状态'), 'active');
  await expect(page.locator('main .table-wrap tbody')).toContainText('P-H028');
  await choose(page.getByRole('combobox',{name:'项目类型',exact:true}), '试制项目');
  await page.getByRole('button',{name:'查询',exact:true}).click();
  await expect(page.getByText('暂无符合条件的项目。可新建项目或导入 Excel。')).toBeVisible();
  await page.getByRole('button',{name:'重置筛选'}).click();
  await page.getByRole('link',{name:'P-H028',exact:true}).click();
  await expect(page.getByRole('button',{name:'编辑项目',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'查看节点计划'}).click();
  await expect(page.getByRole('button',{name:'添加节点',exact:true}).first()).toBeDisabled();
});

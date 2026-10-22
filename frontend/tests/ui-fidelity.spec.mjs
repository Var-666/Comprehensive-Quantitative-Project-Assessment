import { choose, optionValues } from './ui-controls.mjs';
import {test, expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const phase = process.env.UI_AUDIT_PHASE || 'after';
const evidenceRoot = path.resolve('../docs/figma-ui', phase);
const screens = [
  ['overview','/','项目总体概览','项目总览'],
  ['projects','/projects','项目管理','项目管理'],
  ['milestones','/milestones','项目节点管理','节点管理'],
  ['actions','/actions','标准动作配置','标准动作'],
  ['tasks','/tasks','提醒与待办','提醒与待办'],
  ['metrics','/metrics','项目量化评估','量化评估'],
  ['analysis','/analysis','AI 阶段报告工作台','AI 智能分析'],
  ['settings','/settings/llm','系统设置','系统设置'],
];

async function login(page, user='accept-editor') {
  await page.clock.setFixedTime(new Date('2026-10-19T04:00:00Z'));
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill(user);
  await page.getByLabel('密码',{exact:true}).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await expect(page.getByRole('heading',{name:'项目总体概览',exact:true})).toBeVisible();
}

async function contained(locator) {
  locator=locator.page().locator('.modal:visible');
  await expect.poll(async()=>{const r=await locator.boundingBox();const v=locator.page().viewportSize();return !!r&&r.x>=-1&&r.y>=-1&&r.x+r.width<=v.width+1&&r.y+r.height<=v.height+1;}).toBe(true);
  const rect=await locator.boundingBox();
  const viewport=locator.page().viewportSize();
  expect(rect).not.toBeNull();
  expect(rect.x).toBeGreaterThanOrEqual(-1);
  expect(rect.y).toBeGreaterThanOrEqual(-1);
  expect(rect.x+rect.width).toBeLessThanOrEqual(viewport.width+1);
  expect(rect.y+rect.height).toBeLessThanOrEqual(viewport.height+1);
}

test('reproducible Figma audit captures all workspaces at three desktop sizes', async ({page}) => {
  test.setTimeout(120000);
  fs.mkdirSync(evidenceRoot,{recursive:true});
  await page.clock.setFixedTime(new Date('2026-10-19T04:00:00Z'));
  await page.goto('/');
  await page.getByLabel('账号',{exact:true}).fill('accept-editor');
  await page.getByLabel('密码',{exact:true}).fill(process.env.ACCEPTANCE_PASSWORD);
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await expect(page.getByRole('heading',{name:'项目总体概览',exact:true})).toBeVisible();
  const geometry=[];
  for (const width of [1440,1280,1024]) {
    await page.setViewportSize({width,height:900});
    for (const [name,url,title,nav] of screens) {
      await page.goto(url);
      await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
      await expect(page.locator('.sidebar nav a.active')).toHaveText(nav);
      await page.waitForLoadState('networkidle');
      await page.evaluate(()=>document.fonts.ready);
      await page.screenshot({path:path.join(evidenceRoot,`${name}-${width}.png`)});
      const state=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scroll:document.documentElement.scrollWidth,sidebar:document.querySelector('.sidebar').getBoundingClientRect().toJSON(),broken:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.getAttribute('src'))}));
      expect(state.scroll).toBeLessThanOrEqual(width);
      expect(state.sidebar.height).toBe(900);
      expect(state.broken).toEqual([]);
      geometry.push({name,...state});
    }
  }
  fs.writeFileSync(path.join(evidenceRoot,'geometry.json'),JSON.stringify({phase,businessClock:'2026-10-19T04:00:00Z',data:'isolated acceptance_seed via real API',geometry},null,2)+'\n');
});

const failures = [
  ['/','**/api/v1/metrics/dashboard?*','正在加载项目、节点和待办…'],
  ['/projects','**/api/v1/projects?*','正在加载项目…'],
  ['/milestones','**/api/v1/projects/*/milestones?*','正在加载节点…'],
  ['/actions','**/api/v1/action-templates?*','正在加载动作模板…'],
  ['/tasks','**/api/v1/notifications?*','正在处理…'],
  ['/metrics','**/api/v1/metrics/summary?*','正在计算或读取证据…'],
  ['/analysis','**/api/v1/projects/*/reports','正在读取事实或生成报告…'],
  ['/settings/llm','**/api/v1/settings/llm','正在加载大模型服务配置…'],
];
for (const [url, pattern, message] of failures) {
  test(`workspace ${url} exposes loading and request errors, then recovers`,async({page})=>{
    await login(page);
    let release;
    const gate=new Promise(resolve=>{release=resolve;});
    await page.route(pattern,async route=>{
      await gate;
      await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({success:false,error:{code:'UI_ACCEPTANCE_NETWORK_ERROR',message:'UI验收模拟网络异常',fields:[],retryable:false},meta:{request_id:'ui-acceptance'}})});
    });
    await page.goto(url);
    try { await expect(page.getByText(message,{exact:true})).toBeVisible(); }
    finally { release(); }
    await expect(page.getByRole('alert').first()).toContainText('UI验收模拟网络异常');
    await page.unroute(pattern);
    await page.reload();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('alert')).toHaveCount(0);
  });
}

test('Element dropdowns can select, close and reopen across all migrated workspaces',async({page})=>{
  test.setTimeout(90000);
  fs.mkdirSync(evidenceRoot,{recursive:true});
  await login(page);
  let exercised=0, expected=0;const coverage=[];
  for(const [name,url,title] of screens) {
    await page.goto(url);
    await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
    await page.waitForLoadState('networkidle');
    const controls=page.locator('.ui-select-field input[role="combobox"]:visible');
    const count=await controls.count();
    const eligible=[];for(let i=0;i<count;i++)if(await controls.nth(i).isEnabled())eligible.push(i);
    const enabled=eligible.length;expected+=enabled;
    const start=exercised;
    for(const i of eligible) {
      const select=controls.nth(i);
      const choices=await optionValues(select);
      if(!choices.length)continue;
      await choose(select,choices[choices.length-1]);
      await page.waitForLoadState('networkidle');
      await expect(select).toBeEnabled();
      await choose(select,choices[0]);
      await page.waitForLoadState('networkidle');
      exercised++;
    }
    coverage.push({name,visible:count,expected:enabled,exercised:exercised-start});
  }
  fs.writeFileSync(path.join(evidenceRoot,'dropdown-coverage.json'),JSON.stringify(coverage,null,2)+'\n');
  expect(exercised).toBe(expected);
  expect(coverage.filter(row=>row.exercised>0).map(row=>row.name)).toEqual(['projects','milestones','actions','analysis','settings']);
});

test('forms and drawers remain inside the viewport and cancel preserves data',async({page})=>{
  await login(page);
  const base=await (await page.request.get('/api/v1/projects')).json();
  const example=base.data.items.find(p=>p.project_code==='P-H028');
  for(const width of [1440,1280,1024]) {
    await page.setViewportSize({width,height:900});
    await page.goto(`/projects/${example.id}`);await expect(page.locator('.project-execution-summary')).toContainText('trial_v1');await page.waitForLoadState('networkidle');await page.screenshot({path:path.join(evidenceRoot,`project-detail-${width}.png`)});
    await page.getByRole('navigation',{name:'项目详情导航'}).getByRole('link',{name:'量化评估',exact:true}).click();await expect(page.getByRole('heading',{level:1})).toContainText('P-H028 项目量化评估明细');
    await page.goto('/projects');
    await page.getByRole('button',{name:'新建项目',exact:true}).click();
    let dialog=page.getByRole('dialog');
    await contained(dialog);
    await dialog.getByRole('button',{name:'保存并进入详情'}).click();
    expect(await dialog.locator('#project-form').evaluate(f=>f.checkValidity())).toBe(false);
    for(const select of await dialog.locator('.ui-select-field input[role="combobox"]').all()) {
      const initialLabel=(await select.locator('xpath=ancestor::div[contains(concat(" ", @class, " "), " el-select ")][1]').locator('.el-select__selected-item').last().textContent()).trim();
      const values=await optionValues(select);
      await choose(select, values[values.length-1]);
      await choose(select, {label:initialLabel});
    }
    await page.screenshot({path:path.join(evidenceRoot,`project-form-${width}.png`)});
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    await expect(dialog).toHaveCount(0);
    await page.getByRole('button',{name:'导入 Excel',exact:true}).click();
    await expect(page.locator('.import-workspace')).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:path.join(evidenceRoot,`import-page-${width}.png`)});
    await page.getByRole('button',{name:'返回来源页面',exact:true}).click();
    await page.goto('/milestones');
    await page.getByRole('button',{name:'查看详情',exact:true}).first().click();
    dialog=page.getByRole('dialog');await contained(dialog);
    await page.screenshot({path:path.join(evidenceRoot,`node-drawer-${width}.png`)});
    await dialog.getByRole('button',{name:'变更历史',exact:true}).click();
    await expect(dialog.getByRole('heading',{name:'计划历史快照',exact:true})).toBeVisible();
    expect(await dialog.locator('.modal-body').evaluate(e=>e.scrollTop)).toBeGreaterThan(0);
    await dialog.getByRole('button',{name:'节点信息',exact:true}).click();
    await expect(dialog.locator('[data-node-section="info"]').getByText('计划日期',{exact:true})).toBeVisible();
    await dialog.getByRole('button',{name:'关闭',exact:true}).last().click();
  }
  const after=await (await page.request.get('/api/v1/projects')).json();
  expect(after.data.total).toBe(base.data.total);
});

test('late project responses cannot overwrite the currently selected node plan',async({page})=>{
  await login(page);
  const projects=(await (await page.request.get('/api/v1/projects')).json()).data.items;
  const slow=projects.find(p=>p.project_code==='P-H031'), current=projects.find(p=>p.project_code==='P-H014');
  await page.goto('/milestones');await page.waitForLoadState('networkidle');
  let release;const gate=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/v1/projects/**',async route=>{
    const pathname=new URL(route.request().url()).pathname;
    if(pathname===`/api/v1/projects/${slow.id}`||pathname===`/api/v1/projects/${slow.id}/plan-versions`)await gate;
    await route.continue();
  });
  const request=page.waitForRequest(r=>new URL(r.url()).pathname===`/api/v1/projects/${slow.id}`);
  await choose(page.getByLabel('所属项目'), slow.id);await request;
  await expect(page.getByRole('combobox',{name:'计划版本',exact:true})).toBeDisabled();
  await choose(page.getByLabel('所属项目'), current.id);
  await expect(page.getByRole('combobox',{name:'计划版本',exact:true})).toBeEnabled();
  release();await page.waitForLoadState('networkidle');
  await expect(page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'所属项目',exact:true})})).toContainText(current.project_code);
  await expect(page.locator('.project-context-meta')).toContainText('王工');
  await expect(page.locator('main .table-wrap tbody')).toContainText('H014-');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('real project pagination and long table scrolling keep every record reachable',async({page})=>{
  await login(page);
  const identity=(await (await page.request.get('/api/v1/auth/me')).json()).data;
  const created=[];
  try {
  for(let i=0;i<23;i++) {
    const response=await page.request.post('/api/v1/projects',{headers:{'X-CSRF-Token':identity.csrf_token},data:{project_code:`UI-SCROLL-${i}`,project_name:`滚动与分页验收 ${i}`,project_status:'not_started'}});
    expect(response.status()).toBe(201);
    created.push((await response.json()).data.id);
  }
  await page.setViewportSize({width:1024,height:900});
  await page.goto('/projects');
  await page.getByRole('textbox',{name:'搜索项目',exact:true}).fill('UI-SCROLL-');
  await page.getByRole('button',{name:'查询',exact:true}).click();
  await expect(page.locator('.pagination')).toContainText('共 23 条');
  const wrapper=page.locator('.table-wrap');
  const geometry=await wrapper.evaluate(e=>({width:e.clientWidth,scrollWidth:e.scrollWidth,height:e.clientHeight,scrollHeight:e.scrollHeight}));
  expect(geometry.scrollWidth).toBeGreaterThan(geometry.width);
  expect(geometry.scrollHeight).toBeGreaterThan(geometry.height);
  await wrapper.evaluate(e=>{e.scrollTop=e.scrollHeight;e.scrollLeft=e.scrollWidth;});
  expect(await wrapper.evaluate(e=>e.scrollTop)).toBeGreaterThan(0);
  expect(await wrapper.evaluate(e=>e.scrollLeft)).toBeGreaterThan(0);
  const firstCodes=await page.locator('tbody tr td:first-child').allTextContents();
  await page.getByRole('button',{name:'下一页',exact:true}).click();
  await expect(page.locator('.pagination')).toContainText('第 2 页');
  const nextCodes=await page.locator('tbody tr td:first-child').allTextContents();
  expect(firstCodes.length+nextCodes.length).toBe(23);
  expect(new Set([...firstCodes,...nextCodes]).size).toBe(23);
  await page.getByRole('button',{name:'上一页',exact:true}).click();
  await expect(page.locator('.pagination')).toContainText('第 1 页');
  await page.getByRole('button',{name:'重置筛选',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'搜索项目',exact:true})).toHaveValue('');
  } finally {
    for(const id of created){const r=await page.request.put(`/api/v1/projects/${id}/members`,{headers:{'X-CSRF-Token':identity.csrf_token},data:{user_id:identity.user_id,role_code:'admin',active:false}});expect(r.status()).toBe(200);}
  }
});

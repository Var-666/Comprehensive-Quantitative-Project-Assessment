import { choose, setChecked } from '../tests/ui-controls.mjs';
import {test,expect} from '@playwright/test';
import crypto from 'node:crypto';
import path from 'node:path';
import fs from 'node:fs';
const key='browser-http-double-'+crypto.randomBytes(24).toString('hex');
async function login(page,username='accept-editor'){
 await page.goto('/settings/llm');await page.getByLabel('账号',{exact:true}).fill(username);await page.getByLabel('密码',{exact:true}).fill(process.env.ACCEPTANCE_PASSWORD);await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.getByRole('heading',{name:'系统设置',exact:true})).toBeVisible();
}
test('HTTPS settings persist credentials and independent discovered/model-tested/default/scenario states (HTTP doubles)',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const automaticTests=[];page.on('request',r=>{if(/\/api\/v1\/settings\/llm\/models\/[^/]+\/test$/.test(r.url()))automaticTests.push(r.url());});
 await login(page);await expect(page.getByLabel('API Base URL',{exact:true})).toHaveValue('https://maas-api.cmhk.com/v1');
 await page.getByRole('button',{name:'测试连接',exact:true}).click();
 let d=page.getByRole('dialog');await expect(d).toContainText('未配置 API Key');await page.screenshot({path:'test-results-llm/llm-connection-result.png'});await d.getByRole('button',{name:'关闭结果',exact:true}).click();
 await page.getByRole('button',{name:'管理服务',exact:true}).click();d=page.getByRole('dialog');await d.getByLabel('服务名称 *').fill('HTTP替身验证网关，非实际MaaS连接');await d.getByRole('button',{name:'保存服务配置',exact:true}).click();await expect(d).toHaveCount(0);
 await page.screenshot({path:'test-results-llm/llm-settings-unconfigured.png',fullPage:true});
 await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();d=page.getByRole('dialog');await expect(d.getByLabel('新的 API Key *')).toHaveAttribute('type','password');await page.screenshot({path:'test-results-llm/llm-key-dialog.png'});await d.getByLabel('新的 API Key *').fill(key);await d.getByRole('button',{name:'保存新密钥',exact:true}).click();await expect(d).toHaveCount(0);
 const settingsResponse=await page.request.get('/api/v1/settings/llm');expect(await settingsResponse.text()).not.toContain(key);
 await page.getByRole('button',{name:'测试连接',exact:true}).click();d=page.getByRole('dialog');await expect(d).toContainText('列表读取成功');await expect(d).toContainText('尚未执行');await d.getByRole('button',{name:'关闭结果',exact:true}).click();
 await page.getByRole('button',{name:'刷新模型列表',exact:true}).click();await expect(page.getByRole('status')).toContainText('自动验证完成：已测试 3/3 个，2 个通过，1 个未通过');
 let row=page.locator('.llm-model-tile[data-model-id="http-double-analysis"]');await expect(row).toContainText('基础调用通过');
 await expect(page.locator('.llm-model-tile')).toHaveCount(2);
 await expect(page.locator('.llm-model-tile[data-model-id="http-double-blocked"]')).toHaveCount(0);
 await expect(page.locator('.llm-model-tile[data-model-id="http-double-notice"]')).toContainText('基础调用通过');expect(automaticTests).toHaveLength(3);
 const discovered=(await (await page.request.get('/api/v1/settings/llm/models')).json()).data;expect(discovered).toHaveLength(3);expect(discovered.find(m=>m.model_id==='http-double-blocked').selectable).toBe(false);
 const notice=page.locator('.llm-model-tile[data-model-id="http-double-notice"]');await notice.getByRole('button',{name:'禁用',exact:true}).click();await expect(notice).toContainText('已禁用');await expect(page.locator('.llm-model-tile')).toHaveCount(2);await notice.getByRole('button',{name:'启用',exact:true}).click();await expect(notice.getByRole('button',{name:'禁用',exact:true})).toBeVisible();
 for(const collapsed of [false,true]){
  if(collapsed)await page.getByRole('button',{name:'收起侧边栏',exact:true}).click();
  for(const width of [1440,1275,1024]){
   await page.setViewportSize({width,height:984});
   const layout=await page.locator('.llm-model-grid').evaluate(grid=>{const bounds=grid.getBoundingClientRect();return [...grid.children].map(tile=>{const box=tile.getBoundingClientRect();return {inside:box.left>=bounds.left&&box.right<=bounds.right&&box.bottom<=bounds.bottom,compact:box.height<=230,overflow:tile.scrollWidth>tile.clientWidth};});});expect(layout.every(t=>t.inside&&t.compact&&!t.overflow)).toBe(true);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
   if(width===1275){await page.locator('.llm-model-card').scrollIntoViewIfNeeded();await page.screenshot({path:`test-results-llm/model-cards-${collapsed?'collapsed':'expanded'}-1275.png`,animations:'disabled'});}
  }
 }
 await page.getByRole('button',{name:'展开侧边栏',exact:true}).click();
 await page.getByRole('button',{name:'刷新模型列表',exact:true}).click();await expect(page.getByRole('status')).toContainText('跳过 2 个已验证或已禁用模型');expect(automaticTests).toHaveLength(4);
 await page.getByRole('button',{name:/先连接服务并获取模型列表/}).click();await page.locator('#default-model-options').getByRole('button',{name:/HTTP替身：分析测试模型/}).click();
 await choose(page.getByRole('combobox',{name:'通知与工作安排草稿',exact:true}), {label:'HTTP替身：通知测试模型'});
 await page.getByRole('switch',{name:'启用实际模型调用'}).click();await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','true');
 await page.reload();await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','true');await expect(page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'通知与工作安排草稿',exact:true})})).toContainText('HTTP替身：通知测试模型');
 await page.locator('.llm-model-tile[data-model-id="http-double-analysis"]').getByRole('button',{name:'禁用',exact:true}).click();await expect(page.getByRole('alert')).toContainText('模型正被默认或业务场景引用');
 await page.getByRole('button',{name:'＋ 手动添加模型',exact:true}).click();d=page.getByRole('dialog');await page.screenshot({path:'test-results-llm/llm-manual-dialog.png'});await d.getByLabel('模型 ID *').fill('manual-http-double-id');await d.getByLabel('显示名称（可选）').fill('手动HTTP替身模型');await d.getByRole('button',{name:'保存模型',exact:true}).click();await expect(d).toHaveCount(0);
 row=page.locator('.llm-model-tile[data-model-id="manual-http-double-id"]');await expect(row).toHaveCount(0);await expect(page.getByRole('status')).toContainText('点击刷新模型自动验证');await page.getByRole('button',{name:'刷新模型',exact:true}).click();await expect(row).toContainText('手动录入');await expect(row).toContainText('基础调用通过');await row.getByRole('button',{name:'删除',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'确认删除模型'}).click();await expect(row).toHaveCount(0);
 await page.screenshot({path:'test-results-llm/llm-settings-configured.png',fullPage:true});
 await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();d=page.getByRole('dialog');await expect(d.getByLabel('新的 API Key *')).toHaveValue('');await d.getByLabel('新的 API Key *').fill(key+'-replacement');await d.getByRole('button',{name:'保存新密钥',exact:true}).click();await expect(d).toHaveCount(0);await expect(page.locator('.llm-model-tile')).toHaveCount(0);await expect(page.getByText('暂无测试通过的模型',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'移除已保存 Key'}).click();d=page.getByRole('dialog');await setChecked(d.getByRole('checkbox'), true);await d.getByRole('button',{name:'确认移除密钥'}).click();await expect(d).toHaveCount(0);await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','false');
 for(const storage of ['localStorage','sessionStorage'])expect(await page.evaluate(name=>JSON.stringify(window[name]),storage)).not.toContain(key);
 for(const path of ['/api/v1/settings/llm','/api/v1/settings/llm/models','/api/v1/settings/llm/audit-events','/api/v1/settings/llm/call-logs'])expect(await (await page.request.get(path)).text()).not.toContain(key);
 for(const width of [1440,1280,1024]){await page.setViewportSize({width,height:1000});const geometry=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,height:innerHeight,sidebar:document.querySelector('.sidebar').getBoundingClientRect().height,broken:[...document.images].filter(i=>!i.complete||i.naturalWidth===0).length,settingsIcon:document.querySelector('.sidebar a[href="/settings/llm"] img').getBoundingClientRect().width,toggle:document.querySelector('.llm-toggle img').getBoundingClientRect().width}));expect(geometry.scroll).toBeLessThanOrEqual(width);expect(geometry.sidebar).toBe(geometry.height);expect(geometry.broken).toBe(0);expect(geometry.settingsIcon).toBe(20);expect(geometry.toggle).toBe(65);}
 expect(errors).toEqual([]);
});
for (const action of ['stop','navigate']) {
test(`automatic verification ${action} stops queued tests and preserves completed results`,async({page})=>{
 await login(page);await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();let d=page.getByRole('dialog');await d.getByLabel('新的 API Key *').fill(key+'-'+action);await d.getByRole('button',{name:'保存新密钥',exact:true}).click();await expect(d).toHaveCount(0);
 let release;const gate=new Promise(resolve=>{release=resolve;});let calls=0;
 await page.route('**/api/v1/settings/llm/models/*/test',async route=>{calls++;await gate;await route.continue();});
 const first=page.waitForRequest(r=>/\/api\/v1\/settings\/llm\/models\/[^/]+\/test$/.test(r.url()));
 await page.getByRole('button',{name:'刷新模型列表',exact:true}).click();await first;
 if(action==='stop')await page.getByRole('button',{name:'停止后续测试',exact:true}).click();
 else await page.getByRole('link',{name:'项目管理',exact:true}).click();
 release();
 if(action==='stop')await expect(page.getByRole('status')).toContainText('自动验证已停止：已测试 1/3');
 await expect.poll(async()=>{const r=await page.request.get('/api/v1/settings/llm/models');return r.json().then(v=>v.data.filter(m=>m.verification_status==='available').length);}).toBe(1);
 expect(calls).toBe(1);
});
}
test('non administrator cannot see navigation or access settings APIs',async({page})=>{
 await login(page,'accept-reviewer');await expect(page.getByRole('link',{name:'系统设置',exact:true})).toHaveCount(0);await expect(page.getByText('仅系统管理员可访问大模型配置，请联系管理员。')).toBeVisible();expect((await page.request.get('/api/v1/settings/llm')).status()).toBe(403);
});

test('settings dropdowns and credential dialogs stay usable at every desktop size',async({page})=>{
 await login(page);
 const configuration=(await (await page.request.get('/api/v1/settings/llm')).json()).data;
 if(configuration.key_configured){await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'移除已保存 Key'}).click();const d=page.getByRole('dialog');await setChecked(d.getByRole('checkbox'), true);await d.getByRole('button',{name:'确认移除密钥'}).click();await expect(d).toHaveCount(0);}
 const directory=path.resolve('../docs/figma-ui/after');fs.mkdirSync(directory,{recursive:true});
 async function inViewport(locator){if(await locator.getAttribute('role')==='dialog')locator=page.locator('.modal:visible');await expect.poll(async()=>{const r=await locator.boundingBox(),v=page.viewportSize();return r.x>=0&&r.y>=0&&r.x+r.width<=v.width+1&&r.y+r.height<=v.height+1;}).toBe(true);const r=await locator.boundingBox();const v=page.viewportSize();expect(r.x).toBeGreaterThanOrEqual(0);expect(r.y).toBeGreaterThanOrEqual(0);expect(r.x+r.width).toBeLessThanOrEqual(v.width+1);expect(r.y+r.height).toBeLessThanOrEqual(v.height+1);}
 for(const width of [1440,1280,1024]){
  await page.setViewportSize({width,height:900});
  const trigger=page.locator('.llm-select-trigger');
  await trigger.click();let options=page.locator('#default-model-options');await expect(options).toBeVisible();await inViewport(options);
  await page.screenshot({path:path.join(directory,`llm-default-dropdown-${width}.png`)});
  await page.getByRole('heading',{name:'系统设置',exact:true}).click();await expect(options).toHaveCount(0);
  await trigger.click();await expect(options).toBeVisible();await page.keyboard.press('Escape');await expect(options).toHaveCount(0);await expect(trigger).toBeFocused();
  await trigger.click();await trigger.click();await expect(options).toHaveCount(0);
  await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();let d=page.getByRole('dialog');await inViewport(d);
  const input=d.getByLabel('新的 API Key *');await expect(input).toHaveValue('');await input.fill('ui-credential-dialog-synthetic-value');
  await d.getByRole('button',{name:'显示',exact:true}).click();await expect(input).toHaveAttribute('type','text');await d.getByRole('button',{name:'隐藏',exact:true}).click();await expect(input).toHaveAttribute('type','password');
  await page.screenshot({path:path.join(directory,`llm-key-dialog-${width}.png`)});
  await d.getByRole('button',{name:'取消',exact:true}).click();await expect(d).toHaveCount(0);
  await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();d=page.getByRole('dialog');await expect(d.getByLabel('新的 API Key *')).toHaveValue('');await page.keyboard.press('Escape');await expect(d).toHaveCount(0);
  await page.getByRole('button',{name:'＋ 手动添加模型',exact:true}).click();d=page.getByRole('dialog');await inViewport(d);await page.screenshot({path:path.join(directory,`llm-manual-dialog-${width}.png`)});await d.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'测试连接',exact:true}).click();d=page.getByRole('dialog');await expect(d).toContainText('未配置 API Key');await inViewport(d);await page.screenshot({path:path.join(directory,`llm-result-dialog-${width}.png`)});await d.getByRole('button',{name:'关闭结果',exact:true}).click();
 }
});

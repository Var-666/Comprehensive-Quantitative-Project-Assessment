import {test,expect} from '@playwright/test';
import crypto from 'node:crypto';
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
 await page.getByRole('button',{name:'刷新模型列表',exact:true}).click();await expect(page.getByRole('status')).toContainText('自动验证完成：已测试 3/3 个，2 个通过，1 个未通过');
 let row=page.getByRole('row').filter({hasText:'http-double-analysis'});await expect(row).toContainText('实际调用通过');
 await expect(page.getByRole('row').filter({hasText:'http-double-blocked'})).toContainText('当前账号无权限');
 await expect(page.getByRole('row').filter({hasText:'http-double-notice'})).toContainText('实际调用通过');expect(automaticTests).toHaveLength(3);
 await page.getByRole('button',{name:'刷新模型列表',exact:true}).click();await expect(page.getByRole('status')).toContainText('跳过 2 个已验证或已禁用模型');expect(automaticTests).toHaveLength(4);
 await page.getByRole('button',{name:/先连接服务并获取模型列表/}).click();await page.locator('#default-model-options').getByRole('button',{name:/HTTP替身：分析测试模型/}).click();
 await page.getByRole('combobox',{name:'通知与工作安排草稿',exact:true}).selectOption({label:'HTTP替身：通知测试模型'});
 await page.getByRole('switch',{name:'启用实际模型调用'}).click();await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','true');
 await page.reload();await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','true');await expect(page.getByRole('combobox',{name:'通知与工作安排草稿',exact:true})).not.toHaveValue('');
 await page.getByRole('row').filter({hasText:'http-double-analysis'}).getByRole('button',{name:'禁用',exact:true}).click();await expect(page.getByRole('alert')).toContainText('模型正被默认或业务场景引用');
 await page.getByRole('button',{name:'＋ 手动添加模型',exact:true}).click();d=page.getByRole('dialog');await page.screenshot({path:'test-results-llm/llm-manual-dialog.png'});await d.getByLabel('模型 ID *').fill('manual-http-double-id');await d.getByLabel('显示名称（可选）').fill('手动HTTP替身模型');await d.getByRole('button',{name:'保存模型',exact:true}).click();await expect(d).toHaveCount(0);
 row=page.getByRole('row').filter({hasText:'manual-http-double-id'});await expect(row).toContainText('手动录入');await expect(row).toContainText('尚未测试');await row.getByRole('button',{name:'删除',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'确认删除模型'}).click();await expect(row).toHaveCount(0);
 await page.screenshot({path:'test-results-llm/llm-settings-configured.png',fullPage:true});
 await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();d=page.getByRole('dialog');await expect(d.getByLabel('新的 API Key *')).toHaveValue('');await d.getByLabel('新的 API Key *').fill(key+'-replacement');await d.getByRole('button',{name:'保存新密钥',exact:true}).click();await expect(d).toHaveCount(0);await expect(page.getByRole('row').filter({hasText:'http-double-analysis'})).toContainText('尚未测试');
 await page.getByRole('button',{name:'设置 / 更换 Key',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'移除已保存 Key'}).click();d=page.getByRole('dialog');await d.getByRole('checkbox').check();await d.getByRole('button',{name:'确认移除密钥'}).click();await expect(d).toHaveCount(0);await expect(page.getByRole('switch')).toHaveAttribute('aria-checked','false');
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

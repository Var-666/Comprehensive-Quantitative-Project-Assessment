import {test,expect} from '@playwright/test';
async function login(page,username='accept-editor'){
 await page.goto('/metrics');
 await page.getByLabel('账号',{exact:true}).fill(username);
 await page.getByLabel('密码',{exact:true}).fill(process.env.ACCEPTANCE_PASSWORD);
 await page.getByRole('button',{name:'登录',exact:true}).click();
 await expect(page.getByRole('heading',{name:'项目量化评估',exact:true})).toBeVisible();
}
async function switchUser(page,user){await page.getByRole('button',{name:'退出登录'}).click();await login(page,user);}
async function selectReportProject(page){await page.getByRole('combobox',{name:'报告项目',exact:true}).selectOption({label:'P-H028 · 7500DWT 化学品船'});}

test('report service errors are visible and retry reuses the same submission key',async({page})=>{
 await login(page);await page.getByRole('link',{name:'AI 智能分析',exact:true}).click();await selectReportProject(page);await page.getByLabel('报告截止日').fill('2026-10-19');
 const keys=[];page.on('request',r=>{if(r.url().endsWith('/reports/draft'))keys.push(r.headers()['idempotency-key']);});
 const pattern='**/api/v1/projects/*/reports/draft';
 await page.route(pattern,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({success:false,error:{code:'MODEL_UNAVAILABLE',message:'模型服务暂时不可用，测试故障',fields:[],retryable:false},meta:{request_id:'browser-recovery-fixture'}})}));
 await page.getByRole('button',{name:'生成报告草稿',exact:true}).click();await expect(page.getByRole('alert')).toContainText('模型服务暂时不可用');await expect(page.getByRole('button',{name:'生成报告草稿',exact:true})).toBeEnabled();await expect(page.getByRole('status')).toHaveCount(0);await expect(page.getByLabel('报告截止日')).toHaveValue('2026-10-19');
 await page.unroute(pattern);await page.getByRole('button',{name:'生成报告草稿',exact:true}).click();await expect(page.getByRole('status')).toContainText('报告草稿已生成并保存');expect(keys).toHaveLength(2);expect(keys[0]).toBeTruthy();expect(keys[1]).toBe(keys[0]);
});
test('trial metrics trace their evidence and frozen reports require an independent reviewer',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await login(page);
 await page.getByLabel('业务统计截止日').fill('2026-10-19');
 await page.getByRole('button',{name:'计算评价',exact:true}).click();
 const row=page.getByRole('row').filter({hasText:'P-H028'});
 await expect(row).toContainText('93.3%');
 await expect(page.locator('.stat-grid')).toContainText('88.2%');
 await row.getByRole('button',{name:'评价明细'}).click();
 await page.getByLabel('评价分类').selectOption('late_completed');
 await page.getByRole('row').filter({hasText:'H028-N006'}).getByRole('button',{name:'证据追溯'}).click();
 let d=page.getByRole('dialog');
 await expect(d).toContainText('2026-10-12');await expect(d).toContainText('2026-10-15');await expect(d).toContainText('3 天');
 await d.getByRole('button',{name:'关闭追溯',exact:true}).click();
 await page.getByRole('button',{name:'保存评价快照'}).click();
 await expect(page.getByRole('status')).toContainText('已保存评价快照');
 await page.screenshot({path:'test-results/phase3-metrics.png',fullPage:true});
 await page.getByRole('button',{name:'生成阶段报告'}).click();
 await expect(page.getByLabel('报告截止日')).toHaveValue('2026-10-19');
 await expect(page.getByLabel('报告截止日')).toBeDisabled();
 await page.getByRole('button',{name:'生成报告草稿',exact:true}).click();
 await expect(page.locator('.report-preview')).toContainText('93.3');
 await expect(page.locator('.report-preview')).toContainText('Mock');
 await page.getByRole('button',{name:'提交报告审核'}).click();
 await expect(page.getByRole('button',{name:'独立报告审核'})).toBeDisabled();
 await switchUser(page,'accept-reviewer');
 await page.goto('/analysis');await selectReportProject(page);
 await page.getByRole('button',{name:'独立报告审核'}).click();
 d=page.getByRole('dialog');await d.getByLabel('报告审核依据 *').fill('独立核对冻结快照与原始Excel试算值');
 await d.getByRole('button',{name:'确认报告审核'}).click();
 await expect(d).toHaveCount(0);await expect(page.locator('.report-preview')).toContainText('已批准');
 const download=page.waitForEvent('download');await page.getByRole('link',{name:'导出报告 HTML'}).click();await expect((await download).suggestedFilename()).toMatch(/^report-.*\.html$/);
 await page.screenshot({path:'test-results/phase3-report.png',fullPage:true});
 for(const width of [1280,1024]){await page.setViewportSize({width,height:900});await expect(page.locator('.report-preview')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);}
 expect(errors).toEqual([]);
});

test('money needs extra authorization and actual amounts remain unknown until independent verification',async({page})=>{
 await login(page);await page.goto('/analysis');await selectReportProject(page);
 await page.getByRole('button',{name:'收付款记录',exact:true}).click();
 await expect(page.getByText('当前账户未获本项目金额访问授权。项目角色不会自动获得财务权限。')).toBeVisible();
 async function grant(name,write,verify){
  await page.getByRole('button',{name:'财务额外授权'}).click();const d=page.getByRole('dialog');
  await d.getByLabel('项目成员 *').selectOption({label:name});
  await d.getByRole('checkbox',{name:'金额读取',exact:true}).check();
  await d.getByRole('checkbox',{name:'财务录入',exact:true}).setChecked(write);
  await d.getByRole('checkbox',{name:'独立财务核实',exact:true}).setChecked(verify);
  await d.getByRole('button',{name:'保存财务记录'}).click();await expect(d).toHaveCount(0);
 }
 await grant('验收编制人员',true,true);await grant('验收审核人员',false,true);
 await page.getByRole('button',{name:'录入财务计划',exact:true}).click();
 let d=page.getByRole('dialog');await d.getByLabel('财务记录编号 *').fill('FIN-BROWSER-PLAN');await d.getByLabel('计划日期 *',{exact:true}).fill('2026-10-26');await d.getByLabel('计划金额 *',{exact:true}).fill('8000000.00');await d.getByLabel('币种（三位大写） *').fill('CNY');await d.getByLabel('计划依据 *').fill('浏览器虚构计划，非到账事实');await d.getByRole('button',{name:'保存财务记录'}).click();await expect(d).toHaveCount(0);
 await expect(page.getByText('待核实，不能认定为0',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'录入实际收付款',exact:true}).click();
 d=page.getByRole('dialog');await expect(d.getByLabel('实际金额 *',{exact:true})).toHaveValue('');await expect(d.getByLabel('实际发生日期 *')).toHaveValue('');
 await d.getByLabel('财务记录编号 *').fill('FIN-BROWSER-ACTUAL');await d.getByLabel('实际发生日期 *').fill('2026-10-01');await d.getByLabel('实际金额 *',{exact:true}).fill('100.11');await d.getByLabel('币种（三位大写） *').fill('CNY');await d.getByLabel('实际凭证来源 *').fill('浏览器虚构凭证，非真实收款');await d.getByLabel('关联财务计划').selectOption({label:'FIN-BROWSER-PLAN · CNY'});await d.getByRole('button',{name:'保存财务记录'}).click();await expect(d).toHaveCount(0);
 await expect(page.getByRole('button',{name:'独立财务核实',exact:true})).toBeDisabled();
 await switchUser(page,'accept-reviewer');await page.goto('/analysis');await selectReportProject(page);await page.getByRole('button',{name:'收付款记录',exact:true}).click();
 await page.getByRole('button',{name:'独立财务核实',exact:true}).click();d=page.getByRole('dialog');await d.getByLabel('财务核实依据 *').fill('另一人员独立核对浏览器测试凭证');await d.getByRole('button',{name:'确认财务核实'}).click();await expect(d).toHaveCount(0);await expect(page.getByRole('row').filter({hasText:'FIN-BROWSER-ACTUAL'})).toContainText('verified');
 await page.screenshot({path:'test-results/phase3-finance.png',fullPage:true});
});

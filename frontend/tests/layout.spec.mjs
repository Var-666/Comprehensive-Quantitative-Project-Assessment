import {test,expect} from '@playwright/test';

test('all eight screens keep the established navigation, desktop layout and usable assets',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await page.getByLabel('账号',{exact:true}).fill('accept-editor');await page.getByLabel('密码',{exact:true}).fill(process.env.ACCEPTANCE_PASSWORD);await page.getByRole('button',{name:'登录',exact:true}).click();await expect(page.getByRole('heading',{name:'项目总体概览',exact:true})).toBeVisible();
 const screens=[['/','项目总体概览','项目总览'],['/projects','项目管理','项目管理'],['/milestones','项目节点管理','节点管理'],['/actions','标准动作配置','标准动作'],['/tasks','提醒与待办','提醒与待办'],['/metrics','项目量化评估','量化评估'],['/analysis','AI 阶段报告工作台','AI 智能分析'],['/settings/llm','系统设置','系统设置']];
 for(const width of [1440,1280,1024]){
  await page.setViewportSize({width,height:900});
  for(const [path,title,nav] of screens){
   await page.goto(path);await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
   await expect(page.locator('.sidebar nav a.active')).toHaveText(nav);
   await page.waitForFunction(()=>[...document.images].every(i=>i.complete));
   const geometry=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,sidebar:document.querySelector('.sidebar').getBoundingClientRect().toJSON(),header:document.querySelector('header').getBoundingClientRect().toJSON(),main:document.querySelector('main').getBoundingClientRect().toJSON(),broken:[...document.images].filter(i=>!i.naturalWidth).map(i=>i.getAttribute('src')),distorted:[...document.images].filter(i=>i.getBoundingClientRect().width>0&&(Math.abs(i.getBoundingClientRect().width-i.naturalWidth)>0.5||Math.abs(i.getBoundingClientRect().height-i.naturalHeight)>0.5)).map(i=>i.getAttribute('src')),tables:[...document.querySelectorAll('.table-wrap')].map(t=>({width:t.clientWidth,scroll:t.scrollWidth,overflow:getComputedStyle(t).overflowX}))}));
   expect(geometry.scroll).toBeLessThanOrEqual(width);expect(geometry.sidebar.height).toBe(900);expect(geometry.sidebar.y).toBe(0);expect(geometry.sidebar.width).toBe(236);expect(geometry.header.x).toBe(236);expect(geometry.main.x).toBe(236);expect(geometry.broken).toEqual([]);expect(geometry.distorted).toEqual([]);
   for(const table of geometry.tables)if(table.scroll>table.width)expect(['auto','scroll']).toContain(table.overflow);
   if(width===1440)await page.screenshot({path:`test-results/acceptance-${path.replaceAll('/','-')||'overview'}.png`,fullPage:true});
  }
 }
 expect(errors).toEqual([]);
});

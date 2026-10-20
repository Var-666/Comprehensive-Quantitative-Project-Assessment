import {defineConfig} from '@playwright/test';
import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'project-llm-https-'));
execFileSync('../.venv/bin/python',['../scripts/init_llm_security.py','--directory',directory,'--no-env']);
process.env.ACCEPTANCE_PASSWORD||=crypto.randomBytes(24).toString('base64url');
const cert=path.join(directory,'localhost.crt'),key=path.join(directory,'localhost.key');
export default defineConfig({
 testDir:'./tests-llm',outputDir:'test-results-llm',workers:1,timeout:60000,
 use:{baseURL:'https://127.0.0.1:5176',channel:'chrome',headless:true,ignoreHTTPSErrors:true,viewport:{width:1440,height:1000},screenshot:'only-on-failure'},
 webServer:[
 {command:`cd ../backend && ../.venv/bin/alembic upgrade head && ../.venv/bin/python -m app.acceptance_seed && ../.venv/bin/uvicorn browser_llm_app:app --app-dir tests --host 127.0.0.1 --port 8012 --ssl-certfile "${cert}" --ssl-keyfile "${key}"`,url:'https://127.0.0.1:8012/api/v1/health',ignoreHTTPSErrors:true,env:{PYTHONPATH:'.',DATABASE_URL:`sqlite:///${path.join(directory,'test.db')}`,APP_ENV:'test',DEMO_MODE:'true',ACCEPTANCE_PASSWORD:process.env.ACCEPTANCE_PASSWORD,COOKIE_SECURE:'true',ALLOWED_ORIGINS:'https://127.0.0.1:5176,https://127.0.0.1:8012',LLM_ENCRYPTION_KEY_FILE:path.join(directory,'llm-master.key'),AI_PROVIDER:'mock',AI_BASE_URL:'',AI_MODEL:'',AI_API_KEY:'',LLM_ENCRYPTION_KEY:''},reuseExistingServer:false},
 {command:'npm run dev -- --port 5176',url:'https://127.0.0.1:5176',ignoreHTTPSErrors:true,env:{API_PROXY_TARGET:'https://127.0.0.1:8012',VITE_TLS_CERT_FILE:cert,VITE_TLS_KEY_FILE:key,NODE_EXTRA_CA_CERTS:cert},reuseExistingServer:false}
 ]
});

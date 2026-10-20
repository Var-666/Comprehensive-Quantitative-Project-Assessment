# 项目总体量化评估智能体 · V0.4.0

第一、二、三阶段版本：Vue 3 / TypeScript / Vite / Pinia / Vue Router + FastAPI / SQLAlchemy / Alembic。页面连接真实 API 与数据库，所有业务接口强制登录、项目授权与服务端权限校验。计划编制人与批准人、实际提交人与核实人必须分离。验收基线已由用户于2026-10-20确认，见 [第一阶段基线](docs/PHASE1_BASELINE.md) 与 [逐项验收表](docs/PHASE1_ACCEPTANCE.md)。

## 本地启动

需要 Python 3.12+、Node.js 20.19+（或 22+）、npm。当前环境使用 Python 3.12 与 Node 20.9 完成过构建；推荐使用受支持的较新 Node LTS。

```bash
# 在仓库根目录执行。可用 PYTHON_BIN 指定 Python 路径。
./scripts/setup.sh
cp .env.example .env
# 显式加载提供的模拟 Excel：3 个项目、67 个节点；再次运行不覆盖。
./scripts/seed.sh
.venv/bin/python scripts/create_local_accounts.py
./scripts/dev.sh
```

前端：<http://127.0.0.1:5173>；OpenAPI：<http://127.0.0.1:8000/docs>。SQLite 默认数据库为仓库根目录 `development.db`，不进 Git。停止开发脚本使用 Ctrl+C，数据不丢失。

本机初始化脚本生成三个独立账号 local-editor、local-reviewer、local-viewer，分别承担编制/管理、审核、只读角色。随机密码仅保存在根目录 `.local-access.json`（0600权限、忽略Git和Docker构建），不输出到终端或写进源码。重复执行不会重置账号。先用 local-editor 登录，需批准或核实时退出并使用 local-reviewer；不能自审。

配置实际人员账号无需使用样本：在 backend 目录运行 `../.venv/bin/python -m app.admin <账号> --name <姓名> --system-admin`，按提示输入密码。审核账号省略 `--system-admin`，再到项目详情“项目成员与权限”授权。账号保存在独立 auth_credentials 表，原 users 人员目录不保存密码。没有开放注册和默认密码。

若 8000 已被占用：

```bash
API_PORT=8001 ./scripts/dev.sh
```

此时文档地址为 <http://127.0.0.1:8001/docs>，脚本自动调整前端 API 代理。

也可以分别运行：

```bash
# 终端一
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
# 终端二，从仓库根目录开始
cd frontend
API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev
```

`requirements.lock.txt` 和 `package-lock.json` 固定本次实际验证的依赖；日常安装优先使用这两个锁文件。

## PostgreSQL / Docker Compose

目标数据库为 PostgreSQL，ID 使用原生 UUID，审计时间为 timestamptz，业务日期为 date。SQLite 使用 UUID 文本及 UTC 时间兼容存储；API 始终返回带时区时间。没有使用 SQLite 专有业务查询。

```bash
cp .env.example .env
# 编辑 .env，填写随机的 POSTGRES_PASSWORD（建议仅用 URL 安全字符）
docker compose up --build
# 显式初始化开发样本
docker compose exec backend python -m app.seed
# 交互创建两个独立账号，密码由终端输入，不写入命令
docker compose exec backend python -m app.admin operator --name 项目管理人员 --system-admin --grant-samples admin
docker compose exec backend python -m app.admin reviewer --name 项目审核人员 --grant-samples reviewer
```

Compose 将端口绑定到 127.0.0.1。容器启动执行 Alembic 迁移；不自动加载模拟数据。数据库数据保存在 Docker 命名卷。Compose 前端是开发服务器，仅用于本机验收。若使用已有 PostgreSQL，在 `.env` 填写 `DATABASE_URL=postgresql+psycopg://...`，随后运行迁移和启动脚本。

已在官方 PostgreSQL 16 容器上实际运行迁移往返、alembic check、模拟数据初始化与完整 pytest；不再以离线SQL代替实例测试。可重复验证：`.venv/bin/python scripts/verify_postgres.py`。脚本使用随机容器名、随机密码及隔离数据库，结束后仅删除自己的测试容器。

前后端 Docker 镜像可通过 `docker compose build` 构建；完整容器栈浏览器验收使用 `.venv/bin/python scripts/verify_compose.py`，随机端口、随机项目名及数据卷避免影响开发环境，结束后清理本次验收资源。运行前需已构建镜像、本机安装 Chrome 和本地测试依赖。

## 已实现及操作方式

- **项目管理**：分页、编号/名称/负责人搜索、状态与类型筛选、新建、编辑、详情、归档。编号数据库唯一，修改需要 If-Match。归档保留历史，可在编辑中恢复状态。
- **节点管理**：选项目和计划版本，创建/编辑草稿节点，节点类型、责任部门、日期性质及来源，按计划日期排序的可滚动时间轴，详情与变更留痕。
- **计划版本**：项目创建时生成 V1 草稿；独立审核人员批准后只读。新建变更草稿复制当前版本**全部节点快照**；修改不覆盖旧版。创建和修改该版计划的全部人员均不能批准自己的版本。一次仅保留一个草稿，合同、内部计划、待确认日期明确区分。
- **实际记录**：详情中单独提交完成事实与实际日期。提交不等于完成；由独立审核人员核实、退回或标记争议并留痕。新提交不会替换先前已核实事实。来源说明不是正式附件；第一阶段未要求的证据文件存储未冒充实现。
- **身份与权限**：Argon2密码哈希、数据库可撤销登录会话、HttpOnly/SameSite Cookie、CSRF、登录失败锁定，项目 admin/editor/reviewer/viewer 角色。未授权项目在列表和统计中不可见，直接访问也被拒绝；角色撤销对已有登录会话立即生效。
- **Excel 导入**：上传、选择工作表/表头行、编辑字段映射、逐行验证、错误预览与 CSV 下载、人工勾选确认、事务写入、批次与拒绝提交原因留痕、幂等提交。禁止自动覆盖。
- **项目总览**：只展示数据库中真实台账计数。标准动作、提醒与待办已接入真实后端；量化评估与AI智能分析留待第三阶段，明确“尚未实现”。

### Excel 使用

提供的工作簿表头在第 **6** 行；项目表为 `01_项目台账`，节点表为 `02_节点计划`。导入弹窗默认采用这些映射，可改列名，选填映射可清空。

项目导入必填 `project_code / project_name`。节点导入必填 `milestone_code / milestone_name / node_type_code / planned_date`，必须在节点管理选择**本项目草稿**。节点表有项目编号时必须与选择项目一致。模拟工作簿含三个项目的混合节点，请按项目拆分或过滤后上传；系统不会将其他项目节点误写入当前项目。

人员和部门名称必须与目录匹配，不自动造人、造部门。初始化样本时从模拟 Excel 配置演示目录；全新空库可以先创建不指定负责人/部门的项目。正式目录维护与统一组织集成待确认。

限制：仅 `.xlsx`，最大 5MB、2,000 数据行，解压后不超过 30MB；输入映射列不接受公式，非映射的统计公式不导入。**按已确认基线整批原子写入**：任一错误/重复行均不写业务表，修正后重新预览；部分成功模式被禁用。提交会再次校验权限和数据，预览之后产生的编号冲突也不会覆盖数据。预览批次归属上传者，原始行、校验错误、文件SHA256和提交失败原因持久化。节点导入还必须具有所选项目编辑权限。

### 模拟样本的边界

`./scripts/seed.sh` 是显式开发夹具加载器，严格读取原 Excel 的计划日期及核实情况：P-H028 26 个节点、P-H031 24 个节点、P-H014 17 个节点。该脚本只加载第一阶段实体。第二阶段动作草稿使用下方单独命令加载，不导入未经确认的历史通知状态、财务或评价。

P-H028 来源仅有 V2，不虚构缺失的 V1；下一草稿从 V3 开始。“需关注”是原始关注说明，不与生命周期混用，暂以草稿保存；该映射集中在导入/样本加载器。含“合同约定（演示，未核实）”的日期保存为 unconfirmed，不变成已核实合同事实。样本的“已核实”均明确标注为虚构夹具，不是真实审核证据。

## 第二阶段操作

权限与计算边界见 [第二阶段基线](docs/PHASE2_BASELINE.md)。七个主菜单保持原名，新增功能位于“标准动作”“提醒与待办”及节点详情。

1. 用系统管理员在“标准动作”编制模板及动作项，保存草稿并“提交业务确认”；换独立审核账号批准。可选按项目类型限制适用范围。已批准版本只读，可复制为新版本。
2. 在同页“工作日历”编制企业逐日标记（如需工作日），独立批准。周末预填不是正式节假日结论。再配置“提醒规则”的天数、日历版本、接收角色和追补窗口，并独立批准。
3. 在节点详情“关联动作模板”选择已批准且适用的动作，保留快照。已有动作不会通过取消勾选被无痕删除；调整使用新计划或模板版本。草稿计划不会触发提醒。
4. “提醒与待办 → 提醒扫描”可预览每个节点的触发日期与跳过原因，系统管理员可对有授权的项目确认生成草稿与待办；重复扫描不会重复创建。生产环境生成只接受当天业务日期。
5. 编辑通知草稿并提交审核，另一账号核对内容版本、依据和接收人后批准。此时仍是“审核通过待发送”；项目编辑另行“发布站内通知”，收件人登录“站内收件箱”查看并标记已读。外部渠道被后端拒绝。
6. “执行任务 → 处理任务”明确分派有项目编辑权限的执行人；执行人填写处理情况、证据引用和声称完成情况。另一项目审核人员可接受、退回或标记异议。核实任务不会写节点实际记录。

开发脚本默认同时启动独立扫描进程，每60秒按Asia/Shanghai当前业务日扫描，只使用批准配置，生成草稿/待办，不审核、不发送。可用 `START_REMINDER_WORKER=0 ./scripts/dev.sh` 只启动前后端，或单独运行：

```bash
cd backend
../.venv/bin/python -m app.worker --once
# 常驻扫描；Ctrl+C停止
../.venv/bin/python -m app.worker --interval 60
# 可选：加载原Excel的11个模拟模板草稿/24项动作，重复运行不覆盖。
../.venv/bin/python -m app.phase2_seed --username local-editor
```

模拟动作保留“待业务确认”和来源规则说明；不自动批准、绑定，也不虚构正式接收角色、核实标准或节假日日历。Compose包含独立worker服务，等待backend健康后启动。

新增API（完整参数见OpenAPI）：

| 功能 | 路径（均为 `/api/v1` 前缀） |
| --- | --- |
| 模板 | `GET/POST /action-templates`、`GET/PATCH /action-templates/{id}` |
| 规则 | `GET/POST /reminder-rules`、`PATCH /reminder-rules/{id}`、`POST /reminder-rules/preview-trigger` |
| 日历 | `GET/POST /work-calendars`、`GET/PATCH /work-calendars/{id}` |
| 配置审核 | 上述三类资源的 `POST /{资源}/{id}/submit-review`、`/review`、`/retire` |
| 节点动作及取消 | `GET /milestones/{id}/suggested-actions`、`GET/POST /milestones/{id}/action-links`、`POST /milestones/{id}/cancel` |
| 扫描 | `POST /reminder-jobs/simulate`、`POST /reminder-jobs/run`、`GET /reminders` |
| 通知 | `GET /notifications`、`GET /notifications/{id}`、`PATCH /notifications/{id}/draft`、`POST /notifications/{id}/submit-review`、`/review`、`/dispatch` |
| 收件箱 | `GET /inbox`、`POST /inbox/{id}/read` |
| 任务反馈 | `GET /tasks`、`GET/PATCH /tasks/{id}`、`POST /tasks/{id}/feedback`、`POST /task-feedback/{id}/verify`、`GET /tasks/{id}/audit-events` |

配置编辑/审核、通知更新/审核/发送、任务更新/反馈均使用If-Match；生成与站内发布另有数据库防重约束。执行人必须有项目编辑权限，不能通过任务分派绕过只读角色限制。

## API

统一前缀 `/api/v1`，返回 `{success,data,meta}` 或 `{success:false,error,meta}`，含服务器生成的 request_id。异常不向页面泄露SQL、密码或内部路径。API操作人来自已认证会话，不接受客户端指定提交人、审核人或actor请求头。登录返回HttpOnly会话Cookie和CSRF令牌；后续写请求携带 `X-CSRF-Token`。只有健康检查与登录接口无需已有会话。

| 功能 | 可用接口 |
|---|---|
| 基础配置 | `GET /health`、`/config`、`/departments`、`/users`、`/dictionaries/node-types` |
| 登录会话 | `POST /auth/login`、`GET /auth/me`、`POST /auth/logout` |
| 项目授权 | `GET/PUT /projects/{id}/members` |
| 项目 | `GET/POST /projects`、`GET/PATCH/DELETE /projects/{id}`、`GET /projects/{id}/overview` |
| 项目统计/审计 | `GET /summary`、`GET /projects/{id}/audit-events` |
| 计划版本 | `GET/POST /projects/{id}/plan-versions`、`POST /plan-versions/{id}/activate`（独立批准） |
| 节点 | `GET/POST /projects/{id}/milestones`、`GET /milestones/{id}`、`PATCH /milestones/{id}/plan-item` |
| 实际与核实 | `POST /milestones/{id}/actuals`、`POST /milestone-actuals/{id}/verify`（独立核实） |
| Excel | `POST /imports/preview`、`GET /imports/{id}`、`POST /imports/{id}/commit`、`GET /imports/{id}/errors` |

PATCH 当前接受完整可编辑表单，不接受未知字段。项目编辑/归档、新草稿、节点编辑和演示生效需 `If-Match: <row_version>`；冲突返回 409，用户刷新后重新填写。导入确认需 `Idempotency-Key` 和预览摘要；相同键同载荷返回原结果，不同载荷返回 409。单次项目或节点创建重复请求由业务编号唯一约束拒绝，前端保存时禁用重复点击。

## 验证

```bash
./scripts/check.sh
# 使用本机 Google Chrome，临时 SQLite + 8011/5174 端口，不触碰开发数据库
cd frontend
npm run test:e2e
```

端到端测试需已安装 Google Chrome；也可在 Playwright 配置中改为已安装的 Chromium。pytest 的 `TEST_DATABASE_URL` 只能指向**专用可清空测试库**，用例会建表及清理表；不要指向业务库。

生产配置须 `APP_ENV=production`、`DEMO_MODE=false`、PostgreSQL及 `COOKIE_SECURE=true`，并设置真实HTTPS域名的 `ALLOWED_ORIGINS`；企业SSO/组织同步和证据存储是后续集成，不以样本账号代替企业实际人员。

测试意图涵盖：防止并发覆盖、保存历史计划、禁止跨项目版本、实际提交不代表核实、导入预览不写业务表、整批原子性、重复提交防重、预览后冲突二次检查、异常文件/公式输入拒绝，以及对照全部 67 个样本节点日期和核实事实。第二阶段另有确定性提醒、工作日历、版本失效、审发分离、任务与反馈测试；第三阶段增加Excel试算核对、冻结证据、独立报告审核、金额授权/核实、模型合约与输出拒绝测试。

第二阶段执行记录、限制及缺失依据见 [第二阶段验收](docs/PHASE2_ACCEPTANCE.md)；第一阶段历史交付见 [docs/DELIVERY.md](docs/DELIVERY.md)。

## 目录

```text
backend/app/            配置、Schema、核心模型、业务服务、导入服务、API、样本加载
backend/alembic/        可审阅的固定迁移
backend/tests/          pytest API/业务意图测试
frontend/src/           视图、共用表单/弹窗、类型、API 客户端、Pinia 字典
frontend/public/icons/  Figma 原型本地 SVG 资源
frontend/tests/         浏览器端到端测试
scripts/               安装、迁移、开发启动、样本初始化与检查
docs/                  依据、取舍与实际验收记录
```


## 第三阶段操作

规则见 [第三阶段基线](docs/PHASE3_BASELINE.md)，实际验证记录见 [第三阶段验收](docs/PHASE3_ACCEPTANCE.md)。升级已有数据库先在 backend 运行 `../.venv/bin/alembic upgrade head`，开发启动方式不变。

1. “量化评估”选择业务截止日并计算；原始样本选择2026-10-19。项目明细可按类别筛选、查看节点来源/核实记录、保存及读取历史快照。试算按期率与核实覆盖率分别展示，空分母显示“—”。CSV导出来自当前权限范围的后端计算。
2. “AI 智能分析”选项目、截止日和报告类型，生成冻结事实报告草稿，提交审核，再换另一审核账号批准/退回。可查看事实引用及审核记录，导出HTML（保留Mock/审核状态，浏览器可打印）。无生效计划不能生成报告。
3. “收付款记录”页签由管理员给已有成员额外授权，编辑分别录入计划和实际；获额外核实权的另一项目审核人核实实际凭证。未核实实际不加入确认金额。含金额报告需勾选且有财务读取权；财务读取撤销后报告访问、导出也拒绝。
4. “提醒与待办”草稿支持AI整理，原事实快照不变，仍需独立审核和单独站内发送。

可选加载Excel06虚构财务数据（不自动授权任何人）：

```bash
cd backend
../.venv/bin/python -m app.phase3_seed --currency CNY
# 容器环境：docker compose exec backend python -m app.phase3_seed --currency CNY
```

币种是命令调用者明确提供的演示假设，原表没有单独币种字段。仅development/test + DEMO_MODE=true可执行，6条计划和1条有发生事实的实际记录；重复不覆盖。

默认 `AI_PROVIDER=mock` 不调用模型。真实模式配置 `.env` 中 `AI_PROVIDER=openai_compatible`、`AI_BASE_URL`（HTTPS，包含例如/v1前缀）、`AI_MODEL`、`AI_API_KEY`，开启 `AI_EXTERNAL_ENABLED=true` 并重启服务；页面还须本次显式同意。端点须支持 `/chat/completions` 严格JSON Schema，具体模型由部署方选择。仅外送事实ID/类别/类型，正文留在本系统；模型不能自由改写事实或补充数字。网络/格式错误会明确失败，不冒充Mock成功。密钥不返回前端，不写日志或Git。未配置真实模型时，测试仅覆盖Mock及HTTP传输合约替身。

| 新增功能 | `/api/v1` 路径 |
|---|---|
| 试算与导出 | `GET /metrics/summary?as_of=`、`GET /metrics/export?as_of=` |
| 项目评价/证据 | `GET /projects/{id}/metrics`、`/metric-evidence`（as_of、计划版本/快照、类别、分页） |
| 冻结快照 | `GET/POST /projects/{id}/metric-snapshots`、`GET /metric-snapshots/{id}` |
| 财务权限/事实 | `GET/PUT /projects/{id}/financial-access`、`GET /projects/{id}/financial-records?as_of=`、`POST /projects/{id}/financial-plans`、`/financial-actuals`、`POST /financial-actuals/{id}/verify` |
| 报告 | `POST /projects/{id}/reports/draft`（Idempotency-Key）、`GET /projects/{id}/reports`、`GET /reports/{id}`、`POST /reports/{id}/submit-review`、`/review`、`GET /reports/{id}/export` |
| 模型配置/通知整理 | `GET /ai/config`（无密钥）、`POST /notifications/{id}/ai-draft` |

报告提交/审核、财务核实和通知整理要求 If-Match。报告与通知模型整理最多持有一次请求的项目事务锁和配置超时（默认20秒），以避免审核/授权撤销和生成之间竞态；无后台自动外送或自动重试。当前报表按计算时已核实事实复算截止日，不提供历史知情时间重放或完整会计台账。


## 系统设置 · 大模型配置

新增独立“系统设置”导航，仅系统管理员可见；原七个业务模块保持原流程。配置预置 `https://maas-api.cmhk.com/v1`，不预置模型名称或API Key。完整接口、权限、兼容迁移及测试依据见 [大模型配置交付记录](docs/LLM_CONFIGURATION.md)。

密钥必须通过HTTPS提交。本机首次准备并启动：

```bash
.venv/bin/pip install -r backend/requirements.lock.txt
npm --prefix frontend ci
./scripts/dev-https.sh
```

浏览器访问 **https://127.0.0.1:5175/settings/llm**，API文档 **https://127.0.0.1:8002/docs**。本机脚本生成自签开发证书，浏览器需信任该本机证书；仅供本地开发，正式环境使用企业认可的可信TLS证书。

按用户后续要求，本机也可直接使用 **http://127.0.0.1:5173/settings/llm**：运行 `./scripts/dev.sh`（本机8000端口被占用时使用 `API_PORT=8001 ./scripts/dev.sh`）。该脚本显式设置 `LLM_ALLOW_LOCAL_HTTP_CREDENTIALS=true`，只对development/test环境、回环客户端及localhost/127.0.0.1/::1主机开放Key管理，保留管理员权限、CSRF、加密与脱敏要求；不读取X-Forwarded-For作为例外依据。生产环境即使打开此开关也拒绝HTTP提交。可用 `LLM_ALLOW_LOCAL_HTTP_CREDENTIALS=false ./scripts/dev.sh`关闭例外。初次使用仍须初始化加密主密钥，方法见下文。

`init_llm_security.py` 仅生成加密主密钥与本地TLS证书，不生成企业API Key。主密钥保存在忽略Git/Docker构建的 `.local-secrets/llm-master.key`（0600），`.env`只保存其路径引用。生产由部署环境注入 `LLM_ENCRYPTION_KEY` 或受控 `LLM_ENCRYPTION_KEY_FILE`；妥善保管并备份主密钥，丢失后不能解密既有Key，需重新配置凭据。API Key只通过页面加密写数据库，不放配置文件。

操作顺序：

1. 系统管理员进入“系统设置”，确认服务地址并保存。URL仅允许部署白名单中的精确HTTPS域名与端口。
2. “设置 / 更换 Key”输入真实账户Key，保存后页面只显示配置状态和更新时间。
3. “测试连接”检查服务与凭据；“刷新模型列表”查询实际 `/models`，随后自动串行验证尚未通过当前凭据验证的已启用模型，每模型执行一次短调用。页面显示进度与结果，已通过模型跳过；单模型权限/格式问题不妨碍其余模型，认证失败、限流、网络或服务异常暂停批次。可点击“停止后续测试”，离开页面也不再发起后续调用，已完成结果保留。服务端刷新API仍只负责发现；自动调度由网页复用既有模型测试API完成，不是常驻后台任务。401/403/404/429/5xx及网络错误分别提示；404不当作Key无效。
4. 自动列表不可用时，“手动添加模型”填写服务商提供的准确ID，仍可单独点“测试模型”验证或重测。每次最多128个输出token；推理模型会先消耗思考token，若达到上限，明确提示截断，不误报格式不兼容、不自动重试或标记可用。列表来自账户授权，自动测试仅验证当前文本生成接口，向量/重排模型可能不适用于该场景。
5. 已启用且通过当前凭据调用测试的模型才可选为默认或业务场景模型；“项目阶段智能分析”和“通知与工作安排草稿”可分别选择或跟随默认模型。引用中的模型不能直接禁用或删除，先改选或取消引用。
6. 选择真实MaaS模式并启用业务调用。报告和通知仍要求本次明确同意外送，且仅传事实ID/类别/类型。模型不修改项目、合同、计划、实际资金或评价结果。

配置变更立即用于新请求，无需重启；在途请求可继续使用开始时的配置。更换Key会将模型验证状态重置为未测试，重测后使用新Key；移除Key停止后续实际调用。地址变更清除旧Key及默认/场景选择，并隔离旧地址模型。操作审计与调用日志均脱敏，不记录Key、提示词、正文或平台原始异常。

优先级：**数据库管理员配置 > 旧环境配置 > 初始Mock**。无管理员配置时兼容原有 `AI_*` 环境模式；发现旧配置时必须明确确认接管，或通过“迁移旧环境配置”加密导入。迁移后的模型为手动未测试、实际调用关闭；已有管理员配置不允许被旧环境覆盖，Web移除Key后不会回退环境Key。`AI_EXTERNAL_ENABLED`适用于旧环境模式；数据库模式由管理员的启用操作授权，业务每次外送同意仍保留。

旧环境的安全自定义地址会原样显示；若未列入新白名单，页面明确提示运维授权，阻止保存Key、迁移和调用，不会自动改成CMHK地址。SQLite升级需3.35或更新版本；迁移保留既有报告、审核关系与检查约束，回滚遇到超长模型ID会停止，避免截断历史来源。

部署地址安全：`LLM_ALLOWED_ORIGINS`默认仅 `https://maas-api.cmhk.com`，可由运维显式扩展精确HTTPS origin；如获准域名解析到企业专用内网，还需在 `LLM_PRIVATE_ORIGINS`显式授权。回环、云元数据、链路本地和保留地址始终拒绝，不跟随重定向，不关闭TLS验证、不读取环境代理。企业平台若不是该兼容格式，应依据实际文档扩展 `llm_provider.py`，目前不声称已验证CMHK全部兼容。

本机代理若把该域名解析为 `198.18.0.0/15` 虚拟IP，也会触发非公网限制。先确认准确域名和TLS连接；获授权后在本机 `.env` 设置 `LLM_PRIVATE_ORIGINS=https://maas-api.cmhk.com` 并重启后端即可复用现有策略。无需把Key写回 `.env`、修改全局代理或关闭TLS验证；该授权只覆盖准确origin，不自动授权其他域名、端口或重定向目标。

可选本机HTTPS容器栈：

```bash
.venv/bin/python scripts/init_llm_security.py
# 先配置POSTGRES_PASSWORD；仅本机开发证书和挂载，不是正式部署模板。
docker compose -f compose.yaml -f compose.https.yaml up --build -d
# 访问 https://127.0.0.1:5173/settings/llm
```

新增验证命令：

```bash
npm --prefix frontend run test:llm
.venv/bin/python scripts/verify_llm_https.py
```

HTTPS浏览器测试使用独立的 `browser_llm_app` 测试入口与MockTransport，仅允许APP_ENV=test，不在产品入口启用。结果与真实CMHK平台连接严格区分；真实Key未配置时不会请求平台，也不会显示连接成功。`test:llm`的Chrome仅信任本地测试自签证书，MaaS客户端TLS验证保持开启。

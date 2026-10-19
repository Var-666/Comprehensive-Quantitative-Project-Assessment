# 项目总体量化评估智能体 · V0.1.1

第一阶段验收版本：Vue 3 / TypeScript / Vite / Pinia / Vue Router + FastAPI / SQLAlchemy / Alembic。页面连接真实 API 与数据库，所有业务接口强制登录、项目授权与服务端权限校验。计划编制人与批准人、实际提交人与核实人必须分离。验收基线已由用户于2026-10-20确认，见 [第一阶段基线](docs/PHASE1_BASELINE.md) 与 [逐项验收表](docs/PHASE1_ACCEPTANCE.md)。

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

前后端 Docker 镜像可通过 `docker compose build` 构建；完整三容器浏览器验收使用 `.venv/bin/python scripts/verify_compose.py`，随机端口、随机项目名及数据卷避免影响开发环境，结束后清理本次验收资源。运行前需已构建镜像、本机安装 Chrome 和本地测试依赖。

## 已实现及操作方式

- **项目管理**：分页、编号/名称/负责人搜索、状态与类型筛选、新建、编辑、详情、归档。编号数据库唯一，修改需要 If-Match。归档保留历史，可在编辑中恢复状态。
- **节点管理**：选项目和计划版本，创建/编辑草稿节点，节点类型、责任部门、日期性质及来源，按计划日期排序的可滚动时间轴，详情与变更留痕。
- **计划版本**：项目创建时生成 V1 草稿；独立审核人员批准后只读。新建变更草稿复制当前版本**全部节点快照**；修改不覆盖旧版。创建和修改该版计划的全部人员均不能批准自己的版本。一次仅保留一个草稿，合同、内部计划、待确认日期明确区分。
- **实际记录**：详情中单独提交完成事实与实际日期。提交不等于完成；由独立审核人员核实、退回或标记争议并留痕。新提交不会替换先前已核实事实。来源说明不是正式附件；第一阶段未要求的证据文件存储未冒充实现。
- **身份与权限**：Argon2密码哈希、数据库可撤销登录会话、HttpOnly/SameSite Cookie、CSRF、登录失败锁定，项目 admin/editor/reviewer/viewer 角色。未授权项目在列表和统计中不可见，直接访问也被拒绝；角色撤销对已有登录会话立即生效。
- **Excel 导入**：上传、选择工作表/表头行、编辑字段映射、逐行验证、错误预览与 CSV 下载、人工勾选确认、事务写入、批次与拒绝提交原因留痕、幂等提交。禁止自动覆盖。
- **项目总览**：只展示数据库中真实台账计数。其余四个主模块保留菜单并明确“尚未实现”，没有伪造提醒、财务指标或 AI 结果。

### Excel 使用

提供的工作簿表头在第 **6** 行；项目表为 `01_项目台账`，节点表为 `02_节点计划`。导入弹窗默认采用这些映射，可改列名，选填映射可清空。

项目导入必填 `project_code / project_name`。节点导入必填 `milestone_code / milestone_name / node_type_code / planned_date`，必须在节点管理选择**本项目草稿**。节点表有项目编号时必须与选择项目一致。模拟工作簿含三个项目的混合节点，请按项目拆分或过滤后上传；系统不会将其他项目节点误写入当前项目。

人员和部门名称必须与目录匹配，不自动造人、造部门。初始化样本时从模拟 Excel 配置演示目录；全新空库可以先创建不指定负责人/部门的项目。正式目录维护与统一组织集成待确认。

限制：仅 `.xlsx`，最大 5MB、2,000 数据行，解压后不超过 30MB；输入映射列不接受公式，非映射的统计公式不导入。**按已确认基线整批原子写入**：任一错误/重复行均不写业务表，修正后重新预览；部分成功模式被禁用。提交会再次校验权限和数据，预览之后产生的编号冲突也不会覆盖数据。预览批次归属上传者，原始行、校验错误、文件SHA256和提交失败原因持久化。节点导入还必须具有所选项目编辑权限。

### 模拟样本的边界

`./scripts/seed.sh` 是显式开发夹具加载器，严格读取原 Excel 的计划日期及核实情况：P-H028 26 个节点、P-H031 24 个节点、P-H014 17 个节点。只加载第一阶段实体，动作/通知/财务/评价工作表不写入数据库。

P-H028 来源仅有 V2，不虚构缺失的 V1；下一草稿从 V3 开始。“需关注”是原始关注说明，不与生命周期混用，暂以草稿保存；该映射集中在导入/样本加载器。含“合同约定（演示，未核实）”的日期保存为 unconfirmed，不变成已核实合同事实。样本的“已核实”均明确标注为虚构夹具，不是真实审核证据。

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

测试意图涵盖：防止并发覆盖、保存历史计划、禁止跨项目版本、实际提交不代表核实、导入预览不写业务表、整批原子性、重复提交防重、预览后冲突二次检查、异常文件/公式输入拒绝，以及对照全部 67 个样本节点日期和核实事实。第二/三阶段的提醒与指标用例未实现、未声称通过。

具体执行记录、限制及缺失依据见 [docs/DELIVERY.md](docs/DELIVERY.md)。

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

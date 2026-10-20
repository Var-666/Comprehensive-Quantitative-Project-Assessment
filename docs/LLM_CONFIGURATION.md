# 大模型配置管理交付 · V0.4.0

任务依据：本轮用户附件《大模型配置管理与可用模型自动获取》，以及用户确认的CMHK地址 `https://maas-api.cmhk.com/v1`。沿用现有Vue/FastAPI/SQLAlchemy/认证/CSRF/审计，不重建系统。Figma已实际读取29主页面、30手动模型、31连接结果、32默认模型选择、33安全Key弹窗；复用原组件、令牌与七模块导航，新增系统设置及原型SVG（设置20×20、关闭开关65×25）。

## 实现与数据

- `llm_models.py` 与迁移 `3fe4fc031b52`：`llm_service_config`单实例服务、加密凭据和修订；`llm_models`模型来源/发现时间/测试状态；`llm_selections`默认、分析与通知场景选择；`llm_call_logs`脱敏调用元数据。
- 迁移 `5e93d62bcf40` 将既有报告模型来源字段扩展至256字符，与模型配置一致；SQLite使用3.35+原生列操作，保留既有报告、审核外键及CHECK约束。回滚发现超长历史ID时拒绝截断；迁移回归测试包含已有报告和独立审核记录。
- `llm_secrets.py` 使用Fernet认证加密，主密钥只从部署环境或0600受控文件读取。使用成熟 [pyca/cryptography](https://github.com/pyca/cryptography)（Apache-2.0/BSD）和[Fernet官方文档](https://cryptography.io/en/stable/fernet/)，不自行设计密码算法。
- `llm_provider.py`集中处理候选OpenAI兼容GET /models及POST /chat/completions、Bearer、超时、1MB/2000条上限、字段校验和状态解释。HTTP/TLS由既有httpx承担，不引入新Agent框架。不预置平台模型名，不将列表成功视为推理成功。
- `llm_settings.py / llm_routes.py` 管理员配置、Key生命周期、模型刷新/手动管理/验证及选择、明确环境迁移、乐观锁和脱敏审计。更新服务地址会清Key、取消选择、隔离旧模型。引用中的模型受API及数据库组合外键保护，不能禁用/删除。
- `LLMService`统一读取生效配置和解密，按场景选用模型；`ai_service`继续负责事实引用约束。报告、工作安排和通知均经过同一调用服务，新请求即刻读取新配置，在途请求使用原配置快照。
- `LLMSettingsView.vue / llmTypes.ts` 真实表单和弹窗、Loading/Empty/Error/Success、默认下拉、场景选择、启停、日志查看。Key只保存在当前输入框内存，成功、失败提交及关闭后清空，不写Pinia/浏览器存储/URL。

配置优先级：已有数据库配置始终优先；无数据库配置时兼容旧AI环境。旧配置接管需要明确确认；迁移由服务端加密读取，导入模型为未测试，实际调用关闭。移除Web Key保留无凭据状态，不回退环境Key。数据库MaaS模式由管理员启用和业务本次外送同意共同控制；旧环境模式保留AI_EXTERNAL_ENABLED开关。无Key测试返回未配置，不联网。

安全的旧自定义地址按实际值展示；不在新白名单时明确提示运维授权，阻止凭据保存、迁移及网络调用，避免首次保存Key误投向预置地址。

## API清单

统一前缀 `/api/v1/settings/llm`；全部接口要求系统管理员，会话/CSRF沿用现有机制。配置/密钥/刷新/默认/场景操作要求配置If-Match；单模型操作使用模型If-Match。测试返回 `data.result.ok/code/message`和上游HTTP状态，平台401不当作本站登录过期。

| 方法 | 后缀 | 功能 |
|---|---|---|
| GET / PUT | 空 | 脱敏读取 / 保存服务地址、名称、模式、超时、启用状态 |
| PUT / DELETE | /credential | 添加、更换 / 移除Key；默认HTTPS，支持明确启用的本机开发HTTP例外 |
| POST | /import-environment | 显式迁移旧配置；相同传输限制，不覆盖已保存管理员配置 |
| POST | /test-connection | 实际尝试服务与列表接口认证检测，缺Key不联网 |
| GET | /models | 读取已保存的当前地址模型 |
| POST | /models/refresh | 请求平台/models并保存实际ID和来源、最近发现时间 |
| POST | /models | 手动录入准确ID和可选显示名 |
| PUT / DELETE | /models/{id} | 启用/禁用 / 删除未被引用的手动模型 |
| POST | /models/{id}/test | 最小调用测试，最多128输出token，不保存生成正文；截断单独提示，不自动重试 |
| PUT | /default-model | 设置/取消已验证默认模型 |
| PUT | /scenario-models | 分别配置分析和通知，null表示跟随默认 |
| GET | /audit-events | 最近100条脱敏配置审计 |
| GET | /call-logs | 最近100条脱敏调用元数据 |

原 `/api/v1/ai/config`向业务页面提供生效模式概况，不暴露服务凭据。管理员测试结果分别记录服务连接、认证、列表支持、实际调用、最近时间、配置修订与失败原因。404及非标准格式提示待适配，不能认定Key或模型本身一定不可用；模型基础调用通过也不保证严格JSON Schema已受平台支持。

## 安全边界

HTTPS协议、无URL凭据/查询参数/片段、精确域名和端口白名单、DNS地址检查、专网显式授权，回环/云元数据/保留地址禁止。重定向不跟随、TLS验证开启、环境代理关闭；网络错误和平台异常仅返回固定脱敏解释，不反射响应正文。业务仍仅外送符号事实描述，不提供写业务表的模型工具。

Key不进入GET、通用审计、异常或报表；配置审计使用显式安全快照，不把加密列交给通用record输出。调用日志没有Key、提示词、生成内容或平台原始异常。失败的业务事务回滚时，其数据库日志也回滚，但固定字段的服务日志仍记录失败代码；管理员测试失败结果可正常持久化。

主密钥与TLS私钥不提交Git、不进入Docker镜像，开发脚本写0600文件引用，不生成MaaS Key。正式环境需部署认可的TLS和Secret；本机证书只供开发。用户后续要求不用HTTPS，已增加显式本机例外：`scripts/dev.sh`启用 `LLM_ALLOW_LOCAL_HTTP_CREDENTIALS=true`，仅development/test、回环客户端和本机主机名允许HTTP管理Key；生产及非本机请求仍拒绝，伪造X-Forwarded-For不授予例外。前端根据后端开关及当前主机控制输入，后台仍加密保存。上游MaaS请求继续要求HTTPS及TLS验证。

## 验收项对应

| 附件编号 | 验证依据 |
|---|---|
| 1 保存Base URL | persisted_address测试；数据库读回、乐观锁冲突 |
| 2/3/4 添加、更换、移除Key | credential_lifecycle；实际请求Authorization切换；移除后无HTTP、无环境回退 |
| 5 无Key测试 | missing_credential；结果明确未配置，HTTP替身被禁止触发 |
| 6 正常模型列表 | discovery与partial字段解析；ID/名称来自响应，初始untested |
| 7 401/403/404/429/500 | provider_statuses参数化测试；脱敏、分别映射，404认证未知 |
| 8 超时/网络 | edge_cases参数化，单次请求、无静默成功/自动重试 |
| 9 空列表 | empty列表真实保存状态，不伪造模型 |
| 10 手动模型 | manual fallback；未验证不能选用 |
| 11 默认模型 | discovery/inference及scenario测试；必须保存、启用并验证 |
| 12 禁用/删除默认 | API409及直接SQL组合外键断言，需先取消引用 |
| 13 场景模型 | analysis模型A、notification模型B分别调用 |
| 14 Key不出GET和日志 | response/audit/log断言；公开字段、平台响应夹带Key拒绝 |
| 15 非管理员 | 所有主要管理操作403；浏览器隐藏设置菜单并拒绝API |
| 16 URL/重定向/SSRF | unsafe_urls、DNS私网需额外授权、元数据地址拒绝、302不跟随 |
| 17 新模型即时使用 | 新Session读取新默认/场景；Key更新使旧验证失效，重测后新Bearer |
| 18 Figma交互 | HTTPS Chrome完整配置流程、两类模型、场景、启停/移除、桌面与SVG几何、截图复核 |
| 额外：重启 | 新Python后端进程读取数据库并解密同一凭据，默认模型保持；HTTPS容器验证另记机器报告 |

当前已实际执行：SQLite和真实PostgreSQL均 **99 passed**（41项新增测试及原58项回归），无跳过；HTTPS模型配置浏览器 **2 passed**（上游HTTP替身）；原七模块浏览器 **8 passed**；Ruff/Prettier/vue-tsc/Vite/alembic check通过。最终Docker镜像已构建，隔离PostgreSQL/HTTPS前后端完成加密配置、数据库和API重启持久化、Key移除验证，见[机器记录](llm-https-verification.json)。保留既有Starlette测试客户端httpx弃用警告，不冒充错误已消除。浏览器配置测试在 `frontend/test-results-llm/`，业务回归在 `frontend/test-results/`，不互相删除证据。

后续本机HTTP变更：SQLite完整测试 **106 passed**，Ruff/Prettier/alembic check/vue-tsc/Vite通过；新增7项验证本机HTTP密钥生命周期、加密脱敏、管理员限制、关闭开关、生产/非本机/恶意Host及伪造转发头的拒绝。运行中HTTP页面已实际检查密码输入元素 `disabled=false/readOnly=false` 且保存按钮启用，未填入测试Key或改动用户凭据。本次追加未重复运行PostgreSQL、Docker或原浏览器自动化套件，上述99/2/8及容器结果属于追加前版本。

## 真实CMHK连接状态

**2026-10-20 15:09（Asia/Shanghai）已实际连接CMHK模型列表接口。** 本机代理将该域名解析为 `198.18.0.8`，此前被非公网策略拦截；确认准确域名和可信TLS连接后，在本机忽略Git的 `.env` 通过既有 `LLM_PRIVATE_ORIGINS=https://maas-api.cmhk.com` 单独授权并重启。使用用户已在网页保存的Key，请求真实 `/v1/models` 返回200，保存7个接口发现模型，认证状态为 `accepted_for_models_endpoint`。未改写或回显Key，未进行推理测试、设置默认模型或启用业务调用；列表成功不等于推理兼容性已验证。

自动化用例使用明确标记的MockTransport响应，测试模型ID只存在测试夹具，产品入口不加载测试适配器。HTTPS容器测试只验证随机测试Key加密和重启持久化，不以随机Key请求企业服务。上述真实平台列表验证与自动化替身结果分别记录。代理兼容补充测试实跑18项通过（其余30项在本次定向测试中被筛除，未声称重跑）；覆盖虚拟IP授权前拦截、授权后查询以及元数据地址继续拒绝，并通过Ruff和差异格式检查。未重复运行全套构建、PostgreSQL和Docker。真实模型推理及严格结构化输出仍待逐模型测试，当前不声称已验证完全兼容。

**15:16追加真实GLM基础调用验证：** 用户测试GLM时，原8-token预算耗尽，平台返回标准choices/message结构、`finish_reason=length`、空content及推理字段；先前统一提示格式不兼容不准确。测试预算调整为128，截断单独返回 `LLM_TEST_OUTPUT_TRUNCATED/incomplete`，保持未验证且不自动重试，推理或不完整正文不能冒充最终答案。修复后通过产品API对 `CM-Pub-GLM-5.1-PD` 实际测试返回200，状态available。只发送短测试提示，未发送业务事实、改选默认/场景模型或更改启用状态。SQLite完整 **110 passed**，Ruff/Prettier/alembic check/vue-tsc/Vite通过；本次未重跑PostgreSQL、Docker或浏览器自动化。基础调用通过仍不代表阶段报告的严格JSON Schema输出已验证。

**刷新后自动验证：** 网页刷新列表后复用已有模型测试API，串行测试已启用且尚未通过当前修订验证的模型；跳过已通过模型，显示进度、逐行失败原因及汇总。可停止后续测试，离开页面也不再发起新测试，当前调用可结束并保存结果。单模型拒绝不影响后续；认证、限流或网络/服务错误暂停，不自动重试。不自动选择默认模型或更改业务调用开关。已有接口与数据库结构不变。隔离HTTPS浏览器 **4 passed**，覆盖失败隔离、跳过已通过模型、手动停止、页面离开、凭据生命周期与权限；vue-tsc/Vite、Ruff及差异检查通过。本次未重跑全部后端、PostgreSQL或Docker；110项结果属于此前后端修复验证。

## 使用

按用户后续选择，运行 `./scripts/dev.sh`，访问 `http://127.0.0.1:5173/settings/llm`，使用本机系统管理员登录。本机HTTPS入口仍可选用 `./scripts/dev-https.sh` 和 `https://127.0.0.1:5175/settings/llm`。确认地址→保存Key→刷新列表并自动验证（不支持列表则手动准确ID并单测）→选择默认及场景→启用真实MaaS业务调用。Key请在本机配置页面输入，不发送到聊天中。

详细部署、环境兼容与验证命令见README“系统设置 · 大模型配置”。代码、迁移、测试和文档纳入版本管理；本机 `.env`、实际Key、加密主密钥、登录凭据及数据库均不提交。

# 第一期 · 第一阶段交付记录（V0.1.1）

> 本文件保留第一阶段历史记录；当前V0.2.0的第二阶段实现及实际验收见[第二阶段验收记录](PHASE2_ACCEPTANCE.md)。

日期：2026-10-20。本记录取代2026-10-19的本地演示交付说明；旧版所列 PostgreSQL 未实测、固定演示身份、独立审批未接入等技术缺口已在本轮补齐。范围仅第一阶段，不包括第二阶段标准动作/提醒/任务及第三阶段评价/AI。

## 验收依据

- 原始用户请求中的第一阶段功能和本轮“继续完成第一阶段”要求。
- [用户于2026-10-20明确确认的验收基线](PHASE1_BASELINE.md)：编号唯一性、整批原子导入、项目角色、计划编制/批准分离、实际提交/核实分离。
- 已实际读取仓库中的技术设计草案 V0.1、数据库与 API 设计 V0.2、技术评审拆解 V0.3、API 清单、模拟 Excel 的项目和节点事实，以及 Figma 中的项目、节点、表单、导入和详情画面。
- 项目计划书及系统需求说明书原件未提供，未声称读取；当前验收使用上述可访问资料和用户已确认基线。真实企业SSO、组织同步、合同/证据附件及部署域名不以模拟样本冒充。

## 已补齐事项

1. **认证**：本地配置真实账号，pwdlib/Argon2 哈希，数据库登录会话与过期、退出撤销、账号禁用、CSRF、HttpOnly/SameSite Cookie、登录错误次数限制。不存在固定 local-demo 身份或免登录业务接口。
2. **项目授权**：admin/editor/reviewer/viewer 按项目分配；列表与统计只返回授权项目；项目、节点、计划、实际、批次及错误下载均在后端校验访问权限。角色撤销即时生效。账号创建由运维CLI操作，无开放注册和默认密码。
3. **独立审核**：所有版本编制人员不可批准自己的版本；实际提交人不可核实自己的记录；伪造提交人、审核人或actor请求头不能改变服务器记录的操作人。原始计划来源与批准依据分字段保存。
4. **PostgreSQL**：官方16镜像实际迁移往返、alembic check、样本初始化和全部业务测试。并发确认导入使用行锁并刷新已加载对象，重复确认不产生重复数据。
5. **容器全栈**：前后端镜像实际构建，三容器栈启动，使用真实浏览器完成项目、节点、审批、核实及导入。数据库容器重启后数据保持一致。
6. **业务确认和逐项验收**：已把用户确认记录写入基线，导入部分成功模式禁用，并建立[第一阶段逐项验收表](PHASE1_ACCEPTANCE.md)。

## 实际验证

| 验证项 | 结果 |
| --- | --- |
| SQLite pytest | 23 passed，无跳过；包含权限、自审、分页、并发导入及67节点源事实核对 |
| PostgreSQL pytest | 23 passed，无跳过；并发导入两次确认均返回200且只写一条数据 |
| 迁移 | SQLite与真实PostgreSQL迁移往返、alembic check通过；UUID、外键、CHECK和唯一索引实际生效 |
| 本地Chrome端到端 | 4组通过：持久化与历史版本、独立审核、项目/节点导入及防重、导航/故障/桌面布局、归档/筛选/只读权限 |
| Docker三容器端到端 | 同4组通过；使用隔离端口和随机密码，不复用开发数据 |
| PostgreSQL容器重启 | 6个验收项目保留，数量一致；测试数据卷随后仅由本次脚本清理 |
| 前端与规范 | vue-tsc、Vite构建、Ruff和Prettier通过 |
| 本机交付账号 | 随机密码账号的登录、项目读取、退出实际通过；账号文件0600并忽略Git及Docker上下文 |

测试保留一条依赖弃用警告：Starlette TestClient 提示未来迁移其 httpx 接口。未屏蔽此警告，未将警告或跳过项冒充通过。企业真实业务验收、生产基础设施安全评审及后续阶段测试不在本次技术验收中虚构为已执行。

## 关键交付文件

- `backend/app/auth.py`、`auth_routes.py`、`admin.py`：会话、权限与账号配置；`services.py`、`imports.py`：项目、版本、事实与导入事务。
- `backend/alembic/versions/`：四版固定迁移，保留既有数据，未用重建工程替代升级。
- `frontend/src/views/`、`components/`、`store.ts`：登录、项目/节点页面、成员授权、表单/抽屉和会话状态。
- `scripts/check.sh`、`verify_postgres.py`、`verify_compose.py`：可重复的本地、目标数据库与全栈验收；`create_local_accounts.py`：显式本机账号初始化。
- `README.md`、`PHASE1_BASELINE.md`、`PHASE1_ACCEPTANCE.md`：启动、已确认规则与逐项验收依据。

## 开源复用与边界

检查了 FastAPI 官方 full-stack 模板、FastAPI Users 与 pwdlib。FastAPI Users 当前为维护模式；本项目采用 FastAPI 的依赖鉴权模式和 pwdlib 的 Argon2 能力，不自行实现密码算法，不引入与现有 Vue/SQLAlchemy 不一致的整套框架。参考链接：[FastAPI安全文档](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)、[FastAPI Users](https://github.com/fastapi-users/fastapi-users)、[pwdlib](https://github.com/frankie567/pwdlib)。

第一阶段样本仍是3个虚构项目、67个节点。P-H028仅有来源V2，不虚构V1；“需关注”保留来源说明；样本核实记录不充当真实业务证据。工作日历、提醒发送、任务闭环、财务、绩效指标和AI未提前实现，也不作为第一阶段未完成项继续混入。

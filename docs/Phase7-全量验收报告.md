# Phase 7 全量验收报告

> 验收日期：2026-08-25  
> 验收环境：Windows / Python 3.13 / Docker Desktop / Docker Compose v2  
> 当前结论：有条件通过；标准产品栈已通过，Fault Lab E2E 需由网络正常的 CI 完成最后确认

## 1. 验收范围

本轮覆盖 Backend、Runner、Fault Lab、Frontend、数据库迁移、OpenAPI 契约、Compose、
容器镜像和根目录跨平台启动器。验收不创建或修改用户的正式业务数据；Fault Lab 采用独立
`opspilot-acceptance` Compose 项目，失败路径也会删除其容器和数据卷。

## 2. 已通过结果

| 门禁 | 结果 |
|---|---:|
| Backend pytest | 197 passed |
| Runner pytest | 79 passed |
| Fault Lab pytest | 18 passed |
| Frontend Vitest | 51 files / 227 passed |
| Agent Offline Eval | 13/13，release gate passed |
| Backend / Runner / Lab Ruff | passed |
| Backend / Runner / Lab strict MyPy | passed |
| `main.py` Ruff / strict MyPy / launcher regression | passed，3 tests |
| Frontend TypeScript | passed |
| OpenAPI drift check | passed |
| Frontend production build | passed |
| Alembic graph | 单一 Head：`20260821_0037` |
| Standard Compose config | passed |
| Fault Lab Compose overlay config | passed |
| Backend / Frontend / Migration image build | passed |
| Fault Lab image build | passed |
| `python main.py start --no-open` | passed |
| Runtime readiness | PostgreSQL、Backend、Frontend 均 healthy |

自动化测试共执行 521 项业务/组件断言，另执行 13 项离线 Agent Eval。

## 3. 验收中发现并修复

1. 根目录原 `main.py` 只是 IDE 示例，已替换为跨平台 OpsPilot 启动器。
2. Frontend `/healthz` 返回非 JSON；启动器健康检查已按 HTTP 2xx 判断，避免错误超时。
3. OpenAPI 校验在 Windows 原地覆盖受检文件会触发 `EPERM`；已改为临时生成后只读比对。
4. Fault Lab 使用的 `docker.io/shopify/toxiproxy:2.12.0` 不存在；已切换为 Shopify 官方
   `ghcr.io/shopify/toxiproxy:2.12.0`。
5. `main.py` 已加入 Backend CI 的路径触发、Ruff、严格 MyPy 和帮助命令校验。

## 4. 尚待最后确认

Fault Lab 隔离 E2E 未进入场景断言阶段。本机从 Docker Hub 拉取
`qdrant/qdrant:v1.15.4` 时先发生 `unexpected EOF`，续传随后长时间无字节进展。该问题发生在
容器创建之前，属于外部镜像传输阻断，不是测试断言失败。

合并前必须以 `.github/workflows/lab.yml` 的 `e2e` Job 成功作为最终验收条件；该 Job 会在
Ubuntu 上以 25 分钟总超时和 12 分钟场景超时运行，并在失败时收集日志、最终删除隔离卷。
GitHub Branch Protection 中还需将 Backend、Runner、Fault Lab 的必要 Job 设置为 Required
Checks，此仓库外配置无法通过本地文件验收。

## 5. 启动与数据状态

标准栈已在验收通过后主动停止，未删除数据卷、镜像和本地 Secret。停止前最后一次检查结果为：

- Console：`http://127.0.0.1:8080`
- Backend：`http://127.0.0.1:8000`
- PostgreSQL、Backend、Frontend 均为 healthy

再次体验可运行 `python main.py start --no-open`。停止但保留数据使用 `python main.py stop`；只有明确清空本地卷时才使用
`python main.py stop --lab --remove-volumes`。

## 6. Linux 结论

`main.py` 只依赖 Python 标准库和 Docker Compose v2，不调用 PowerShell、批处理文件或
Windows 专用 API，同一入口可在 Linux 使用：`python3 main.py`。Linux 仍需满足 Docker Socket
权限，并在启用 Runner 时配置宿主机 Docker GID。实际 Linux 容器验收由 GitHub Actions 的
Ubuntu Runner 完成，不能用本次 Windows 本机结果替代。

## 7. 工作区清理

已删除 70 个散落的 `.pytest*` 临时目录，以及本轮和历史的 MyPy、Ruff、UV、Compose、构建、
验收缓存；虚拟环境外的 `__pycache__` 也已删除。`.gitignore` 已补充对应规则，避免再次进入版本
状态。`.venv`、`frontend/node_modules` 和 `.secrets` 被有意保留，分别用于本地依赖和当前运行栈。

曾受历史 Windows ACL 保护的 `.review-stage2` 与 `.review-tmp` 已由管理员完成删除。当前工作区
不再保留散落的 pytest 临时目录或旧审查副本。

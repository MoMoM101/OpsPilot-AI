# 后端、Runner 与 Fault Lab CI

> 更新时间：2026-08-25

项目包含三个独立 GitHub Actions Workflow：

- `.github/workflows/backend.yml`：Backend Pytest、认证/RBAC、Runner Lease、Outbox 回归门禁、
  Ruff、严格 MyPy、Alembic 单 Head、PostgreSQL 空库升级、`alembic check`、Compose 配置以及
  Backend/Frontend 镜像构建；
- `.github/workflows/runner.yml`：Runner Pytest、Ruff、严格 MyPy 和 Runner 镜像构建；
- `.github/workflows/lab.yml`：Fault Lab Pytest、Ruff、严格 MyPy、Compose 叠加配置校验、Lab
  镜像构建，以及有 25 分钟 Job 上限和 12 分钟命令上限的真实 Compose E2E。E2E 使用本地确定性
  Agent Provider，动态创建一次性 CI Admin，不依赖外部模型或仓库 Secret。

Backend Workflow 使用临时 PostgreSQL 17 Service，不依赖开发者本地数据库。任何 Migration
分叉、多 Head、空库迁移失败、模型与迁移不一致或安全回归测试失败都会阻止合并。

Fault Lab Workflow 监听 `lab/**`、`docker-compose.lab.yml`、基础 `docker-compose.yml` 和工作流自身。
E2E 失败时先采集 Backend、Runner 和 Lab 容器日志，随后无条件删除 CI 的 Compose 容器和临时卷。

默认分支保护必须把以下 Check 设为 Required status checks；该仓库设置需要在 GitHub Repository
Settings 中由维护者启用，Workflow 文件本身不能修改分支保护：

```text
Fault Lab / quality
Fault Lab / compose
Fault Lab / e2e
```

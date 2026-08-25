# Agent Prompt Injection 防护

> 状态：后端基础防线已实现  
> 更新时间：2026-08-20

## 防护边界

Evidence、Incident 标题以及 Runner 返回的摘要都属于外部输入，不能被当作系统指令。后端在
调用模型前构造独立的 `securityPolicy`，并把所有外部文本放入 `untrustedData`，模型指令明确
禁止执行其中出现的角色切换、策略覆盖、工具调用或权限扩大要求。

当前发送给模型的 Evidence 还有以下限制：

- 只接受 `runner_observation`；
- 只接受来源前缀为 `runner:` 且采集状态为 `succeeded` 或 `failed` 的记录；
- 每次最多发送 25 条；
- 标题和每条摘要最多发送 1000 字符，先做 NFKC 规范化，再移除不可见、双向文本和其他 Unicode 控制字符；
- 不发送 Evidence 原始 `data.content`、凭据或完整日志。

## 确定性服务端校验

模型结构化输出不能直接扩大执行权限：

- 所有模型输出 DTO 使用 `extra=forbid`，未知 Tool、命令和角色字段直接失败，不做静默忽略；
- capability 必须属于后端 `RunnerReadOperation` 枚举，`shell.execute` 等任意能力无法通过
  Pydantic 校验；
- Planner 生成的每个 `resourceScope` 必须等于当前 Incident 的资源；
- Investigator 输出及 Hypothesis 中的 Evidence ID 必须来自本次实际发送给模型的 Evidence；
- Hypothesis、Checkpoint 和 PlanStep 写入时仍会再次校验 Evidence 是否属于当前 Incident；
- RunnerTask 创建时再次校验 Incident 资源范围、PlanStep capability 和 Runner 实际能力。

这些检查均由后端代码执行，不依赖模型是否遵守 Prompt。

## 回归测试

`tests/test_agent_prompt_security.py` 覆盖：

- Evidence 中伪造 SYSTEM 指令、Shell 指令和超长内容；
- 非白名单 Evidence 类型与来源；
- 超出本次上下文的 Evidence ID；
- 非白名单 capability。
- 未声明的 `tool_call`、`shell_command` 和 Action `command` 字段；
- Unicode 双向文本、零宽字符和 NUL 控制字符。

以后新增 Evidence 来源、模型 Tool 或 capability 时，必须先更新来源白名单、确定性校验和该
回归集，不能只修改模型 Prompt。

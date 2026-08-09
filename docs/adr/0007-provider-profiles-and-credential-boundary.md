# ADR 0007：模型 Profile、能力降级与凭据边界

> 状态：已接受
> 日期：2026-08-10

## 背景

现有 `AiGatewayManager` 只保留一个内存 OpenAI 配置，不能自定义 base URL、管理多个模型端点，也没有能力、用量与费用记录。将 API Key 保存到 SQLite、作品归档或浏览器存储都会扩大泄漏面；让 Web 读回系统已保存密钥也会破坏本地信任边界。

## 决定

### Provider 与 Model Profile

1. 上层 Job 只依赖 `ProviderAdapter` 契约，不直接依赖 OpenAI SDK。MVP 实现 OpenAI Responses 和通用 OpenAI-compatible 两个适配器；Ollama 原生协议保留到 P1。
2. `ModelProfile` 是本机全局配置，保存 profile ID、显示名、provider 类型、HTTPS/loopback base URL、模型名、能力快照和每百万 token 估价。它不属于任何作品，不进入作品归档。
3. 只允许 `https` 远程地址和 `http` loopback 地址；禁止 URL 凭据、query/fragment 和任意内网 HTTP，防止无意外发与凭据泄漏。
4. 每个 Job 在提交时绑定 profile ID、provider、model 和能力/配置指纹。恢复时指纹不一致就停止并要求作者确认，不静默换模型续写。

### 能力与错误

1. 能力使用显式布尔快照：结构化输出、流式增量、服务端取消、用量回传。能力探测失败时使用保守默认，不宣称未验证的能力。
2. 缺少结构化输出时使用文本 JSON 加本地校验；缺少流式时回退到完整响应；无服务端取消时不再开始下一次调用，并明确提示当前请求可能仍在 provider 端运行。
3. provider 异常归一为 `authentication`、`permission`、`rate_limit`、`timeout`、`unavailable`、`invalid_response`、`unsupported_capability` 和 `cancelled`。用户只看到可行动文案；原始响应、请求头和密钥不进入日志、Event 或 Artifact。

### 密钥与运行时

1. macOS 使用 Keychain Services，Windows 使用 Credential Manager。凭据以稳定服务名和 profile ID 定位，设置页只能读取“已保存/未保存”状态。
2. Web 可把作者当下输入的密钥交给 Tauri 命令，但 Tauri 不把已保存密钥返回 Web。Tauri 在内部读取凭据并通过带随机会话令牌的 loopback 请求激活 sidecar profile。
3. sidecar 只在进程内存中保留执行密钥。数据库、作品归档、任务输入、录制回放和日志均不保存明文密钥。
4. 系统凭据库不可用时，允许作者选择仅当前 sidecar 进程有效的内存密钥；禁止退回到明文文件、SQLite 或 localStorage。

### 用量与外发预览

1. Attempt 记录输入/输出 token、耗时、重试序号和估算成本；价格是 profile 元数据快照，只称“估算”。未返回 usage 的端点明确标记未知，不伪造精确数字。
2. 每次创建 AI Job 前生成外发预览，包含数据类型、字符范围、预估 token、provider/profile 和估算成本。预览不含 API Key，也不把参考作品原文混入正文写作上下文。

## 结果

- 切换兼容端点不需要改写 Job、Artifact 和作者确认契约。
- 多 profile 可管理、可审计，但密钥不随数据库或作品流转。
- 兼容端点的能力差异会显式降级，不在长任务中途以猜测代替契约。
- 费用是可预见和可追溯的，但不被表述为 provider 账单。

## 回滚边界

可关闭多 profile UI，并把现有 OpenAI 适配器当作唯一会话 profile。回滚不得把系统凭据迁入明文存储，不得从 Web 读回已保存密钥，也不得删除已有用量和任务溯源记录。

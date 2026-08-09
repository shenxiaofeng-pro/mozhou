# ADR 0006：任务状态机、幂等键与租约恢复

> 状态：已接受
> 日期：2026-08-09

## 背景

ADR 0002 已确定长 AI 工作使用持久化 Job、Attempt、Chunk、Artifact 和 Event，但尚未冻结状态转换、重复提交语义和 sidecar 崩溃后的接管规则。拆书会产生数十次付费调用，写章又必须确保同一候选不会重复写入正文，因此这些规则必须先于任务表和 worker 实现。

## 决定

### 状态机

Job 使用以下状态：

- `queued`：已持久化，等待 worker 领取。
- `running`：worker 已持有有效租约并正在执行。
- `pause_requested`：作者请求停止，worker 在下一安全检查点结束当前本地步骤，不再开始新的外部调用。
- `cancelled`：任务已停止；已成功 Artifact 保留且可查看。
- `succeeded`：所有必要 Artifact 已持久化。
- `failed`：任务因可见错误结束，可由作者重试。
- `interrupted`：worker 租约过期或进程异常退出，尚未判断能否继续。

合法转换固定为：

- `queued → running | cancelled`
- `running → pause_requested | succeeded | failed | interrupted`
- `pause_requested → cancelled | running | interrupted`
- `failed → queued | cancelled`
- `interrupted → queued | cancelled`
- `cancelled → queued`
- `succeeded` 不允许再转换

重试和重启恢复通过转换回 `queued` 实现，不新建逻辑任务。状态变化必须追加 Event，并与状态更新处于同一短事务。

### 幂等键

1. 顶层 Job 以 `(project_id, kind, idempotency_key)` 唯一；重复提交返回已有 Job。
2. Chunk 以 `(job_id, idempotency_key)` 唯一；参考 Map 键由来源区段、字符范围、模型和提示版本共同决定。
3. Artifact 以 `(job_id, artifact_key)` 唯一且只插入、不更新。相同键与相同哈希重复写入返回已有 Artifact；相同键但内容不同视为冲突并停止任务。
4. 章节候选的 Job 幂等键包含章节 ID、期望 revision、作者意图哈希、provider、model 和提示版本；采用候选仍使用章节 revision 乐观锁，因此重放不能覆盖作者新稿。

### Attempt、租约与恢复

1. 每次真实外部调用创建一个 Attempt；本地准备步骤不伪装成模型调用。
2. 单机 worker 以 `BEGIN IMMEDIATE` 原子领取一个 `queued` Job，写入随机 owner、租约截止时间与心跳。
3. worker 不在数据库事务内等待模型；调用前后和每个 Chunk 检查取消状态，同时由独立心跳在线程阻塞等待模型期间续租。默认租约 15 秒，心跳与回收扫描间隔不超过 5 秒。
4. 启动时立即扫描一次，运行期间继续周期扫描；租约在新 sidecar 启动后才过期的 `running` / `pause_requested` Job 也会被标为 `interrupted`，再只把可安全重放的任务放回 `queued`。
5. 已成功 Chunk 和 Artifact 永不因任务重试而删除；恢复时跳过它们。无法确认结果是否到达的 Attempt 标为 `interrupted`，可产生新 Attempt，但 Artifact 唯一键阻止重复副作用。

### 并发边界

MVP 只运行一个进程内 worker 和一个短事务写者。SQLite 使用 WAL、5 秒 busy timeout 和有界退避；不引入 Redis、云队列或多进程调度。

## 结果

- 用户可看到任务为何停止、从哪里继续以及哪些调用已经完成。
- 第 39 个 Map 块失败时，前 38 个成功 Artifact 仍可复用。
- 重复点击、前端重试、sidecar 重启和 API 超时不会创建第二个逻辑任务或重复采用正文。
- 后续审校与沙盘可以复用同一状态机，但 M2 只接入拆书和写章两条垂直链路。

## 回滚边界

可停止 worker 并让新任务停留在 `queued`，旧同步接口保留一版开发兼容。回滚不得删除 Job、Attempt、Chunk、Artifact 或 Event；不得把未知的 `running` 直接标成 `succeeded`，也不得绕过正文 revision 门禁。

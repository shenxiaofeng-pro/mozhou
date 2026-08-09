# 墨舟完整实施进度

> 执行依据：PLAN.md  
> 计划状态：已批准，范围冻结  
> 开始日期：2026-08-09  
> 当前阶段：M4 长篇上下文编译器
> 总体状态：M0、M1、M2、M3 已完成并验收；尚未达到总体 Definition of Done

## 已确认产品决策

| 决策 | 结论 |
|---|---|
| D1 分发与许可 | MVP 先按闭源私有测试推进；保持清洁实现，不复制 MiroFish 源码 |
| D2 AI 自动化 | 默认一键串联到单章候选稿；写入正文仍需作者确认 |
| D3 模型范围 | 首轮支持 OpenAI-compatible 与自定义 base URL；Ollama 原生体验放入 P1 |
| D4 平台顺序 | macOS 先行内测；Windows 在公开 MVP 前完成发布门 |
| D5 仓库治理 | 不升级 GitHub Pro；保持私有，采用版本化本地 pre-push 门和强制执行的 PR/CI 工作纪律，外部协作前重新评估 |

## Definition of Done

以下条件全部满足前不得宣称完成：

1. PLAN.md 的 M0 至 M12 全部完成并逐项验收。
2. 全部构建、测试、lint、类型检查通过。
3. 里程碑验收场景得到实际验证。
4. 本文件记录最终结果、验证证据和遗留风险。
5. PLAN.md 第 11、12 节的测试策略与 MVP 发布门全部满足。

说明：项目目录及其父级不存在适用的 AGENTS.md 或 CLAUDE.md。增量实施技能引用的 references/definition-of-done.md 在已安装技能包中缺失，因此采用以上项目专属 Definition of Done，不降低验收标准。

## 里程碑状态

| 里程碑 | 状态 | 验证摘要 |
|---|---|---|
| M0 工程治理与计划对齐 | 已完成 | 数据、基线、双平台 CI、恢复演练和免费私有仓库替代控制已通过 |
| M1 创作可信度与核心可达性热修 | 已完成 | 事实选择、全宽度 AI 入口、按需正文、迁移链、动态端口与会话令牌均已通过 |
| M2 可恢复 AI 任务运行时 | 已完成 | 任务核心、长篇拆书、章纲/写章、任务中心、心跳续租和真实 DMG 强杀恢复均已验收 |
| M3 模型网关、密钥与用量治理 | 已完成 | 多线路、系统密钥、任务分流、用量治理、外发确认及 macOS/Windows/security 远端门均已通过 |
| M4 长篇上下文编译器 | 进行中 | 正在定义版本化 ContextPacket、预算与来源选择契约 |
| M5 全局拆书库与现实资料导入 | 未开始 | — |
| M6 原创性门禁与蓝图工作流 | 未开始 | — |
| M7 整书总导演与 AI 优先创作 | 未开始 | — |
| M8 多 Agent 审校、版本与变更集 | 未开始 | — |
| M9 稿件导入、导出与连载工作台 | 未开始 | — |
| M10 规模、安全与双平台发布硬化 | 未开始 | — |
| M11 封闭测试与 MVP 发布 | 未开始 | — |
| M12 P1 剧情沙盘 | 未开始 | — |

## M0：工程治理与计划对齐

### 已完成

- 重新读取 PLAN.md、README.md、docs/product 和 tasks 下的现有文档。
- 确认项目没有适用的 AGENTS.md 或 CLAUDE.md。
- 确认产品负责人已批准四项产品决策。
- 对真实用户数据库执行只读完整性检查：quick_check 为 ok。
- 在 ~/Library/Application Support/com.lingjing.mozhou/backups/ 创建实施前 SQLite 一致性备份。
- 独立打开备份并验证 quick_check 为 ok，项目/章节/参考作品数量为 8/17/2，与源库一致。
- 初始化本地 main 分支并建立实施前源码基线提交 86cd5bc。
- 扩充 .gitignore，排除数据库、密钥、本地数据、构建产物、缓存、Tauri 生成 schema 和 TypeScript 增量缓存。
- 暂存内容扫描未发现真实密钥；唯一 Key 模式命中是自动化测试夹具。
- 创建 GitHub 私有仓库 https://github.com/shenxiaofeng-pro/mozhou，并推送实施前基线。
- 用 Node 原生进程编排替换 shell 后台符号；macOS/Windows 命令选择测试 2/2 通过。
- 建立仓库守卫，阻止数据库、构建产物、环境密钥、大文件和生成目录进入版本控制；工程脚本测试 5/5 通过。
- pnpm 高危依赖审计通过：未发现已知漏洞。
- 本地创建 macOS/Windows 完整 verify 和独立 security CI，以及 npm、uv、Cargo、GitHub Actions 的 Dependabot 配置。
- GitHub CLI 已获得 workflow scope，CI 和仓库守卫提交已推送到私有远端。
- 记录本地优先运行时、持久任务与上下文、作者批准门、全局拆书库与清洁实现四项 ADR。
- 建立真实能力状态矩阵，并将 PRD、早期开发计划和历史任务清单指向冻结的 PLAN.md。
- 修复 Windows 测试夹具中的 POSIX/macOS 路径假设；本地 API 全量测试 68/68 通过。
- GitHub Actions 运行 31310974313 全绿：macOS、Windows 原生 sidecar/桌面检查和 security 均通过。
- JavaScript、Python 与 Rust 依赖审计未发现已知漏洞；Rust 保留 17 条第三方传递依赖维护/不安全告警。
- 在全新目录按 pnpm/uv 锁文件安装并执行完整 verify，全部通过。
- 创建并推送 v0.1.0-baseline 标签；从标签创建独立临时分支后再次完成锁文件安装和完整 verify。
- 冻结 0.1.0 数据、API、归档与测试契约，并建立提交与 Pull Request 约定。
- M0 收尾 PR #4 的 macOS、Windows 和 security 三项门全部通过，并以 rebase 方式合入 main；Actions v7 更新已获得远端证据。
- 产品负责人接受免费私有仓库阶段性方案；新增本地 pre-push 门，功能分支/标签允许、main 更新和删除拒绝的策略测试 3/3 通过。
- `pnpm install` 自动配置版本化 hooks，当前仓库已验证 `core.hooksPath=.githooks` 且 pre-push 文件可执行。

### 当前基线

| 检查 | 结果 |
|---|---|
| Web Vitest | 26/26 通过 |
| FastAPI pytest | 68/68 通过 |
| Tauri Rust | 2/2 通过 |
| 用户数据库 quick_check | ok |
| 用户数据数量 | 8 个项目、17 个章节、2 本参考作品 |
| Git 基线 | 86cd5bc |

### 当前状态

- GitHub workflow scope 权限已经解除，远端自动发布门可正常运行。
- GitHub 对私有仓库的经典分支保护和 Repository Ruleset 均返回 HTTP 403：当前账户必须升级 GitHub Pro 或把仓库设为公开。
- 公开仓库违反已确认的闭源私测决策；产品负责人决定不升级，接受版本化本地 hook 加 PR/CI 工作纪律作为单人 MVP 阶段控制。
- Dependabot 已创建 npm、Python 和 GitHub Actions 更新 PR；CI Actions 的 Node 24 运行时更新已由 PR #4 验证并合入，其余升级保持独立验证。

### 验收结论

- M0 交付、测试与恢复标准已验证；服务端分支保护由已确认的 D5 阶段性例外替代。
- M1 可以开始；增加外部协作者前必须重新打开仓库治理决策。

## M1：创作可信度与核心可达性热修

### 已完成

- 加入 60 条正式事实的第 100 章上下文回归，先复现旧实现只取最早 50 条的问题。
- 新选择器排除来源在当前章之后的事实，优先保留当前角色相关事实，再按来源章节、创建时间和标识选择最近事实。
- 每条入选事实附带来源章号和 `entity_relevance` 或 `source_chapter_recency` 入选原因。
- AI 专项测试 4/4、API 全量测试 69/69、ruff 与 mypy 全部通过。
- 以单一 `DirectorPanel` 实例实现窄窗 AI 导演抽屉，宽屏保持三栏，避免两套状态或请求分叉。
- 1040 像素及更窄窗口提供固定“AI 导演”书签入口；支持关闭按钮、背景关闭和 Escape，并在关闭后把焦点还给入口。
- 抽屉和移动端拆书入口具有明确可访问名称，动画遵循 `prefers-reduced-motion`。
- React 新增窄窗交互回归；Web 27/27、lint、类型检查和生产构建通过。
- 真实浏览器在 1040、900、760 三档完成入口、展开、关闭、焦点、正文可见性和控制台验证；控制台无 warning/error。
- 重新构建 ad-hoc 签名 macOS 发行包；在隔离数据目录的发行版 Tauri 窗口精确缩至 1040 像素，实际打开和关闭 AI 导演成功，可访问树包含完整 AI 工作台。
- 本切片完整 `pnpm run verify` 通过：仓库守卫、lint、类型检查、工程脚本 8/8、Web 27/27、API 69/69、Web 构建、sidecar 构建和 Rust 桌面检查全部成功。
- 新增不携带章节正文的 `WorkspaceSummary` / `ChapterSummary` 契约，以及项目摘要和单章正文读取 API；旧版完整 Workspace API 保留一版，便于渐进迁移和回滚。
- 工作台首次打开只取项目摘要与复更章正文；创建、保存和各面板的旧完整响应在入口统一归一化，常驻 React 状态不再保存整本章节正文。
- 切章现在先保存当前稿件，再按章节 ID 读取目标正文；读取失败会保留当前章节并显示错误，避免空稿覆盖或界面误切换。
- API 回归验证摘要响应不含正文标记、单章接口返回正文、旧接口仍兼容，且两条新路由的 404 行为明确。
- 本切片完整 `pnpm run verify` 通过：仓库守卫、lint、类型检查、工程脚本 8/8、Web 28/28、API 71/71、Web 构建、sidecar 构建和 Rust 桌面检查全部成功。
- 新增 `services/api/app/migrations/` 显式注册表，v1 初始结构、v2 章纲/AI 来源字段、v3 迁移履历按连续版本顺序执行；当前 schema version 提升为 3。
- 旧库升级先创建一致性备份，再在同目录暂存副本执行迁移和完整性检查；全部成功才替换原库，中途失败清理暂存副本，不修改原库。
- 数据库回归覆盖 v1→v2→v3、v2→v3、重复启动、未来版本拒绝、损坏拒绝和中途故障注入；故障用例验证原库 SHA-256、版本、原稿内容不变且备份可读。
- 使用真实用户库的一致性副本完成 v2→v3 演练：`quick_check=ok`，项目/章节/参考作品保持 8/17/2，迁移履历 3 条、升级前备份 1 份；真实原库未执行迁移。
- 迁移切片验证：API 74/74、ruff 和 mypy 全部通过。
- 迁移切片完整 `pnpm run verify` 通过：仓库守卫、lint、类型检查、工程脚本 8/8、Web 28/28、API 74/74、Web 构建、sidecar 构建和 Rust 桌面检查全部成功。
- Tauri 每次启动使用系统随机源生成 256-bit 会话令牌，经子进程环境传给 sidecar；WebView 通过单一 `api_connection` IPC 在内存中获取动态地址和令牌，所有业务请求统一附带请求头。
- FastAPI 对所有非预检 `/api/*` 请求使用常量时间比较校验令牌；缺失和错误令牌返回同一 401，`/health` 只暴露就绪状态，令牌不写入数据库、文件、URL、日志或 localStorage。
- 运行入口必须具备桌面令牌或显式 `MOZHOU_ALLOW_INSECURE_DEV_API=1`；仅版本化浏览器开发脚本设置兼容开关并输出安全警告，桌面发行缺令牌会拒绝启动。
- 移除桌面构建中遗留的固定 8765 配置，并强制 Tauri 环境优先使用 IPC 连接，避免绕过动态 sidecar 和会话认证。
- 会话令牌自动化验证：API 缺失/错误/正确三类请求、CORS 预检、运行入口安全开关、Web 统一请求头和 Tauri 随机源均通过；API 81/81、Web 28/28、Rust 3/3。
- 仓库守卫新增“索引内文件正在删除”回归并将 `.env.tauri` 改为禁止跟踪，工程脚本 9/9 通过，防止固定桌面 API 配置再次进入仓库。
- macOS 发行版冷启动验收发现健康响应可能分成多个 TCP 片段；旧探针只读一次时会误判 sidecar 超时。探针现读取最多 4 KiB 的完整关闭响应，并以“响应头先到、正文延迟到达”回归覆盖该故障；Rust 4/4 通过。
- 重新生成 ad-hoc 签名 DMG，并在端口 8765 被诱饵服务占用时从只读 DMG 启动。发行版成功创建隔离测试作品并进入创作工作台，实际 sidecar 使用动态端口 57281；无令牌访问业务 API 返回 401，诱饵 8765 未承载桌面业务请求。
- M1 收尾完整 `pnpm run verify` 通过：仓库守卫、lint、类型检查、工程脚本 9/9、Web 28/28、API 81/81、Web 构建、sidecar 构建和 Rust 桌面检查全部成功；Rust 单元测试另行 4/4 通过。

### 下一切片

- 进入 M2：先建立持久任务、任务分块与事件模型，再把真实写章和长篇拆书迁移到可恢复运行时。

## M2：可恢复 AI 任务运行时

### 已完成

- 新增 ADR 0006，冻结 `queued`、`running`、`pause_requested`、`cancelled`、`succeeded`、`failed`、`interrupted` 状态及合法转换，明确 Job/Chunk/Artifact 幂等键、不可变产物和租约恢复语义。
- 新增 schema v4，持久化 Job、Attempt、Chunk、Artifact、Event；顶层任务、任务块和产物分别具备数据库唯一约束，避免重复提交、重复块和重复副作用。
- 实现单机短事务租约、心跳、取消检查点、失败重试和过期租约恢复；恢复会把开放 Attempt 标为 interrupted、保留成功 Artifact，并仅重排未完成块。
- worker 边界只持久化错误类型与安全文案，不写入 provider 原始异常，回归验证模拟密钥片段不会进入任务详情。
- 提供项目任务列表、任务详情、产物内容、取消和重试 API；项目归档已覆盖全部任务表，恢复副本会重映射任务引用并验证 Artifact SHA-256。
- M2 核心切片专项验证：状态机全组合、双 worker 互斥租约、幂等提交、不可变 Artifact 冲突、取消检查点、过期恢复、运行成功/失败、API 和归档往返均通过；后端当前 91 项测试。
- M2 核心切片首次完整 `pnpm run verify` 通过：仓库守卫、lint、类型检查、工程脚本 9/9、Web 28/28、API 91/91、Web 构建、sidecar 构建和 Rust 桌面检查全部成功。
- PR #12 的远端 security 门发现新测试中的模拟敏感串；本地守卫此前只扫描已跟踪文件，尚未提交的新文件不会被检查。守卫现同时扫描已跟踪和未忽略的未跟踪文件，并新增回归；模拟异常改用不具凭据形态的文本，工程脚本增至 10 项。
- PR #12 的 macOS、Windows 与 security 三项远端检查全部通过，并已 rebase 合入 main；拆书任务切片从新的功能分支继续。
- 新增 schema v5，为模式卡记录唯一 `source_job_id`；即使 Fusion artifact 已写入后在模式卡落库瞬间崩溃，重试也只重新执行幂等物化，不会再次调用模型或生成第二张卡。
- 把同步拆书实现拆成 5 万字 Map、单书 Reduce 与跨书 Fusion 三层模型契约；旧同步接口保留一版作为开发回滚路径，产品页面只提交后台任务。
- 任务计划只持久化参考区段 ID、作品信息与字符范围，参考原文只在执行 Map 时从隔离表读取，不进入 Job input、Chunk input 或 Artifact；正文 AI 的数据边界不变。
- 新增真实可恢复拆书处理器：每次外部调用关联 Attempt，每块结果写入不可变 Artifact，失败只把当前块标为 failed；重试按 artifact key 复用所有已完成 Map/Reduce/Fusion。
- 故障矩阵在第 1、20、39、40 个 Map、首个单书 Reduce 与最终 Fusion 注入一次超时，六种场景均在重试后只多执行失败调用，总 artifact 固定 43 个，模式卡只物化一次。
- 取消场景验证当前已经完成的调用会先保存 Artifact，下一次调用前停止；任务页面可显示块进度、取消后续调用，并从 failed/interrupted/cancelled 状态继续。
- 拆书产品入口改为 `202 Accepted` 任务提交与 700ms 轮询；完成后重新载入项目摘要并展示模式卡，重新进入页面可发现未完成或失败任务。
- 本切片专项验证：Web lint、类型检查与 28/28 交互测试通过；API ruff、mypy 与 101/101 测试通过，其中可恢复拆书与迁移/归档专项 35/35 通过。
- 本切片完整 `pnpm run verify` 通过：仓库守卫、lint、类型检查、工程脚本 10/10、Web 28/28、API 101/101、Web 生产构建、独立 sidecar 构建和 Rust 桌面检查全部成功。
- 拆书任务 PR #14 的 macOS、Windows 与 security 三项检查全部通过，并已 rebase 合入 main。
- AI 章纲和完整章节候选新增独立 `chapter_brief` / `chapter_draft` 后台处理器；提交幂等键包含章节 revision、作者意图、provider/model、prompt version 与上下文 SHA-256。
- 排队后若章节 revision 或作品上下文变化，worker 会在调用模型前以 `stale_revision` / `context_changed` 安全失败，避免用过期资料付费生成。
- 章纲写入不可变 JSON artifact，只在作者点击“采用到章纲”后进入编辑表单；正文写入 text artifact 并幂等物化为 GenerationRun，仍须作者点击“采用并写入编辑器”才更新正文。
- GenerationRun 标识由 Job 稳定派生并写入 artifact metadata；候选物化瞬间崩溃后重试只重新物化，不重复模型调用，也不创建第二个候选。
- AI 共创面板已迁移到 `202 Accepted` 任务提交、进度轮询、取消和断点重试；旧同步章纲/正文接口继续保留一版作为开发兼容回滚路径。
- 章节任务专项验证 6 项：重复提交、候选批准门、provider 失败重试、物化崩溃、上下文变化阻断和后台 API 类型化结果均通过；API 全量增至 107/107，Web 仍为 28/28。
- 章节任务切片完整 `pnpm run verify` 通过：仓库守卫、lint、类型检查、工程脚本 10/10、Web 28/28、API 107/107、Web 生产构建、sidecar 构建与 Rust 桌面检查全部成功。
- 新增作品级全局任务中心，统一展示拆书、章纲、正文与审校任务的状态、进度、调用数、安全错误和不可变产物；支持取消、失败/中断/取消后的断点重试。
- 已完成任务可继续读取类型化结果；章纲和正文仍需作者点击确认才写入章节，Fusion 完成后可刷新项目资产，批准门没有被后台任务绕过。
- 任务中心只从会先强制保存正文的工作台入口，或无正文编辑器的拆书页入口打开；移除会绕过保存门的悬浮快捷入口。
- 修复从任务中心采用章纲后目录已更新、当前编辑区仍保留旧章节版本的问题；当前章节会在服务端 revision 变更后重新读取，自动保存只在本地草稿干净且没有进行中保存时采用外部版本，避免覆盖输入中的正文。
- 任务中心 React 行为测试覆盖失败任务重试、不可变产物查看、章纲候选确认和当前编辑器同步；Web 增至 30/30，lint 与严格类型检查通过。
- 真实浏览器使用隔离数据库在 1040×900 与 760×900 验证排队/失败/成功任务、进度、停止、断点重试、产物展开、章纲确认、窄屏详情和 Escape 关闭；采用后目录与中央编辑器均显示新标题，控制台无 warning/error。
- 任务中心切片完整 `pnpm run verify` 通过：仓库守卫、lint、严格类型检查、工程脚本 10/10、Web 30/30、API 107/107、Web 生产构建、独立 sidecar 构建和 Rust 桌面检查全部成功。
- 桌面恢复验收前复现了“新 sidecar 在旧租约到期前启动，只扫描一次后任务永久停在 running”的断点；运行时现把默认租约缩短为 15 秒，在模型阻塞期间由独立心跳每 5 秒内自动续租，并在运行期间每 5 秒内持续回收过期租约。
- 新增慢 provider 调用续租回归，以及“新运行时先启动、旧租约随后到期”自动恢复回归；后者验证 `lease_expired → recovered → leased → completed` 完整事件链。
- 章节任务故障矩阵明确覆盖断网、超时、限流与格式错误，四种故障均写入安全错误、保留既有结果并可重试且不重复正文候选；加上第 1/20/39/40 个 Map、Reduce、Fusion、取消与物化崩溃，M2 计划故障点已覆盖。
- 使用重新冻结的真实 sidecar 二进制强制 `SIGKILL` 后重启：20/40 进度与已完成 Artifact 内容/SHA-256 保持，任务依次进入 interrupted、queued 并由新 worker 领取；无令牌 API 仍返回 401。
- 从重新构建、ad-hoc 签名的只读 DMG 启动 Tauri 应用，真实子 sidecar 首次监听动态端口 64461；强杀 sidecar 并关闭/重启应用后，新 sidecar 改用 64838，任务事件为 `lease_expired → recovered → leased → failed`，安全失败原因可重试，20/40 进度与中断前第 20 块 Artifact 完整保留。
- 退出 DMG 中的 Tauri 主进程后父子 sidecar 全部回收，监听端口关闭；磁盘映像已安全卸载。macOS 当时处于锁屏，无法再读取发行版窗口可访问树；任务中心的完整交互与视觉已由同构 Web 构建在 1040×900、760×900 真实浏览器覆盖，桌面本轮专注验证发行进程、动态端口和持久恢复链。
- M2 收尾完整 `pnpm run verify` 通过：仓库守卫、lint、严格类型检查、工程脚本 10/10、Web 30/30、API 112/112、Web 生产构建、独立 sidecar 构建与 Rust 桌面检查全部成功；ad-hoc 签名 DMG 另行完整构建通过。

### 验收结论

- M2 的交付、故障矩阵、浏览器任务中心和真实 macOS DMG 恢复标准均已验证；进入 M3 模型网关、密钥与用量治理。

## M3：模型网关、密钥与用量治理

### 已完成

- 新增 ADR 0007，冻结 provider profile、任务绑定、能力降级、系统凭据、外发预览与浏览器会话降级边界；Ollama 原生支持保持在 P1。
- 从单一 AiGateway 拆出 ProviderAdapter、能力、统一结果/用量和错误类别；实现 OpenAI Responses 与通用 OpenAI-compatible Chat Completions 适配器。
- OpenAI Responses 正文使用 `response.output_text.delta` 流式事件；兼容端点只有明确声明流式能力时使用 SSE，否则安全降级为单次完整 delta。
- 401、403、429、5xx、超时、无效 JSON、取消和不支持能力统一为不泄漏响应正文的安全错误；默认测试使用 MockTransport、假流与脱敏回放，不访问付费模型。
- schema v6 增加全局 provider profile 和 Job/Attempt/Artifact profile ID、Token、耗时与费用；profile 元数据不进入作品归档，历史任务仍保留稳定来源标识。
- 模型线路台支持多个 OpenAI/OpenAI-compatible profile、安全自定义 base URL、模型、估价、能力快照、乐观 revision、删除和切换；OpenAI 固定官方 HTTPS 地址，兼容端点只允许 HTTPS 或回环 HTTP，拒绝 URL 凭据、查询串和危险协议。
- schema v7 增加章纲、正文、拆书与审校任务默认线路；任务提交时绑定指定 profile，之后切换活动线路也不会改变已排队 Job 与 Artifact。
- 每个 Attempt 记录输入/输出 Token、耗时、重试和估算费用；任务中心聚合展示调用后实际用量，profile 未填写价格时明确显示未知而不伪造金额。
- 章纲与正文入口加入显式外发确认：展示目标 profile/provider/model、数据类型、内容范围、字符数、预计输入/输出 Token 和费用；确认前不创建 Job，修改作者意图会使旧预览失效。
- macOS 使用系统 Keychain 保存每条 profile 密钥和活动标记；Web 只能查询存在/活动状态，不能读回明文。Rust 请求缓冲区和临时密钥在使用后清零，数据库、归档和日志泄漏扫描通过。
- 桌面 sidecar 启动时先延迟 Job worker，恢复所有仍存在的 Keychain profile，最后恢复活动线路，再显式启动 worker；避免中断任务在凭据恢复前抢跑。无活动线路时也会预载其他已保存线路，保证任务级分流可恢复。
- 浏览器开发模式支持多线路当前页面内存密钥，刷新即清除，不进入 localStorage、项目或数据库；真实浏览器验收中发现并修复了切换第二条线路后第一条会话密钥丢失的问题。
- Provider 回放夹具只保存脱敏响应和能力事件，带显式 `sanitized` 标记；仓库守卫继续扫描已跟踪和未跟踪文件中的敏感数据。

### 验证证据

- 完整 `pnpm run verify` 通过：仓库守卫、lint、严格类型检查、工程脚本 10/10、Web、API、生产构建、独立 sidecar 和 Rust desktop check 全绿；最终计数为 Web 33/33、API 137/137。
- Rust 常规测试 7/7 通过，另有 1 项真实 macOS Keychain 写入、读取、删除测试通过并确认无残留；多 profile 恢复顺序的假 Keychain/HTTP 集成测试验证非活动线路先加载、活动线路最后加载。
- 真实浏览器使用隔离数据库建立两条兼容线路并分别绑定章纲/正文：确认页显示章纲非活动线路、923 字符、1,016 输入 Token、1,200 输出 Token和约 0.0029 美元；确认前 Job 数为 0，确认后 Job 与 Attempt 均绑定章纲 profile。
- 不可达兼容端点最终显示“模型服务暂时不可用，可安全重试”，没有泄漏底层连接信息；740×900 窄屏模型线路台、任务分流与焦点入口可达，控制台 warning/error 为 0。
- macOS arm64 ad-hoc DMG 已重新完整构建，产物位于 `artifacts/desktop/墨舟_0.1.0_aarch64.dmg`；未执行付费模型冒烟。

### 验收结论

- PR #18 的 macOS、Windows 和 security 检查全部通过；M3 功能、凭据边界、跨平台编译、真实浏览器与 macOS 安装包验收完成，进入 M4 长篇上下文编译器。

## 遗留风险

- 当前 GitHub 免费套餐不能在私有仓库强制分支保护；本地 hook 可被刻意绕过，外部协作前必须升级或迁移。
- Rust 审计有 17 条来自 Tauri Linux/GTK 等传递依赖的维护或不安全告警，当前 0 个已知漏洞；后续随 Tauri 依赖更新复核，不能静默忽略。
- CI 使用的 rustsec/audit-check@v2 仍声明 Node 20 action runtime，GitHub 会强制以 Node 24 运行；等待上游 action 更新。
- macOS 安装包仍是 ad-hoc 签名，未公证。
- 其余风险按 PLAN.md 第 4、13 节持续跟踪。

# 当前任务

## PLAN M13–M17：作者智能扩展

### M13 场景语义与情节图原创性检查

- [ ] v18 场景图检查、发现与版本化阈值数据模型。
- [ ] 多书节点/边/顺序/角色职能确定性比较与黄金集。
- [ ] high/medium 门禁、局部重检、归档和报告隐私。
- [ ] 拆书实验室报告 UI、真实浏览器与完整 verify。

### M14 AI 增强剧情沙盘

- [ ] AI 沙盘结构化契约、Prompt 与 provider adapter 能力。
- [ ] 外发/费用预览、可恢复单轮 Job、取消和 Artifact 重放。
- [ ] 服务端动作裁决、确定性回退和候选隔离回归。
- [ ] AI/规则模式 UI、本地兼容协议浏览器验收与完整 verify。

### M15 资料研究员 Agent

- [ ] v20 研究会话、来源快照、发现、冲突和候选模型。
- [ ] 本地提取、模型归纳、引用范围复核、缓存与恢复。
- [ ] 候选资料卡逐条批准和 ContextPacket 隔离。
- [ ] 研究台 UI、注入/伪造引用安全测试、浏览器与完整 verify。

### M16 DOCX/EPUB 导入导出

- [ ] ZIP/XML/XHTML 安全解析器与攻击夹具。
- [ ] DOCX/EPUB 稿件预览、人工校正和事务导入。
- [ ] DOCX/EPUB 生成器、往返一致性和二进制下载。
- [ ] macOS/Windows CI、真实浏览器与完整 verify。

### M17 作者效率与关系图谱

- [ ] v21 批注、灵感、显式人物关系模型和 42 天日历。
- [ ] 批注锚点/过期、灵感候选门、人物/伏笔图谱服务。
- [ ] 连载台、批注、灵感箱、图谱 UI 与快捷键。
- [ ] 性能/可访问性/窄屏浏览器与最终完整 verify。

### 最终收尾

- [ ] 更新 PROGRESS、能力矩阵、README、ADR 与遗留风险。
- [ ] 安全审查、依赖/密钥扫描、全量构建测试与远端三项 CI。

## PLAN M2：可恢复 AI 任务运行时

- [x] 冻结任务状态机、幂等键、租约与重启恢复 ADR。
- [x] 建立 v4 Job、Attempt、Chunk、Artifact、Event 表与单机 worker 基础设施。
- [x] 提供任务列表、详情、产物查看、取消与重试 API，并把任务历史纳入项目归档。
- [x] 将拆书 Map、单书 Reduce、跨书 Fusion 迁移为可恢复分块任务。
- [x] 将真实章纲与写章迁移为幂等后台任务。
- [x] 实现前端任务中心、进度、取消、失败块重试和结果继续采用。
- [x] 完成第 1/20/39 块、Reduce、断网、限流、格式错误、取消和桌面重启故障验收。

## PLAN M1：创作可信度与核心可达性热修

- [x] 用 60 条正式事实复现并修复 AI 上下文只取最早 50 条的问题。
- [x] 在 1040、900、760 像素宽度提供可访问的 AI 导演入口。
- [x] 增加项目概要与章节正文按需读取接口，旧 Workspace 契约并存一版。
- [x] 建立 v1→v2→v3 显式顺序迁移与失败恢复验证。
- [x] 为桌面 sidecar 和 Web API 请求增加启动期随机会话令牌。
- [x] 执行 M1 完整自动化、真实浏览器和桌面验收。

## PLAN M0：工程治理与计划对齐（已完成）

- [x] 保存用户数据库一致性备份并建立 Git 基线。
- [x] 建立跨平台开发进程编排、仓库守卫和依赖扫描。
- [x] 建立 macOS/Windows verify 与 security CI。
- [x] 记录架构决策并建立真实能力状态矩阵。
- [x] macOS、Windows 和 security 首轮远端 CI 全绿。
- [x] 在全新目录验证锁文件安装和完整 verify。
- [x] 验证基线标签恢复，并冻结 0.1.0 基线。
- [x] 按产品负责人确认的免费私有仓库方案安装本地 pre-push 门，阻止直接更新或删除 main，并保留 PR 三项 CI 纪律。

以下内容是 R2 历史交付记录，不再作为当前未完成清单。

## R2 历史交付

- [x] 稳定数据目录
  - Acceptance：默认数据库位于 OS 用户应用数据目录，且不依赖启动目录；显式环境变量仍可覆盖。
  - Verify：配置单元测试。
  - Files：`config.py`、`test_config.py`。

- [x] 旧库无损迁移
  - Acceptance：目标不存在时通过 SQLite 一致性备份复制旧库，旧文件保留，目标已存在不覆盖。
  - Verify：迁移单元测试和现有开发库核验。
  - Files：`config.py`、`test_config.py`。

- [x] 数据库升级保护
  - Acceptance：schema version 可追踪；升级前创建备份；重复启动不重复备份；损坏或未来版本数据库拒绝写入。
  - Verify：数据库单元测试。
  - Files：`database.py`、`test_database.py`。

- [x] R2.1 发布门验证
  - Acceptance：lint、类型、全量测试、Web build、Rust check 全通过，现有作品迁移后数量一致。
  - Verify：`pnpm run verify` 和只读数据核验。

- [x] 桌面 API sidecar
  - Acceptance：桌面进程自行启动 FastAPI，动态选择仅监听 127.0.0.1 的端口，健康检查成功后再开放工作台，退出时回收子进程。
  - Verify：Rust 单元测试、`cargo check`、桌面开发运行。
  - Files：`lib.rs`、`Cargo.toml`、`sidecar.py`、Tauri 配置与构建脚本。

- [x] 前端动态 API 地址
  - Acceptance：Tauri 中通过 invoke 获取 sidecar 地址，Web 开发仍支持 `VITE_API_URL`/8765，所有 API 调用共享同一解析入口。
  - Verify：前端单元测试和真实桌面验收。
  - Files：`api.ts` 及测试。

- [x] 桌面安装包配置
  - Acceptance：Tauri bundle 启用，sidecar 作为外部二进制纳入产物；本机 release 构建可验证。
  - Verify：sidecar 构建、`desktop:build`。

- [x] 项目列表 API
  - Acceptance：`GET /api/projects` 返回按更新时间倒序的 `Project[]`，不含正文。
  - Verify：后端 API 测试。
  - Files：`repository.py`、`main.py`、`api.ts`、`test_api.py`。

- [x] 作品书架
  - Acceptance：启动可看到已有作品，打开后恢复工作区；退出回到书架且能再次打开。
  - Verify：前端交互测试、真实浏览器。
  - Files：`ProjectLibraryPage.tsx`、`App.tsx`、`CreateProjectForm.tsx`、`styles.css`、`App.test.tsx`。

- [x] 导航前立即保存
  - Acceptance：输入后立即切章、进拆书库或退出，保存成功后才导航；失败不导航。
  - Verify：前端交互测试。
  - Files：`useChapterAutosave.ts`、`WorkspaceShell.tsx`、`App.test.tsx`。

- [x] 发布门验证
  - Acceptance：lint、类型、前后端测试、Web build、Rust check 全通过；浏览器控制台无错误。
  - Verify：`pnpm run verify` 和真实浏览器走查。

- [x] 完整项目归档
  - Acceptance：导出覆盖项目全部业务数据与参考原文，协议有版本和 SHA-256，恢复点不递归进入归档。
  - Verify：导出范围与校验和 API 测试。
  - Files：`archive.py`、`main.py`、后端测试。

- [x] 安全恢复为副本
  - Acceptance：只接受 256 MiB 内、固定白名单和精确列结构的合法归档；所有 ID/引用重映射；绝不覆盖原作品。
  - Verify：完整往返、篡改拒绝、事务回滚测试。
  - Files：`archive.py`、`main.py`、后端测试。

- [x] 项目恢复点
  - Acceptance：可创建、列表并从压缩快照恢复新副本；列表不加载正文。
  - Verify：数据库迁移和恢复点 API 测试。
  - Files：`database.py`、`models.py`、`archive.py`、后端测试。

- [x] 书架归档与恢复体验
  - Acceptance：书架可下载归档、导入作品副本、创建与恢复快照，过程有禁用、成功与失败反馈。
  - Verify：前端交互测试和真实浏览器走查。
  - Files：`ProjectLibraryPage.tsx`、`App.tsx`、`api.ts`、契约、样式与测试。

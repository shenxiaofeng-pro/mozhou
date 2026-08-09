# 墨舟完整实施进度

> 执行依据：PLAN.md  
> 计划状态：已批准，范围冻结  
> 开始日期：2026-08-09  
> 当前阶段：M0 工程治理与计划对齐  
> 总体状态：M0 进行中；等待 GitHub workflow 权限，尚未达到 Definition of Done

## 已确认产品决策

| 决策 | 结论 |
|---|---|
| D1 分发与许可 | MVP 先按闭源私有测试推进；保持清洁实现，不复制 MiroFish 源码 |
| D2 AI 自动化 | 默认一键串联到单章候选稿；写入正文仍需作者确认 |
| D3 模型范围 | 首轮支持 OpenAI-compatible 与自定义 base URL；Ollama 原生体验放入 P1 |
| D4 平台顺序 | macOS 先行内测；Windows 在公开 MVP 前完成发布门 |

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
| M0 工程治理与计划对齐 | 进行中 | 已保护用户数据库并建立本地 Git 基线 |
| M1 创作可信度与核心可达性热修 | 未开始 | — |
| M2 可恢复 AI 任务运行时 | 未开始 | — |
| M3 模型网关、密钥与用量治理 | 未开始 | — |
| M4 长篇上下文编译器 | 未开始 | — |
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
- 建立仓库守卫，阻止数据库、构建产物、环境密钥、大文件和生成目录进入版本控制；守卫测试 3/3 通过。
- pnpm 高危依赖审计通过：未发现已知漏洞。
- 本地创建 macOS/Windows 完整 verify 和独立 security CI，以及 npm、uv、Cargo、GitHub Actions 的 Dependabot 配置。

### 当前基线

| 检查 | 结果 |
|---|---|
| Web Vitest | 26/26 通过 |
| FastAPI pytest | 68/68 通过 |
| Tauri Rust | 2/2 通过 |
| 用户数据库 quick_check | ok |
| 用户数据数量 | 8 个项目、17 个章节、2 本参考作品 |
| Git 基线 | 86cd5bc |

### 当前阻断

- 当前 GitHub CLI Token 具有 repo 权限但缺少 workflow 权限。
- GitHub 拒绝推送本地提交 bdb3c48，原因是该提交新增 .github/workflows/verify.yml。
- 需要为当前 GitHub 凭据增加 workflow scope 后重试；不会改用其他凭据绕过权限。

### 恢复后继续

- 推送并实际运行 macOS/Windows CI。
- CI 全绿后配置 main 分支保护。
- 建立 ADR 和能力状态矩阵。

### 剩余验证

- 全新目录从锁文件安装并执行完整 verify。
- macOS 与 Windows CI 验证。
- 依赖、密钥和大文件扫描。
- 从基线标签验证可恢复。

## 遗留风险

- 远程仓库已经建立，但主分支保护尚未生效。
- 远程私有仓库已建立，但远端目前只有基线；CI 提交因 workflow scope 不足尚未推送。
- Windows 原生构建证据尚未产生。
- macOS 安装包仍是 ad-hoc 签名，未公证。
- 其余风险按 PLAN.md 第 4、13 节持续跟踪。

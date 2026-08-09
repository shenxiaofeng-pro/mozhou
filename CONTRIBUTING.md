# 墨舟贡献约定

墨舟 MVP 目前在私有仓库开发。所有变更从受保护的 `main` 分支创建短生命周期分支，并通过 Pull Request 合入。

## 提交

提交标题采用 `类型: 简短说明`：

- `feat`：用户可见能力
- `fix`：缺陷修复
- `refactor`：不改变行为的结构调整
- `test`：测试或验收资产
- `docs`：文档
- `build`、`ci`、`chore`：构建、流水线和维护

每个提交只包含一个可独立验证的增量。不要提交数据库、参考原文、API Key、`.env`、安装包、缓存、`target` 或生成的 sidecar；提交前必须执行 `pnpm run guard:repository`。

## 合并门

Pull Request 至少满足：

1. 说明变更、风险和回滚方式。
2. 更新或新增与行为对应的自动化测试。
3. `quality (macos-14)`、`quality (windows-2022)` 与 `security` 全部通过。
4. 不降低测试、lint、类型检查、构建或安全扫描标准。
5. 数据、API 或归档协议变化同步更新版本、迁移测试和 [0.1.0 基线契约](docs/product/v0.1.0-baseline.md)。

`PLAN.md` 是已批准的冻结范围，实施期间只更新 `PROGRESS.md`，不得用代码变更顺带扩张产品范围。

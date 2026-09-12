# M36 本地创作安全门审查

> 审查日期：2026-09-12
>
> 范围：M28–M35 新增的稿件/参考导入、选题、拆书模式、原创迁移、CreativeContext、章节生产、Canon 回流和作者导航入口
> 结论：本地工程安全门已有自动化证据；签名发布和真实作者验收仍是外部待验项，不得因本文而标记完成。

## 安全边界

墨舟当前是单机、单用户、回环地址上的桌面应用，不是互联网多租户服务。桌面版每次启动生成独立的 256-bit 会话令牌，所有 `/api/` 请求都需通过固定请求头提交；请求不使用 Cookie，因此当前不应套用互联网 Cookie 会话的 CSRF 方案。如果未来开放局域网、远程访问或多用户协作，必须重新设计身份、授权、CSRF 和限流，不能复用当前单机假设。

## 门禁与证据

| 检查项 | 实现边界 | 自动化证据 | 结论 |
|---|---|---|---|
| 输入白名单 | M28–M35 关键请求模型限制枚举、长度、数量、SHA-256/revision，并对未知 JSON 字段 fail-closed | `test_m36_security_gate.py` 遍历不少于 65 个请求/嵌套模型 | 通过 |
| SQL 注入 | 业务值使用 SQLite `?` 占位符；只容许经审查的表名、列名、固定过滤片段和可变数量占位符列表 | `test_m36_security_gate.py` 会扫描特性模块中的动态 SQL；Canon/偏好状态表额外受 `_FEEDBACK_STATE_TABLES` 限制 | 通过 |
| 文件上传 | TXT/Markdown/PDF/DOCX/EPUB 均有大小、解码、页数/字符数和内容边界；低置信编码必须人工确认 | `test_safe_import.py`、`test_document_formats.py` | 通过 |
| ZIP/XML/PDF | 拒绝路径穿越、绝对路径、重复条目、加密包、符号链接、异常膨胀、DTD/ENTITY、DOCX 宏/外链和 PDF 活动内容 | `test_safe_import.py`、`test_document_formats.py` | 通过 |
| 密钥与日志 | API Key 仅进入系统凭据库/执行期内存；仓库守卫扫描密钥特征；结构化日志只接受固定字段，不接收正文、请求体或任意 metadata | `repository-guard.test.mjs`、`test_diagnostics.py`、Rust credential tests | 通过 |
| Loopback 令牌 | 桌面版验证令牌格式，用常数时间比较保护 `/api/`；健康端点不暴露数据 | `test_api.py`、`test_sidecar.py`、Rust `generates_a_fresh_256_bit_hex_session_token` | 通过 |
| CORS | 仅允许已知 Vite/Tauri 回环 origin，不使用 `*`，不允许 credential cookie | `test_api.py` | 通过 |
| 诊断导出 | 仅导出版本、系统、完整性、数量与脱敏路由；不含书名、正文、Prompt、路径、密钥或令牌 | `test_diagnostics.py` 使用哨兵值检查 ZIP | 通过 |
| 归档恢复 | 大小、格式版本、顶层字段、checksum、行模型和跨表血缘均 fail-closed；导入为新副本；未完成 Canon 任务恢复后标记中断并要求重提交 | `test_archive_api.py` 语义无效/孤儿回滚、M34 往返与 pending 任务恢复测试 | 通过（纳入全量门） |
| 模型外发 | 只读取冻结 CreativeContext；外发与未知费用需显式确认；参考原文不进入章节写作上下文 | Context/ChapterProduction/PatternAdaptation/Canon 专项测试 | 通过 |

## 本地复核命令

```bash
pnpm run guard:repository
uv run --project services/api --no-sync pytest \
  services/api/tests/test_m36_security_gate.py \
  services/api/tests/test_safe_import.py \
  services/api/tests/test_document_formats.py \
  services/api/tests/test_diagnostics.py \
  services/api/tests/test_api.py \
  services/api/tests/test_archive_api.py
```

M36 最终收口仍要求完整 `pnpm run verify`、发布 preflight、真实浏览器和 macOS 桌面冒烟；本文的专项测试不替代这些总门。

## 已知边界与回滚

- `pnpm run dev` 为浏览器开发显式开启无令牌兼容模式，并打印安全警告；它不能用作桌面发行方式。
- 依赖漏洞数据会随时间变化，线下不能用旧结果代替候选发布时的 npm/Python/Rust 审计。
- 报告格式 v2 只增加脱敏聚合字段，不改数据库；如需回滚，可独立撤回报告模型/UI，不影响作品数据。
- 任一密钥泄露、丢稿、归档非原子失败、Canon 候选越权写入或高风险原创性绕过，都是停测 P0；不得降低验收标准换取发布。

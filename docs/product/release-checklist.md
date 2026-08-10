# 桌面发布清单

## 1. 发布输入

- [ ] `main` 全部必需检查通过，工作区和锁文件干净。
- [ ] 标签为 `vMAJOR.MINOR.PATCH` 或明确的 `-rc.N` 预发布版本，且与应用版本一致。
- [ ] macOS Secrets：`APPLE_CERTIFICATE`、`APPLE_CERTIFICATE_PASSWORD`、`APPLE_SIGNING_IDENTITY`、`APPLE_ID`、`APPLE_PASSWORD`、`APPLE_TEAM_ID`、`KEYCHAIN_PASSWORD`。
- [ ] Windows Secrets：`AZURE_CLIENT_ID`、`AZURE_CLIENT_SECRET`、`AZURE_TENANT_ID`、`AZURE_ARTIFACT_SIGNING_ENDPOINT`、`AZURE_ARTIFACT_SIGNING_ACCOUNT`、`AZURE_ARTIFACT_SIGNING_PROFILE`。
- [ ] 发布说明不含作者数据、测试密钥或内部路径。

## 2. 自动发布门

- [ ] 完整 `pnpm run verify`：仓库守卫、lint、类型、脚本、Web/API、规模基准、生产构建、sidecar、Rust。
- [ ] npm/Python/Rust 依赖审计无未处置高危漏洞。
- [ ] 限制性许可证门通过，生成 CycloneDX `mozhou.cdx.json` 与 `NOTICE.txt`。
- [ ] macOS `.app` 深度签名验证、DMG 公证装订与镜像校验通过。
- [ ] Windows EXE/MSI Authenticode 全链验证通过，安装包内含独立 API sidecar。
- [ ] 每个安装包生成 SHA-256、发布记录、GitHub provenance 与 SBOM attestation。

## 3. 干净机矩阵

| 场景 | macOS 当前主版本 | macOS 上一主版本 | Windows 11 |
|---|---:|---:|---:|
| 无 Node/Python/Rust 首次安装并启动 | [ ] | [ ] | [ ] |
| 新建作品、写入、保存、退出、重启找回 | [ ] | [ ] | [ ] |
| 从上一候选升级，数据迁移与备份 | [ ] | [ ] | [ ] |
| 运行任务后强杀/断网/休眠并恢复 | [ ] | [ ] | [ ] |
| 磁盘不足、只读目录、SQLite busy 提示 | [ ] | [ ] | [ ] |
| 卸载应用后数据保留，再安装可恢复 | [ ] | [ ] | [ ] |
| 默认归档、完整资料归档和 Markdown 导出 | [ ] | [ ] | [ ] |

## 4. 发布物核验

- [ ] 安装包名称、版本、架构、大小与 `release-record.json` 一致。
- [ ] `SHA256SUMS.txt` 在另一台机器复算一致。
- [ ] `gh attestation verify <安装包> -R shenxiaofeng-pro/mozhou` 通过。
- [ ] SBOM/NOTICE 不含绝对路径、环境变量值或凭据。
- [ ] 升级前自动备份存在且 `PRAGMA quick_check` 通过。
- [ ] 已知限制、恢复说明、隐私说明和回滚安装包齐全。

## 5. 回滚

签名、公证、安全、安装、迁移或数据保留任一项失败时，不创建公开 MVP Release。保留上一稳定安装包和升级前数据库备份；新版本数据库不允许由旧版本静默写入。

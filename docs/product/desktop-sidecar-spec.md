# 墨舟桌面 API Sidecar 规格

## 问题

当前 Tauri 只是前端壳，桌面版依赖作者另开终端并在固定 `8765` 端口启动 FastAPI。release 二进制离开开发环境后不可独立使用，固定端口也可能冲突。

## 目标流程

1. Tauri 启动时从 `127.0.0.1` 选择一个空闲动态端口。
2. Rust 生成 256-bit 随机会话令牌，通过子进程环境传给独立 `mozhou-api` sidecar，并用 Tauri external binary 启动它。
3. Rust 轮询真实 `/health`，在限定时间内成功后才完成桌面初始化；失败则停止子进程并给出启动错误。
4. 前端通过只读 `api_connection` command 获取动态地址和会话令牌，令牌只保存在当前 WebView 内存，所有业务请求共享同一请求入口。
5. 桌面应用退出时回收 API 子进程；sidecar 输出被排空但不转发到页面。
6. 普通浏览器开发不调用 Tauri，继续使用 `VITE_API_BASE_URL`，未配置时走 Vite 的 8765 代理；版本化开发脚本必须显式开启无令牌兼容开关并输出警告。

## 打包

- Python API 使用 PyInstaller 生成当前平台的独立单文件二进制，最终用户无需安装 Python。
- 构建脚本按 Rust host triple 生成 Tauri 要求的 `mozhou-api-<target-triple>` 文件名。
- Tauri `bundle.externalBin` 收录 sidecar，`bundle.active` 开启。
- macOS 和 Windows 必须分别在对应系统原生构建，不进行 Python sidecar 跨平台编译。

## 安全边界

- API 只监听 `127.0.0.1`，Python 入口不接受外网 host。
- 除 `/health` 与 CORS 预检外，所有 `/api/*` 请求必须使用本次桌面启动令牌；缺失和错误令牌返回相同的 401 响应。
- 令牌不进入命令行、数据库、文件、URL、日志或 localStorage；桌面退出后随进程内存销毁。
- 网页侧不获得 shell 权限，只能调用返回 API 地址的 command。
- CSP 只增加 `http://127.0.0.1:*` 连接源。
- Rust 不把 sidecar stdout/stderr 注入 DOM，也不在命令行传递 API Key。
- 数据库仍由 R2.1 的稳定目录、迁移、备份和完整性门禁保护。

## 验收标准

1. 动态端口非 8765 也能打开书架并读写作品。
2. 8765 已被占用时桌面应用仍可启动。
3. sidecar 未就绪或提前退出时桌面启动失败，不显示一个持续报错的空工作台。
4. 关闭应用后对应端口不可连接，子进程不存在。
5. Web 模式、前端测试和 API 单独开发方式不回退。
6. `cargo test`、`cargo check`、整仓 `verify` 和本机桌面 release 构建通过。
7. API 对缺失、错误和正确令牌分别返回 401、401 和业务响应；8765 被占用时桌面仍通过动态端口正常工作。

## 后续

- 安装包签名、公证和自动更新需要发布证书，当前先产出本机可安装未签名包。

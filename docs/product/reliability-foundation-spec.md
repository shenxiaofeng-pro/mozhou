# 规格：作者资产可靠性底座

> 版本：v0.1  
> 日期：2026-08-09  
> 状态：首批已交付

## Objective

在继续扩展多 Agent 能力前，先让真实网文作者能够安全地保存正文、离开作品并重新打开已有作品。本切片面向单机单用户，覆盖“正文即时落盘门禁”和“作品书架”两条最短闭环。

## Assumptions

1. “退出作品”表示回到作品书架，不删除作品。
2. 导航前保存失败时，保留当前编辑器和本地草稿，不执行导航。
3. 第一版书架支持列出、打开和新建；归档、删除、导出与恢复进入后续切片。
4. 作品列表只返回项目元数据，不返回章节正文和拆书原文。

## Tech Stack

- React 19.2、TypeScript、Vite、Vitest。
- FastAPI、Pydantic、SQLite、pytest。
- Tauri 2 继续复用同一 Web 工作台。

## Commands

```bash
pnpm --filter @mozhou/web test
uv run --project services/api --no-sync pytest services/api/tests
pnpm run lint
pnpm run typecheck
pnpm run build
pnpm run desktop:check
pnpm run verify
```

## Project Structure

- `apps/web/src/hooks/useChapterAutosave.ts`：正文保存队列与立即落盘接口。
- `apps/web/src/components/WorkspaceShell.tsx`：切章、拆书库和退出前的保存门禁。
- `apps/web/src/components/ProjectLibraryPage.tsx`：作品书架。
- `apps/web/src/App.tsx`：启动恢复、作品打开与页面状态。
- `services/api/app/repository.py`：轻量项目列表查询。
- `services/api/app/main.py`：项目列表 API。
- `apps/web/src/App.test.tsx`、`services/api/tests/test_api.py`：行为回归测试。

## Code Style

公开动作使用作者能理解的领域词，例如 `flushNow`、`openProject`、`returnToLibrary`。状态更新依赖旧值时使用函数式更新；数据库查询只选择书架需要的项目字段。

```ts
async function navigateAfterSave(action: () => void) {
  if (await flushNow()) action()
}
```

## Testing Strategy

- 前端行为测试：修改正文后不等待 700ms，立即切章、打开拆书库或退出，必须先调用保存；保存失败时不得离开。
- 前端书架测试：已有项目可见、可打开；退出当前作品后可重新打开。
- API 测试：项目按最近更新时间排序，响应不含章节正文。
- 真实浏览器：检查书架、写作台、拆书库往返以及控制台。

## Boundaries

- Always：导航前保存、保留 revision 门禁、列表不返回正文、错误给出下一步。
- Ask first：删除项目、改变参考原文作用域、引入新依赖。
- Never：保存失败后静默导航、覆盖较新 revision、在书架响应中返回正文或参考原文。

## Success Criteria

1. 正文输入后立即切章、进拆书库或退出，不丢失最近输入。
2. 保存失败时停留在当前章节并允许重试。
3. 应用启动时能显示已有作品书架；退出后仍可重新打开同一作品。
4. 项目列表只返回 `Project` 元数据并按最近更新排序。
5. 新增行为测试通过，完整 `pnpm run verify` 通过。

## Follow-up Milestones

1. 固定 OS 数据目录、数据库迁移、自动备份与恢复。
2. FastAPI sidecar、安装包、进程健康检查。
3. 统一可恢复任务引擎，覆盖 AI 写章和长篇拆书。
4. 区段卡→单书卡→跨书融合、全局拆书库和可版本化应用蓝图。
5. 长篇上下文编译器、来源证据、原创性门禁和七维审校。

# Spec：东方玄幻与西方奇幻题材扩展

## Objective

把墨舟从“历史重生、都市重生优先”扩展为同时正式支持东方玄幻和西方奇幻的中文长篇创作工作台。新增题材必须贯穿新建/导入、作品书架、整书导演、章纲/正文生成、上下文、审校、拆书库、归档与封测模板，不能只停留在一个下拉选项。

本批次采用以下兼容性决定：

1. `eastern_fantasy` 对应“东方玄幻”，`western_fantasy` 对应“西方奇幻”。
2. 两个新题材默认允许非重生故事，不强制主角拥有未来知识或双时间线。
3. 为保持旧数据库、归档和任务快照无损，底层 `rebirth_year` / `rebirth_location` 字段暂不改名；在非重生题材中分别解释为“故事纪年”和“起始地域（世界区域）”。
4. 既有 `divergence_point` 在非重生题材中解释为“故事引爆点”；既有 `rebirth_logic` 审校维度扩展为“世界机制/重生逻辑”，不更改持久化枚举值。
5. 本批次交付题材感知底座与两类起航模板；独立修炼/魔法体系结构化编辑器留作后续增强。

### Success criteria

- 作者能新建或导入四种题材，保存、重开、归档和恢复后题材不丢失。
- 东方玄幻/西方奇幻界面不再显示“必须重生”的文案，年份输入允许架空纪年。
- 整书导演、章纲、正文和审校 Prompt 明确识别四种题材，并对玄幻检查力量体系/境界代价，对奇幻检查魔法规则/种族阵营/资源成本。
- 封测模板新增东方玄幻和西方奇幻各一个十章起航方案。
- 旧项目、schema v22 和归档 v10 无需数据迁移，现有测试全部保持通过。

## Tech Stack

- FastAPI、Pydantic、SQLite：题材枚举、模板、上下文与 AI 契约。
- React 19、TypeScript、Vite：新建、导入、书架、导演与工作区题材感知文案。
- pytest、Vitest：API/归档/模板和 UI 行为回归。

## Commands

```bash
pnpm run lint
pnpm run typecheck
pnpm run test
pnpm run test:backend
pnpm run verify
pnpm run dev
```

## Project Structure

```text
services/api/app/models.py          # Genre 契约
services/api/app/ai.py              # 题材感知 AI 指令
services/api/app/context/           # 通用作品锚点与资料选择
services/api/app/beta.py            # 四题材起航模板
apps/web/src/genre.ts               # 前端题材标签和锚点文案
apps/web/src/components/            # 新建、导入、书架、工作区、导演和审校
packages/contracts/src/index.ts     # TypeScript Genre 契约
services/api/tests/                 # API、模板、归档和 Prompt 回归
apps/web/src/**/*.test.tsx          # 题材选择与显示回归
```

## Code Style

题材分支集中在明确 helper 中，避免各组件各写一套二选一判断：

```ts
export function isRebirthGenre(genre: Genre): boolean {
  return genre === 'historical_rebirth' || genre === 'urban_rebirth'
}

export function getStoryAnchorLabels(genre: Genre) {
  return isRebirthGenre(genre)
    ? { year: '重生年份', location: '重生地点', anchor: '重生锚点' }
    : { year: '故事纪年', location: '起始地域', anchor: '世界锚点' }
}
```

## Testing Strategy

- 契约测试：四个枚举值都能创建项目，未知题材仍返回 422。
- 兼容测试：新题材项目归档/恢复保持 genre 和锚点字段；旧归档不变。
- AI 测试：系统指令列出四题材，字段重生成白名单接受新枚举；示范模型对两个新题材输出对应场景。
- UI 测试：新建表单显示四类，选择玄幻/奇幻后切换为故事纪年/起始地域并提交正确 payload；旧重生题材仍显示旧标签。
- 完整验证：运行仓库统一 `pnpm run verify`，并在 1280/1040/760px 真实浏览器检查无横向溢出和控制台错误。

## Boundaries

- Always：保持旧字段、旧 enum 值和归档兼容；所有题材输入继续由 Pydantic 白名单验证；AI 结果继续停在候选区。
- Ask first：删除/重命名持久化字段、把力量/魔法体系拆成新 schema、改变现有重生作品行为。
- Never：自动把旧作品改成新题材；让玄幻/奇幻默认拥有重生知识；为适配新题材降低原创性门禁或资料来源要求。

## Open Questions

本批次没有阻断性问题。后续可独立决定是否增加“修炼体系设计器”“魔法体系设计器”“种族/宗门/阵营图谱”和新题材专用黄金评测集。

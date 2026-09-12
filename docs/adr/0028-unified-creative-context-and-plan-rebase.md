# ADR 0028：统一 CreativeContext 与显式计划重基

## 状态

已接受（2026-09-12）

## 背景

现有章纲和正文使用版本化 `ContextPacket`，但整书启动、卷纲扩展、蓝图字段重生成和章节审校仍各自拼接上下文。结果是相同项目在不同入口可能获得不同的选题、模式、蓝图与 Canon 视图，也难以证明参考原文没有从某条旁路进入模型。另一方面，选题或写作配方变化后，既有蓝图、卷纲和滚动计划只靠零散 `stale` 标记，作者看不到影响范围，也没有保留锁定内容的重基候选。

产品需要一条可审计且可预算的上下文边界：无论 AI 在开书、规划、写章、审校还是定稿回灌，模型只能消费同一种安全包；依赖变化必须变成作者可见的计划复核，而不是静默混用新旧规则。

## 决定

1. `CreativeContextService` 是所有模型创作入口的唯一上下文编译接口。它以 `purpose` 和 typed `subject` 区分 startup、expansion、field、brief、draft、candidate-review 与 canon-reconciliation；旧的章纲/正文 `task_type` 只保留一版兼容映射。
2. 每个 `ContextPacket` 固定记录 purpose、subject、token 预算、入选项、阻断原因、当前 WritingPatternProfile 指纹，以及已确认选题、项目模式、基础蓝图和主体内容组成的依赖快照与指纹。任务只绑定不可变 packet，并在模型调用前复核依赖。
3. 模型只接收 `rendered_context`。渲染内容不得包含参考原文、作品标题、来源 ID、证据摘录或内部谱系；这些信息即使存在于本地审计记录，也不能作为 provider 输入。嵌套创作内容继续按不可信数据处理。
4. 当前项目模式以一个紧凑、整体、required 的安全约束项进入所有 purpose。8K、16K 和 24K 预算下均不得静默删除或拆散；若连同其他必含约束超过预算，packet 明确阻断，预览/提交/worker 均保持 Adapter 零调用。
5. Director、Chapter Job、Review 与后续 Canon 服务不得再自行查询并拼接模型上下文。迁移期间旧方法只能作为调用统一服务的 Adapter，并以黄金快照验证行为；最终删除模型旁路。
6. BookBlueprint、VolumePlan 和 RollingChapterPlan 保存创建时的依赖指纹。当前选题、profile 或基础蓝图变化时，计划进入待复核状态；读取影响预览不能修改任何计划。
7. 计划重基只能创建隔离候选。候选复制当前正式计划，允许作者或 AI 调整未锁内容，强制逐字段保留蓝图锁、卷锁和章节计划锁；已定稿正文永不进入重基写集合。
8. 采用重基候选使用单个 `BEGIN IMMEDIATE` 事务，重新验证候选 revision、当前依赖指纹和全部目标 revision。任一依赖变化或并发修改都以 409 拒绝，不部分应用，也不猜测合并。
9. 新表和归档只追加版本。旧 ContextPacket 可升级为明确带 `legacy_dependency_snapshot` 阻断的只读记录，不伪造新依赖；旧计划在首次读取时建立可解释的兼容依赖，不自动重写作者内容。

## 结果

- 任一创作入口都遵守相同的资料选择、模式约束、预算和隐私规则，删除某个 UI 按钮不再改变模型上下文行为。
- 作者能看到选题或配方变更影响哪些计划，并在保留锁定判断的候选区完成重基。
- 过期 packet、旧计划和并发候选不能污染新蓝图或已批准正文。
- 代价是 ContextPacket 契约、计划依赖、归档闭包和旧入口迁移测试更复杂；这是消除创作旁路所需的集中复杂度。

## 回滚边界

可以按 purpose 临时切回旧编译 Adapter，但 Adapter 仍必须经过中央 CreativeSafety 门，且不能恢复手工 provider JSON 拼接。可以关闭重基生成入口，但必须保留已有依赖快照、待复核状态和候选历史；不得把 stale 计划静默标回 current。schema v29 与归档 v16 只通过后续追加迁移演进，不降级覆盖用户数据库。

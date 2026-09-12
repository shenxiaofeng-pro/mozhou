import type { CraftPatternAssetType, CraftPatternDimension } from '@mozhou/contracts'

export const craftDimensionLabels: Record<CraftPatternDimension, string> = {
  era: '时代与世界阶段',
  core_desire: '核心欲望',
  conflict_causality: '冲突因果',
  resource_system: '资源体系',
  key_scene_sequence: '关键场景顺序',
  ending: '阶段与最终结局',
  hook_mechanics: '开篇与章末钩子',
  promise_payoff_cadence: '承诺与兑现节奏',
  emotional_rhythm: '情绪回报',
  information_reveal: '信息揭示',
  foreshadowing_cycle: '伏笔回收',
  scene_design: '场景设计',
  pov_narrative_distance: '视角与叙事距离',
  expression_parameters: '表达参数',
  power_progression: '能力与升级阶梯',
}

export const craftAssetTypeLabels: Record<CraftPatternAssetType, string> = {
  stage: '约 50 万字阶段卡',
  book_evolution: '单书演变卡',
  fusion_material: '多书融合素材',
}

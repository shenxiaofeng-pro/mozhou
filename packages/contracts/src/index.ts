export type Genre =
  | 'historical_rebirth'
  | 'urban_rebirth'
  | 'eastern_fantasy'
  | 'western_fantasy'

export type ChapterStatus = 'planned' | 'drafted' | 'reviewing' | 'approved'

export type GenerationState = 'context_ready' | 'generating' | 'drafted' | 'applied' | 'interrupted'

export type JobKind =
  | 'chapter_brief'
  | 'chapter_draft'
  | 'reference_segment_map'
  | 'reference_book_reduce'
  | 'reference_fusion'
  | 'review'
  | 'sandbox_ai_round'
  | 'research_extraction'
  | 'comic_season_plan'
  | 'comic_episode_script'
  | 'topic_decision'
  | 'pattern_adaptation'

export type JobState =
  | 'queued'
  | 'running'
  | 'pause_requested'
  | 'cancelled'
  | 'succeeded'
  | 'failed'
  | 'interrupted'

export type JobAttemptState = 'running' | 'succeeded' | 'failed' | 'interrupted' | 'cancelled'

export type JobChunkState = 'queued' | 'running' | 'cancelled' | 'succeeded' | 'failed' | 'interrupted'

export type TimelineLayer = 'original' | 'novel'

export type FactKind = 'state_change' | 'open_thread'

export type FactChangeSetState = 'candidate' | 'applied' | 'rejected'

export type KnowledgeConfidence = 'certain' | 'likely' | 'uncertain'

export type KnowledgeStatus = 'valid' | 'candidate_invalid' | 'invalid'

export type KnowledgeReviewAction = 'keep_valid' | 'confirm_invalid'

export type StoryEntityKind = 'character' | 'resource'

export type StoryThreadStatus = 'open' | 'resolved' | 'abandoned'

export type SourceKind = 'historical_record' | 'news' | 'industry' | 'personal_note'

export type SourceConfidence = 'high' | 'medium' | 'low'

export type ReferenceFormat = 'txt' | 'markdown' | 'pdf' | 'docx' | 'epub'

export type ReferenceRightsBasis = 'self_owned' | 'authorized' | 'public_domain'

export type ReferencePatternDimension =
  | 'era'
  | 'core_desire'
  | 'conflict_causality'
  | 'resource_system'
  | 'key_scene_sequence'
  | 'ending'

export type BlueprintMode = 'preserve' | 'adjust' | 'reconstruct'

export type BlueprintEntityKind = 'character' | 'location' | 'organization' | 'proper_noun'

export type OriginalityRiskLevel = 'low' | 'medium' | 'high'

export type OriginalityStatus = 'needs_check' | 'blocked' | 'review_required' | 'passed'

export type ReferenceApplicationLifecycleState = 'draft' | 'active' | 'archived'

export type CraftPatternAssetType = 'stage' | 'book_evolution' | 'fusion_material'

export type CraftPatternLifecycleState = 'active' | 'archived'

export type CraftPatternDimension =
  | ReferencePatternDimension
  | 'hook_mechanics'
  | 'promise_payoff_cadence'
  | 'emotional_rhythm'
  | 'information_reveal'
  | 'foreshadowing_cycle'
  | 'scene_design'
  | 'pov_narrative_distance'
  | 'expression_parameters'
  | 'power_progression'

export type OriginalitySignal =
  | 'phrase_overlap'
  | 'proper_noun'
  | 'character_combination'
  | 'beat_sequence'
  | 'multi_dimension'

export type BookBlueprintField =
  | 'title'
  | 'genre'
  | 'rebirth_year'
  | 'rebirth_location'
  | 'target_audience'
  | 'core_selling_points'
  | 'core_desire'
  | 'divergence_point'
  | 'long_term_promise'
  | 'ending_direction'
  | 'protagonist_arc'
  | 'resource_growth'
  | 'relationship_design'

export type TopicDecisionField =
  | 'target_platform'
  | 'target_audience'
  | 'subgenre'
  | 'premise'
  | 'core_desire'
  | 'long_term_promise'
  | 'first_three_chapter_promise'
  | 'constraints'
  | 'forbidden_elements'
  | 'reference_purpose'
  | 'reality_anchor'
  | 'first_ten_chapter_goal'

export type TopicDecisionStatus = 'draft' | 'confirmed' | 'pending_reconfirmation'

export type ProjectNextAction =
  | 'confirm_topic'
  | 'review_topic_changes'
  | 'plan_book'
  | 'review_downstream_plans'
  | 'continue_writing'

export type TopicDecisionCandidateState = 'candidate' | 'selected' | 'rejected'

export type DirectorWorkflow =
  | 'director_startup'
  | 'director_expansion'
  | 'director_field_regeneration'
  | 'director_chapter_pipeline'

export type DirectorPipelineStage = 'context' | 'brief' | 'pre_review' | 'draft'

export type AiProvider = 'unavailable' | 'openai' | 'openai_compatible'

export type ContinuitySeverity = 'warning' | 'info'

export type ContinuityIssueKind =
  | 'future_knowledge_review'
  | 'overdue_thread'
  | 'rhythm_gap'
  | 'repeated_beat'
  | 'entity_state_gap'
  | 'source_year_mismatch'

export type ReviewDimension =
  | 'continuity'
  | 'serial_rhythm'
  | 'character'
  | 'realism'
  | 'rebirth_logic'
  | 'style'
  | 'format'

export type ReviewSeverity = 'info' | 'warning' | 'critical'

export type ReviewFindingState = 'open' | 'accepted' | 'rejected' | 'resolved'

export type ReviewEvidenceKind = 'body' | 'structured'

export type ReviewDimensionState = 'succeeded' | 'failed'

export type ChapterVersionSource =
  | 'initial'
  | 'manual_save'
  | 'generation_candidate'
  | 'generation_apply'
  | 'change_set_apply'
  | 'rollback'

export type TextChangeSetState = 'candidate' | 'applied' | 'rejected'

export interface CreateProjectInput {
  title: string
  genre: Genre
  rebirth_year: number
  rebirth_location: string
  chapter_target_words: number
  safety_buffer_chapters: number
  template_id: string | null
  topic_seed: string
}

export interface Project {
  id: string
  title: string
  genre: Genre
  rebirth_year: number
  rebirth_location: string
  chapter_target_words: number
  safety_buffer_chapters: number
  created_at: string
  updated_at: string
}

export interface TopicDecisionContent {
  target_platform: string
  target_audience: string
  subgenre: string
  premise: string
  core_desire: string
  long_term_promise: string
  first_three_chapter_promise: string
  constraints: string[]
  forbidden_elements: string[]
  reference_purpose: string
  reality_anchor: string
  first_ten_chapter_goal: string
}

export interface TopicDecision {
  id: string
  project_id: string
  content: TopicDecisionContent
  status: TopicDecisionStatus
  locks: Record<TopicDecisionField, boolean>
  field_versions: Record<TopicDecisionField, number>
  rejection_reasons: Partial<Record<TopicDecisionField, string>>
  source_template_id: string | null
  source_job_id: string | null
  source_candidate_ids: string[]
  revision: number
  confirmed_revision: number | null
  plan_stale: boolean
  created_at: string
  updated_at: string
}

export interface UpdateTopicDecisionInput {
  content: TopicDecisionContent
  changed_fields: TopicDecisionField[]
  lock_updates: Partial<Record<TopicDecisionField, boolean>>
  rejection_reason_updates: Partial<Record<TopicDecisionField, string | null>>
  expected_revision: number
}

export interface ConfirmTopicDecisionInput {
  expected_revision: number
}

export interface TopicDecisionCandidateRequest {
  expected_revision: number
  author_intent: string
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
}

export interface TopicDecisionRegenerationRequest extends TopicDecisionCandidateRequest {
  target_field: TopicDecisionField
}

export interface TopicDecisionOutboundPreview {
  mode: 'full' | 'field_regeneration'
  target_field: TopicDecisionField | null
  profile_id: string | null
  profile_name: string
  provider: string
  model: string
  data_types: string[]
  content_scope: string
  character_count: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_calls: number
  estimated_cost_microusd: number | null
}

export interface TopicDecisionCandidate {
  id: string
  ordinal: number
  label: string
  content: TopicDecisionContent
  changed_fields: TopicDecisionField[]
  rationale: string
  risks: string[]
  state: TopicDecisionCandidateState
  rejection_reason: string | null
}

export interface TopicDecisionCandidateSet {
  job_id: string
  project_id: string
  based_on_revision: number
  target_field: TopicDecisionField | null
  candidates: TopicDecisionCandidate[]
}

export interface SelectTopicDecisionCandidateInput {
  job_id: string
  candidate_id: string
  selected_fields: TopicDecisionField[]
  expected_revision: number
}

export interface RejectTopicDecisionCandidateInput {
  job_id: string
  candidate_id: string
  reason: string
  expected_revision: number
}

export interface DiagnosticCheck {
  key: string
  status: 'ok' | 'warning' | 'error'
  message: string
}

export interface DiagnosticSummary {
  generated_at: string
  app_version: string
  schema_version: number
  operating_system: string
  architecture: string
  python_version: string
  database_bytes: number
  free_disk_bytes: number
  counts: Record<string, number>
  checks: DiagnosticCheck[]
}

export type BetaFeedbackCategory =
  | 'workflow'
  | 'ai_quality'
  | 'reliability'
  | 'originality'
  | 'usability'

export type BetaFeedbackContext =
  | 'writing'
  | 'director'
  | 'review'
  | 'reference'
  | 'recovery'
  | 'release'

export type BetaEventType =
  | 'manuscript_export'
  | 'project_export'
  | 'recovery_restore'
  | 'report_export'

export interface BetaTemplate {
  id: string
  label: string
  genre: Genre
  suggested_title: string
  rebirth_year: number
  rebirth_location: string
  idea_prompt: string
  reality_anchor: string
  first_ten_chapter_goal: string
}

export interface CreateBetaFeedbackInput {
  category: BetaFeedbackCategory
  context: BetaFeedbackContext
  rating: number
  note: string
}

export interface BetaFeedback extends CreateBetaFeedbackInput {
  id: string
  project_id: string
  created_at: string
}

export interface BetaMilestone {
  key: string
  label: string
  completed: boolean
  evidence_count: number
}

export interface BetaMetrics {
  chapter_count: number
  written_chapter_count: number
  approved_chapter_count: number
  ai_candidate_count: number
  ai_applied_count: number
  ai_adoption_rate: number | null
  mean_manual_modification_ratio: number | null
  review_finding_count: number
  review_accepted_count: number
  review_acceptance_rate: number | null
  median_seconds_to_approved_chapter: number | null
  estimated_cost_microusd: number
  failed_or_interrupted_jobs: number
  recovered_retry_jobs: number
  retry_recovery_rate: number | null
  open_critical_findings: number
  originality_blocked_count: number
}

export interface BetaEvaluationReport {
  format: 'mozhou-closed-beta-report'
  format_version: 1
  generated_at: string
  project_id: string
  template_ids: string[]
  milestones: BetaMilestone[]
  metrics: BetaMetrics
  feedback: BetaFeedback[]
  privacy_notice: string
}

export type SandboxActorKind = 'character' | 'faction'

export type SandboxActionKind =
  | 'observe'
  | 'negotiate'
  | 'invest'
  | 'investigate'
  | 'relocate'
  | 'mobilize'
  | 'publicize'
  | 'trade'

export type SandboxRunState =
  | 'ready'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'budget_exhausted'

export type SandboxCandidateKind = 'chapter_outline' | 'fact_change'

export type SandboxCandidateState = 'candidate' | 'approved' | 'rejected'

export type SandboxVariableValue = boolean | number | string

export type SandboxRoundOrigin = 'rules' | 'ai'

export interface SandboxActor {
  id: string
  name: string
  kind: SandboxActorKind
  goal: string
  location: string
  resources: Record<string, number>
  knowledge: string[]
  capabilities: string[]
  allowed_actions: SandboxActionKind[]
  relationships: Record<string, number>
}

export interface SandboxTemplate {
  id: string
  label: string
  description: string
  genres: Genre[]
  suggested_variables: Record<string, SandboxVariableValue>
  actors: SandboxActor[]
}

export interface CreateSandboxSnapshotInput {
  label: string
  template_id?: string
  actors?: SandboxActor[]
}

export interface SandboxSnapshot {
  id: string
  project_id: string
  label: string
  engine_version: string
  actor_count: number
  snapshot_sha256: string
  source_counts: Record<string, number>
  actors: SandboxActor[]
  created_at: string
}

export interface SandboxForcedAction {
  round_number: number
  actor_id: string
  action_kind: SandboxActionKind
  target_actor_id?: string
  location: string
  required_knowledge: string[]
}

export interface CreateSandboxBranchInput {
  label: string
  parent_branch_id?: string
  seed: number
  variables: Record<string, SandboxVariableValue>
  forced_actions: SandboxForcedAction[]
}

export interface SandboxBranch {
  id: string
  project_id: string
  snapshot_id: string
  parent_branch_id: string | null
  label: string
  seed: number
  variables: Record<string, SandboxVariableValue>
  forced_actions: SandboxForcedAction[]
  created_at: string
}

export interface SandboxAction {
  actor_id: string
  actor_name: string
  action_kind: SandboxActionKind
  target_actor_id: string | null
  target_actor_name: string | null
  location: string
  costs: Record<string, number>
  required_knowledge: string[]
  summary: string
}

export interface SandboxAiActionDraft {
  actor_id: string
  action_kind: SandboxActionKind
  target_actor_id: string | null
  location: string
  required_knowledge: string[]
  motive: string
  intended_consequence: string
}

export interface SandboxOutcome {
  actor_id: string
  summary: string
  resource_changes: Record<string, number>
  relationship_changes: Record<string, number>
  location_change: string | null
  momentum_change: number
  confidence: number
}

export interface SandboxRound {
  id: string
  run_id: string
  ordinal: number
  actions: SandboxAction[]
  outcomes: SandboxOutcome[]
  assumptions: string[]
  evidence: Array<Record<string, string>>
  origin: SandboxRoundOrigin
  model_proposals: SandboxAiActionDraft[]
  rejected_proposals: Array<Record<string, string>>
  job_id: string | null
  state_before_sha256: string
  state_after_sha256: string
  created_at: string
}

export interface SandboxRun {
  id: string
  project_id: string
  branch_id: string
  state: SandboxRunState
  requested_rounds: number
  completed_rounds: number
  action_budget: number
  actions_used: number
  current_state_sha256: string
  execution_mode: SandboxRoundOrigin
  created_at: string
  updated_at: string
  completed_at: string | null
  rounds: SandboxRound[]
}

export interface SandboxConclusion {
  round_number: number
  actor_id: string
  statement: string
  assumptions: string[]
  evidence: Array<Record<string, string>>
  confidence: number
  impact_chain: string[]
  counterexample: string
}

export interface SandboxReport {
  run_id: string
  branch_id: string
  snapshot_sha256: string
  state: SandboxRunState
  disclaimer: string
  conclusions: SandboxConclusion[]
  final_scores: Record<string, number>
}

export interface SandboxInterviewAnswer {
  question: string
  answer: string
  knowledge_basis: string[]
  confidence: number
}

export interface SandboxInterview {
  run_id: string
  actor_id: string
  actor_name: string
  disclaimer: string
  answers: SandboxInterviewAnswer[]
}

export interface CreateSandboxCandidateInput {
  kind: SandboxCandidateKind
  source_round: number
  target_chapter_id?: string
  title: string
}

export interface SandboxCandidate {
  id: string
  project_id: string
  run_id: string
  target_chapter_id: string | null
  source_round: number
  kind: SandboxCandidateKind
  title: string
  content: Record<string, unknown>
  state: SandboxCandidateState
  created_at: string
  updated_at: string
  decided_at: string | null
}

export interface SandboxComparison {
  run_ids: string[]
  comparable: boolean
  snapshot_sha256: string
  scores: Record<string, Record<string, number>>
  differences: string[]
}

export interface SandboxWorkspace {
  snapshots: SandboxSnapshot[]
  branches: SandboxBranch[]
  runs: SandboxRun[]
  candidates: SandboxCandidate[]
}

export interface SandboxAiPreview {
  task_type: 'sandbox'
  run_id: string
  round_number: number
  state_sha256: string
  snapshot_sha256: string
  profile_id: string | null
  profile_name: string
  provider: string
  model: string
  data_types: string[]
  content_scope: string
  actor_count: number
  character_count: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_microusd: number | null
  prompt_version: string
  context_sha256: string
}

export interface SubmitSandboxAiRoundInput {
  expected_state_sha256: string
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
}

export interface ProjectArchive {
  format: 'mozhou-project'
  format_version: 1 | 2 | 3 | 4 | 5 | 6
  exported_at: string
  source_project_id: string
  source_project_title: string
  schema_version: number
  tables: Record<string, Array<Record<string, unknown>>>
  checksum_sha256: string
}

export interface BookBlueprintContent {
  title: string
  genre: Genre
  rebirth_year: number
  rebirth_location: string
  target_audience: string
  core_selling_points: string[]
  core_desire: string
  divergence_point: string
  long_term_promise: string
  ending_direction: string
  protagonist_arc: string
  resource_growth: string
  relationship_design: string
}

export interface BookBlueprint {
  id: string
  project_id: string
  idea: string
  content: BookBlueprintContent
  locks: Record<BookBlueprintField, boolean>
  field_versions: Record<BookBlueprintField, number>
  stale_fields: BookBlueprintField[]
  plan_stale: boolean
  source_candidate_id: string | null
  revision: number
  created_at: string
  updated_at: string
}

export interface DirectorStartupRequest {
  idea: string
  reality_anchor: string
  candidate_count: number
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
}

export interface DirectorStartupCandidate {
  id: string
  ordinal: number
  label: string
  blueprint: BookBlueprintContent
  why_distinct: string
  risks: string[]
}

export interface DirectorStartupProposalSet {
  job_id: string
  project_id: string
  idea: string
  candidates: DirectorStartupCandidate[]
}

export interface SelectDirectorCandidateInput {
  job_id: string
  candidate_id: string
  expected_blueprint_revision: number | null
}

export interface UpdateBookBlueprintInput {
  content: BookBlueprintContent
  changed_fields: BookBlueprintField[]
  lock_updates: Partial<Record<BookBlueprintField, boolean>>
  expected_revision: number
}

export interface DirectorRegenerationImpact {
  target_field: BookBlueprintField
  directly_affected: BookBlueprintField[]
  downstream_affected: BookBlueprintField[]
  locked_conflicts: BookBlueprintField[]
  will_mark_plan_stale: boolean
}

export interface DirectorFieldRegenerationRequest {
  target_field: BookBlueprintField
  expected_revision: number
  author_intent: string
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
}

export interface DirectorFieldProposal {
  job_id: string
  project_id: string
  blueprint_revision: number
  target_field: BookBlueprintField
  value: string | string[]
  rationale: string
  downstream_affected: BookBlueprintField[]
}

export interface ApplyDirectorProposalInput {
  job_id: string
  expected_revision: number
}

export interface DirectorSceneBeat {
  ordinal: number
  summary: string
  state_change: string
  resource_change: string
  emotional_turn: string
  verification: string
}

export interface VolumePlanContent {
  volume_number: number
  title: string
  direction: string
  central_conflict: string
  state_goal: string
  resource_goal: string
  emotional_payoff: string
  climax: string
  verification: string
}

export interface VolumePlan extends VolumePlanContent {
  id: string
  project_id: string
  revision: number
  locked: boolean
  created_at: string
  updated_at: string
}

export interface RollingChapterPlanContent {
  chapter_number: number
  title: string
  reader_promise: string
  opening_hook: string
  state_change: string
  resource_change: string
  emotional_payoff: string
  ending_cliffhanger: string
  verification: string
  scene_beats: DirectorSceneBeat[]
}

export interface RollingChapterPlan extends RollingChapterPlanContent {
  id: string
  project_id: string
  volume_plan_id: string
  revision: number
  locked: boolean
  created_at: string
  updated_at: string
}

export interface DirectorPlanningSnapshot {
  book_blueprint: BookBlueprint | null
  volume_plans: VolumePlan[]
  rolling_chapter_plans: RollingChapterPlan[]
}

export interface DirectorEntityProposal {
  kind: StoryEntityKind
  name: string
  role: string
  goal: string
  initial_state: string
  relationship_notes: string
}

export interface DirectorExpansionProposal {
  job_id: string
  project_id: string
  blueprint_revision: number
  entities: DirectorEntityProposal[]
  volumes: VolumePlanContent[]
  chapters: RollingChapterPlanContent[]
  why_writeable: string
  risk_notes: string[]
}

export interface DirectorExpansionRequest {
  expected_revision: number
  author_intent: string
  chapter_count: number
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
}

export interface UpdateVolumePlanInput {
  content: VolumePlanContent
  locked: boolean
  expected_revision: number
}

export interface UpdateRollingChapterPlanInput {
  content: RollingChapterPlanContent
  locked: boolean
  expected_revision: number
}

export interface DirectorOutboundPreview {
  workflow: DirectorWorkflow
  profile_id: string | null
  profile_name: string
  provider: string
  model: string
  data_types: string[]
  content_scope: string
  character_count: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_calls: number
  estimated_cost_microusd: number | null
}

export interface DirectorPreReviewFinding {
  severity: 'warning' | 'info'
  field: string
  message: string
}

export interface DirectorPreReview {
  passed: boolean
  findings: DirectorPreReviewFinding[]
}

export interface DirectorChapterPipelineRequest {
  expected_revision: number
  author_intent: string
  context_token_budget: number
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
  rerun_from: DirectorPipelineStage
  parent_job_id: string | null
}

export interface CreateRecoveryPointInput {
  label: string
}

export interface RecoveryPointSummary {
  id: string
  project_id: string
  label: string
  kind: 'manual'
  archive_sha256: string
  uncompressed_bytes: number
  compressed_bytes: number
  created_at: string
}

export interface Chapter {
  id: string
  project_id: string
  volume_id?: string | null
  volume_number: number
  chapter_number: number
  sort_key?: number
  title: string
  content: string
  reader_promise: string
  opening_hook: string
  state_change: string
  emotional_payoff: string
  ending_cliffhanger: string
  status: ChapterStatus
  revision: number
  updated_at: string
}

export interface ManuscriptVolume {
  id: string
  project_id: string
  volume_number: number
  title: string
  sort_key: number
  revision: number
  created_at: string
  updated_at: string
}

export interface ManuscriptScene {
  id: string
  project_id: string
  chapter_id: string
  title: string
  summary: string
  sort_key: number
  revision: number
  created_at: string
  updated_at: string
}

export interface ManuscriptImportChapter {
  client_id: string
  title: string
  content: string
  heading_confidence: number
  warnings: string[]
}

export interface ManuscriptImportVolume {
  client_id: string
  title: string
  chapters: ManuscriptImportChapter[]
}

export interface ManuscriptImportPreview {
  source_filename: string
  source_format: 'txt' | 'markdown' | 'docx' | 'epub'
  source_sha256: string
  source_encoding: string
  encoding_confidence: number
  inferred_project_title: string
  volumes: ManuscriptImportVolume[]
  unrecognized_text: string
  warnings: string[]
  total_characters: number
  chapter_count: number
}

export interface ConfirmManuscriptImportInput {
  title: string
  genre: Genre
  rebirth_year: number
  rebirth_location: string
  chapter_target_words: number
  safety_buffer_chapters: number
  source_filename: string
  source_sha256: string
  source_encoding: string
  warnings: string[]
  volumes: ManuscriptImportVolume[]
  unrecognized_text: string
  unrecognized_action: 'prepend_first_chapter' | 'omit' | null
  confirm_warnings: boolean
}

export interface ManuscriptExport {
  filename: string
  content: string
  content_sha256: string
  volume_count: number
  chapter_count: number
}

export type DirectoryNodeKind = 'volume' | 'chapter' | 'scene'

export interface CreateDirectoryNodeInput {
  kind: DirectoryNodeKind
  title: string
  parent_id?: string | null
  summary?: string
}

export interface RenameDirectoryNodeInput {
  title: string
  summary?: string | null
  expected_revision: number
}

export interface MoveDirectoryNodeInput {
  parent_id?: string | null
  before_id?: string | null
  expected_revision: number
}

export interface DeleteDirectoryNodeInput {
  expected_revision: number
  confirm_impact: boolean
}

export interface DirectoryDeleteImpact {
  node_kind: DirectoryNodeKind
  node_id: string
  title: string
  descendant_chapters: number
  descendant_scenes: number
  references: Record<string, number>
  can_delete: boolean
  reason: string | null
}

export interface DirectoryEvent {
  id: string
  project_id: string
  action: 'create' | 'rename' | 'move' | 'delete'
  node_kind: DirectoryNodeKind
  node_id: string
  undone_at: string | null
  created_at: string
}

export interface SerialDailyGoal {
  project_id: string
  goal_date: string
  target_characters: number
  actual_characters: number
  revision: number
  updated_at: string
}

export interface SerialDashboard {
  project_id: string
  goal: SerialDailyGoal
  total_characters: number
  chapter_count: number
  planned_chapters: number
  drafted_chapters: number
  reviewing_chapters: number
  approved_chapters: number
  stockpile_chapters: number
  pending_review_chapters: number
  ready_to_publish_chapters: number
}

export interface WorkspaceSearchResult {
  kind: 'project' | 'chapter' | 'character' | 'resource' | 'thread' | 'idea' | 'annotation'
  id: string
  title: string
  snippet: string
  chapter_id: string | null
}

export type ChapterSummary = Omit<Chapter, 'content'> & {
  has_content: boolean
  content_characters: number
}

export interface ChapterVersion {
  id: string
  chapter_id: string
  version_number: number
  chapter_revision: number
  content: string
  content_sha256: string
  source: ChapterVersionSource
  source_id: string | null
  parent_version_id: string | null
  is_candidate: boolean
  created_at: string
}

export interface RollbackChapterVersionInput {
  expected_revision: number
}

export interface TimelineEvent {
  id: string
  project_id: string
  layer: TimelineLayer
  event_year: number
  title: string
  summary: string
  source_chapter_id: string | null
  created_at: string
}

export interface StoryFact {
  id: string
  project_id: string
  source_chapter_id: string
  kind: FactKind
  content: string
  created_at: string
}

export interface FactChange {
  id: string
  change_set_id: string
  kind: FactKind
  content: string
  event_year: number | null
}

export interface FactChangeSet {
  id: string
  chapter_id: string
  chapter_revision: number
  state: FactChangeSetState
  revision: number
  changes: FactChange[]
  created_at: string
  updated_at: string
}

export interface FutureKnowledge {
  id: string
  project_id: string
  future_year: number
  content: string
  source_note: string
  confidence: KnowledgeConfidence
  status: KnowledgeStatus
  divergence_event_id: string | null
  revision: number
  created_at: string
  updated_at: string
}

export interface StoryEntity {
  id: string
  project_id: string
  kind: StoryEntityKind
  name: string
  role: string
  goal: string
  current_state: string
  relationship_notes: string
  revision: number
  created_at: string
  updated_at: string
}

export interface StoryThread {
  id: string
  project_id: string
  source_chapter_id: string | null
  title: string
  summary: string
  status: StoryThreadStatus
  planted_chapter_number: number | null
  resolved_chapter_id: string | null
  revision: number
  created_at: string
  updated_at: string
}

export interface SourceCard {
  id: string
  project_id: string
  source_kind: SourceKind
  title: string
  source_reference: string
  applicable_year_start: number
  applicable_year_end: number
  confidence: SourceConfidence
  excerpt: string
  source_document_id: string | null
  source_date: string | null
  page_number_start: number | null
  page_number_end: number | null
  start_char: number | null
  end_char: number | null
  confirmed: boolean
  revision: number
  created_at: string
  updated_at: string
}

export interface SourceDocument {
  id: string
  title: string
  source_filename: string
  source_format: ReferenceFormat
  source_sha256: string
  content_sha256: string
  source_encoding: string
  encoding_confidence: number
  import_state: 'ready' | 'needs_review'
  duplicate_of_id: string | null
  source_spans: ReferenceSourceSpan[]
  total_characters: number
  created_at: string
  updated_at: string
}

export interface ReferenceSegment {
  id: string
  reference_work_id: string
  ordinal: number
  start_char: number
  end_char: number
  character_count: number
  chapter_start: string | null
  chapter_end: string | null
  created_at: string
}

export interface ReferenceSourceSpan {
  page_number: number
  start_char: number
  end_char: number
}

export interface ReferenceWork {
  id: string
  project_id: string | null
  project_ids: string[]
  title: string
  source_filename: string
  source_format: ReferenceFormat
  rights_basis: ReferenceRightsBasis
  total_characters: number
  segment_target_characters: number
  content_sha256: string
  source_sha256: string
  source_encoding: string
  encoding_confidence: number
  import_state: 'ready' | 'needs_review'
  duplicate_of_id: string | null
  source_spans: ReferenceSourceSpan[]
  segments: ReferenceSegment[]
  created_at: string
  updated_at: string
}

export interface ReferenceFilePreview {
  source_filename: string
  source_format: ReferenceFormat
  source_encoding: string
  encoding_confidence: number
  import_state: 'ready' | 'needs_review'
  source_sha256: string
  content_sha256: string
  total_characters: number
  page_count: number
  preview: string
  warnings: string[]
  source_spans: ReferenceSourceSpan[]
}

export interface ReferenceWorkImpact {
  work: ReferenceWork
  projects: Project[]
  cache_entries: number
  retained_craft_asset_count?: number
  affected_craft_job_count?: number
}

export interface ContinuityIssue {
  id: string
  kind: ContinuityIssueKind
  severity: ContinuitySeverity
  title: string
  detail: string
  source_labels: string[]
}

export interface ReviewEvidence {
  kind: ReviewEvidenceKind
  chapter_id: string | null
  start_char: number | null
  end_char: number | null
  excerpt: string | null
  source_type: string | null
  source_id: string | null
  label: string
}

export interface ReviewFinding {
  id: string
  project_id: string
  chapter_id: string
  chapter_revision: number
  review_job_id: string | null
  dimension: ReviewDimension
  severity: ReviewSeverity
  code: string
  title: string
  evidence: ReviewEvidence[]
  explanation: string
  suggestion: string
  suggested_replacement: string | null
  confidence: number
  dedupe_key: string
  state: ReviewFindingState
  created_at: string
}

export interface ReviewDimensionOutcome {
  dimension: ReviewDimension
  state: ReviewDimensionState
  finding_count: number
  error_code: string | null
  error_message: string | null
}

export interface ReviewJobResult {
  job_id: string
  project_id: string
  chapter_id: string
  chapter_revision: number
  window_size: number
  outcomes: ReviewDimensionOutcome[]
  findings: ReviewFinding[]
}

export interface ReviewOutboundPreview {
  profile_id: string | null
  profile_name: string
  provider: string
  model: string
  dimensions: ReviewDimension[]
  local_dimensions: ReviewDimension[]
  external_dimensions: ReviewDimension[]
  data_types: string[]
  content_scope: string
  character_count: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_calls: number
  estimated_cost_microusd: number | null
  context_sha256: string
}

export interface ReviewChapterInput {
  expected_revision: number
  window_size: number
  dimensions: ReviewDimension[]
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
  parent_job_id?: string | null
}

export interface TextChange {
  id: string
  change_set_id: string
  ordinal: number
  start_char: number
  end_char: number
  original_text: string
  replacement_text: string
  rationale: string
  review_finding_id: string | null
  selected: boolean | null
  applied_replacement: string | null
}

export interface TextChangeSet {
  id: string
  chapter_id: string
  base_chapter_revision: number
  base_content_sha256: string
  title: string
  state: TextChangeSetState
  revision: number
  changes: TextChange[]
  created_at: string
  updated_at: string
}

export interface CreateTextChangeSetInput {
  finding_ids: string[]
}

export interface ApplyTextChangeSetInput {
  selected_change_ids: string[]
  edited_replacements: Record<string, string>
  expected_set_revision: number
  expected_chapter_revision: number
}

export interface RejectTextChangeSetInput {
  expected_revision: number
}

export interface ResumeCardItem {
  label: string
  detail: string
  source: string
}

export interface ResumeCard {
  chapter_id: string
  chapter_number: number
  chapter_title: string
  chapter_status: ChapterStatus
  last_progress: string
  next_entry: string
  open_threads: ResumeCardItem[]
  active_entities: ResumeCardItem[]
  pending_reviews: number
  warning_count: number
}

export interface AiStatus {
  configured: boolean
  provider: AiProvider
  model: string
  key_source: string | null
  profile_id: string | null
  profile_name: string | null
}

export interface ConfigureAiInput {
  api_key: string
  model: string
}

export type ProviderKind = 'openai' | 'openai_compatible'

export type AiTaskType =
  | 'chapter_brief'
  | 'chapter_draft'
  | 'reference_analysis'
  | 'review'
  | 'sandbox'
  | 'research'
  | 'comic_season_plan'
  | 'comic_episode_script'
  | 'pattern_adaptation'

export type ResearchCategory = 'historical_event' | 'local_system' | 'industry_rule' | 'price_technology' | 'controversy'
export type ResearchMode = 'local' | 'ai'

export interface ResearchInput {
  title: string
  question: string
  era_start: number
  era_end: number
  region: string
  material_type: string
  mode: ResearchMode
  source_document_ids: string[]
  pasted_text: string
  pasted_label: string
}

export interface ResearchPreview {
  source_set_sha256: string
  sources: Array<{ source_document_id: string | null; label: string; source_format: string; character_count: number; content_sha256: string }>
  character_count: number
  estimated_calls: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_microusd: number | null
  profile_id: string | null
  profile_name: string
  provider: string
  model: string
  requires_external_confirmation: boolean
  data_types: string[]
  content_scope: string
}

export interface ResearchSession {
  id: string
  project_id: string
  title: string
  question: string
  era_start: number
  era_end: number
  region: string
  material_type: string
  mode: ResearchMode
  state: 'queued' | 'running' | 'ready' | 'failed' | 'cancelled'
  source_set_sha256: string
  job_id: string | null
  invalid_ai_findings: number
  finding_count: number
  candidate_count: number
  created_at: string
  updated_at: string
}

export interface ResearchFinding {
  id: string
  session_id: string
  research_source_id: string
  source_document_id: string | null
  source_label: string
  category: ResearchCategory
  title: string
  summary: string
  evidence_excerpt: string
  evidence_sha256: string
  start_char: number
  end_char: number
  page_number_start: number | null
  page_number_end: number | null
  applicable_year_start: number
  applicable_year_end: number
  region: string
  confidence: SourceConfidence
  conflict_key: string
  conflict_count: number
  origin: 'local' | 'ai'
  state: 'candidate' | 'approved' | 'rejected'
  source_card_id: string | null
  revision: number
  created_at: string
  updated_at: string
}

export interface ResearchWorkspace {
  session: ResearchSession
  sources: ResearchPreview['sources']
  findings: ResearchFinding[]
}

export interface ResearchSubmission { session: ResearchSession; job: Job }

export interface WritingCalendarDay { date: string; net_characters: number; target_characters: number; met_goal: boolean }
export interface WritingCalendar { project_id: string; timezone: string; days: WritingCalendarDay[]; total_net_characters: number; streak_days: number }
export interface ChapterAnnotation {
  id: string; project_id: string; chapter_id: string; chapter_revision: number; content_sha256: string
  start_char: number; end_char: number; selected_text: string; context_before: string; context_after: string
  comment: string; status: 'open' | 'resolved' | 'stale'; revision: number; created_at: string; updated_at: string
}
export interface AuthorIdea {
  id: string; project_id: string | null; title: string; content: string; tags: string[]
  status: 'inbox' | 'planned' | 'applied' | 'archived'; target_kind: 'chapter_brief' | 'source_card' | 'character' | null
  target_id: string | null; revision: number; created_at: string; updated_at: string
}
export interface StoryGraphNode { id: string; label: string; kind: 'character' | 'resource' | 'thread' | 'chapter'; status: string }
export interface StoryGraphEdge { id: string; source: string; target: string; label: string; status: string; chapter_id: string | null }
export interface StoryGraphs { relationship_nodes: StoryGraphNode[]; relationship_edges: StoryGraphEdge[]; thread_nodes: StoryGraphNode[]; thread_edges: StoryGraphEdge[] }
export interface StoryRelationship { id: string; project_id: string; source_entity_id: string; target_entity_id: string; relation_type: string; summary: string; status: 'active' | 'historical'; source_chapter_id: string | null; revision: number; created_at: string; updated_at: string }

export interface ModelCapabilities {
  structured_output: boolean
  streaming: boolean
  server_cancellation: boolean
  usage: boolean
}

export interface ModelProfile {
  id: string
  name: string
  provider: ProviderKind
  base_url: string
  model: string
  capabilities: ModelCapabilities
  input_cost_microusd_per_million: number | null
  output_cost_microusd_per_million: number | null
  revision: number
  created_at: string
  updated_at: string
}

export interface CreateModelProfileInput {
  name: string
  provider: ProviderKind
  base_url: string
  model: string
  input_cost_microusd_per_million: number | null
  output_cost_microusd_per_million: number | null
}

export interface UpdateModelProfileInput extends CreateModelProfileInput {
  expected_revision: number
}

export interface AiTaskDefault {
  task_type: AiTaskType
  profile_id: string
  profile_name: string
  provider: ProviderKind
  model: string
  revision: number
  updated_at: string
}

export interface UpdateAiTaskDefaultInput {
  profile_id: string
  expected_revision: number | null
}

export type ContextTaskType = 'chapter_brief' | 'chapter_draft'

export type ContextTier =
  | 'hard_constraint'
  | 'canon'
  | 'current_state'
  | 'recent_chapter'
  | 'distant_chapter'
  | 'timeline'
  | 'reality_source'
  | 'blueprint'

export type ContextDirectiveAction = 'pin' | 'exclude'

export interface ContextSourceRef {
  kind: string
  source_id: string
  label: string
  chapter_id: string | null
  chapter_number: number | null
  character_start: number | null
  character_end: number | null
  updated_at: string | null
}

export interface ContextItem {
  id: string
  kind:
    | 'security_boundary'
    | 'author_intent'
    | 'project_anchor'
    | 'current_chapter'
    | 'canonical_fact'
    | 'story_entity'
    | 'story_thread'
    | 'recent_chapter_excerpt'
    | 'distant_chapter_summary'
    | 'timeline_event'
    | 'future_knowledge'
    | 'reality_source'
    | 'approved_blueprint'
    | 'book_blueprint'
    | 'rolling_chapter_plan'
  tier: ContextTier
  label: string
  content: string
  token_estimate: number
  priority: number
  required: boolean
  included: boolean
  directive: ContextDirectiveAction | null
  selection_reason: string
  exclusion_reason: string | null
  source_refs: ContextSourceRef[]
  conflict_notes: string[]
  content_sha256: string
}

export interface ContextTierUsage {
  tier: ContextTier
  budget_tokens: number
  used_tokens: number
  included_count: number
  excluded_count: number
}

export interface ContextPacket {
  id: string
  project_id: string
  chapter_id: string
  chapter_revision: number
  task_type: ContextTaskType
  compiler_version: string
  token_budget: number
  used_tokens: number
  overflow_tokens: number
  packet_sha256: string
  source_fingerprint_sha256: string
  rendered_context: string
  items: ContextItem[]
  tier_usage: ContextTierUsage[]
  conflict_notes: string[]
  created_at: string
}

export interface ContextDirective {
  id: string
  project_id: string
  chapter_id: string
  source_kind: string
  source_id: string
  action: ContextDirectiveAction
  revision: number
  created_at: string
  updated_at: string
}

export interface ContextDirectiveInput {
  source_kind: string
  source_id: string
  action: ContextDirectiveAction
  expected_revision: number | null
}

export interface AiOutboundPreview {
  task_type: AiTaskType
  profile_id: string | null
  profile_name: string
  provider: ProviderKind
  model: string
  data_types: string[]
  content_scope: string
  character_count: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_microusd: number | null
  context_packet: ContextPacket
}

export interface AiChapterBriefInput {
  expected_revision: number
  author_intent: string
  context_packet_id?: string | null
  context_token_budget?: number
}

export interface AiChapterBriefProposal {
  title: string
  reader_promise: string
  opening_hook: string
  state_change: string
  emotional_payoff: string
  ending_cliffhanger: string
  why_this_works: string
  risk_notes: string[]
}

export interface Workspace {
  project: Project
  chapters: Chapter[]
  topic_decision: TopicDecision | null
  next_action: ProjectNextAction
  manuscript_volumes?: ManuscriptVolume[]
  manuscript_scenes?: ManuscriptScene[]
  book_blueprint: BookBlueprint | null
  volume_plans: VolumePlan[]
  rolling_chapter_plans: RollingChapterPlan[]
  timeline_events: TimelineEvent[]
  story_facts: StoryFact[]
  fact_change_sets: FactChangeSet[]
  future_knowledge: FutureKnowledge[]
  story_entities: StoryEntity[]
  story_threads: StoryThread[]
  source_cards: SourceCard[]
  reference_works: ReferenceWork[]
  reference_pattern_cards: ReferencePatternCard[]
  reference_pattern_applications: ReferencePatternApplication[]
  continuity_issues: ContinuityIssue[]
  resume_card: ResumeCard | null
}

export type WorkspaceSummary = Omit<Workspace, 'chapters'> & {
  chapters: ChapterSummary[]
}

export interface CreateTimelineEventInput {
  event_year: number
  title: string
  summary?: string
}

export interface ApplyFactChangeSetInput {
  selected_change_ids: string[]
  expected_revision: number
}

export interface CreateFutureKnowledgeInput {
  future_year: number
  content: string
  source_note?: string
  confidence: KnowledgeConfidence
}

export interface StoryEntityFields {
  name: string
  role: string
  goal: string
  current_state: string
  relationship_notes: string
}

export interface CreateStoryEntityInput extends StoryEntityFields {
  kind: StoryEntityKind
}

export interface UpdateStoryEntityInput extends StoryEntityFields {
  expected_revision: number
}

export interface CreateStoryThreadInput {
  title: string
  summary?: string
  planted_chapter_number?: number
}

export interface TransitionStoryThreadInput {
  target_status: StoryThreadStatus
  resolved_chapter_id?: string
  expected_revision: number
}

export interface CreateSourceCardInput {
  source_kind: SourceKind
  title: string
  source_reference: string
  applicable_year_start: number
  applicable_year_end: number
  confidence: SourceConfidence
  excerpt?: string
}

export interface ImportReferenceWorkInput {
  title: string
  source_filename: string
  rights_basis: ReferenceRightsBasis
  segment_target_characters: number
  content: string
}

export interface ImportReferenceFileInput {
  title: string
  rights_basis: ReferenceRightsBasis
  segment_target_characters: number
  expected_source_sha256: string
  confirm_preview: boolean
  confirm_uncertain_encoding: boolean
  project_id?: string
}

export interface ImportRealitySourceFileInput {
  project_id: string
  title: string
  source_kind: SourceKind
  source_reference: string
  applicable_year_start: number
  applicable_year_end: number
  confidence: SourceConfidence
  source_date?: string
  expected_source_sha256: string
  confirm_preview: boolean
  confirm_uncertain_encoding: boolean
}

export interface ReferenceSynthesisInput {
  selected_segment_ids: string[]
  author_focus: string
  confirm_external_processing: boolean
}

export interface CraftPatternAnalysisPreviewInput {
  selected_segment_ids: string[]
  author_focus: string
}

export interface CraftPatternAnalysisJobInput extends CraftPatternAnalysisPreviewInput {
  confirm_external_processing: boolean
  confirm_unknown_cost: boolean
  max_estimated_cost_microusd: number | null
  expected_preflight_sha256: string
}

export interface CraftPatternFusionPreviewInput {
  selected_asset_version_ids: string[]
  author_focus: string
}

export interface CraftPatternFusionJobInput extends CraftPatternFusionPreviewInput {
  confirm_external_processing: boolean
  confirm_unknown_cost: boolean
  max_estimated_cost_microusd: number | null
  expected_preflight_sha256: string
}

export interface CraftPatternPreviewWork {
  work_id: string
  title: string
  segment_count: number
  character_count: number
}

export interface CraftPatternPreviewSegment {
  segment_id: string
  work_id: string
  work_title: string
  ordinal: number
  start_char: number
  end_char: number
  chapter_start: string | null
  chapter_end: string | null
  character_count: number
}

export interface CraftPatternPreviewAsset {
  asset_version_id: string
  content_sha256: string
  title: string
  asset_type: CraftPatternAssetType
  version: number
  source_work_ids: string[]
}

export interface CraftPatternPreflight {
  operation: 'analysis' | 'fusion'
  selected_works: CraftPatternPreviewWork[]
  selected_segments: CraftPatternPreviewSegment[]
  selected_assets: CraftPatternPreviewAsset[]
  selected_character_count: number
  stage_card_count: number
  book_evolution_count: number
  fusion_material_count: number
  map_calls: number
  stage_calls: number
  book_calls: number
  fusion_calls: number
  planned_calls: number
  cache_hit_calls: number
  uncached_calls: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_microusd: number | null
  profile_id: string | null
  profile_name: string | null
  provider: AiProvider
  model: string
  data_types: string[]
  content_scope: string
  prompt_version: string
  preflight_sha256: string
}

export interface CraftPatternEvidence {
  id: string
  work_id: string
  work_title: string
  segment_id: string
  stage_label: string
  chapter_label: string | null
  absolute_start_char: number
  absolute_end_char: number
  evidence_summary: string
  evidence_sha256: string
  confidence: number
}

export interface CraftPatternItem {
  dimension: CraftPatternDimension
  name: string
  observation: string
  transferable_rule: string
  adaptation_risk: string
  evidence: CraftPatternEvidence[]
}

export interface CraftPatternAssetSummary {
  id: string
  series_id: string
  asset_type: CraftPatternAssetType
  version: number
  content_sha256: string
  lifecycle_state: CraftPatternLifecycleState | null
  lifecycle_revision: number | null
  source_work_ids: string[]
  source_segment_ids: string[]
  source_asset_version_ids: string[]
  title: string
  summary: string
  provider: AiProvider
  model: string
  prompt_version: string
  created_at: string
  updated_at: string
}

export interface CraftPatternAsset extends CraftPatternAssetSummary {
  schema_version: 2
  source_job_id: string | null
  author_focus: string
  craft_items: CraftPatternItem[]
}

export interface CraftPatternAssetPage {
  items: CraftPatternAssetSummary[]
  total: number
  limit: number
  offset: number
}

export interface UpdateCraftPatternLifecycleInput {
  state: CraftPatternLifecycleState
  expected_lifecycle_revision: number
}

export type WritingPatternPurpose = 'learn' | 'counterexample'

export type WritingPatternStrategy = 'preserve_function' | 'transform' | 'avoid'

export type WritingPatternStage =
  | 'startup'
  | 'volume'
  | 'rolling'
  | 'chapter_brief'
  | 'chapter_draft'
  | 'rewrite'
  | 'review'

export type WritingPatternSafetyBasis = 'source_verified' | 'abstract_only'

export type WritingPatternLifecycleState = 'active' | 'archived'

export type WritingPatternConflictResolution =
  | 'choose_source'
  | 'combine_as_transform'
  | 'exclude_all'

export interface WritingPatternRecipeEntryInput {
  asset_version_id: string
  asset_content_sha256: string
  dimension: CraftPatternDimension
  pattern_name: string
  purpose: WritingPatternPurpose
  strategy: WritingPatternStrategy
  weight: number
  applicable_stages: WritingPatternStage[]
  chapter_start: number | null
  chapter_end: number | null
  note: string
}

export interface WritingPatternConflictDecisionInput {
  conflict_key: string
  resolution: WritingPatternConflictResolution
  chosen_entry_key: string | null
}

export interface WritingPatternWorkFingerprint {
  basis: 'content_sha256' | 'abstract_lineage'
  identity_sha256: string
}

export interface WritingPatternRecipeSource {
  entry_key: string
  asset_version_id: string
  asset_series_id: string
  asset_version: number
  asset_content_sha256: string
  asset_type: CraftPatternAssetType
  dimension: CraftPatternDimension
  pattern_name: string
  transferable_rule: string
  adaptation_risk: string
  purpose: WritingPatternPurpose
  strategy: WritingPatternStrategy
  weight: number
  applicable_stages: WritingPatternStage[]
  chapter_start: number | null
  chapter_end: number | null
  note: string
  source_work_fingerprints: WritingPatternWorkFingerprint[]
  source_snapshot_sha256: string
}

export interface WritingPatternConflict {
  conflict_key: string
  dimension: CraftPatternDimension
  applicable_stage: WritingPatternStage
  entry_keys: string[]
  reason: 'preserve_vs_avoid' | 'competing_preserve_rules'
}

export interface AppliedWritingPatternConflictDecision extends WritingPatternConflictDecisionInput {
  affected_entry_keys: string[]
}

export interface ModelSafeWritingPatternRule {
  source_content_sha256: string
  dimension: CraftPatternDimension
  name: string
  transferable_rule: string
  adaptation_risk: string
  purpose: WritingPatternPurpose
  strategy: WritingPatternStrategy
  weight_basis_points: number
  applicable_stages: WritingPatternStage[]
  chapter_start: number | null
  chapter_end: number | null
}

export interface ModelSafeWritingPatternProfile {
  schema_version: 1
  compiler_version: string
  topic_revision: number
  topic_content_sha256: string
  recipe_content_sha256: string
  safety_basis: WritingPatternSafetyBasis
  rules: ModelSafeWritingPatternRule[]
}

export interface PreviewWritingPatternRecipeInput {
  name: string
  description: string
  expected_topic_revision: number
  entries: WritingPatternRecipeEntryInput[]
  conflict_decisions: WritingPatternConflictDecisionInput[]
}

export interface CreateWritingPatternRecipeInput extends PreviewWritingPatternRecipeInput {
  expected_preview_sha256: string
}

export interface PreviewWritingPatternRecipeVersionInput extends PreviewWritingPatternRecipeInput {
  expected_latest_version: number
}

export interface CreateWritingPatternRecipeVersionInput extends PreviewWritingPatternRecipeVersionInput {
  expected_preview_sha256: string
}

export interface WritingPatternRecipePreview {
  name: string
  description: string
  expected_topic_revision: number
  expected_latest_version: number | null
  sources: WritingPatternRecipeSource[]
  conflicts: WritingPatternConflict[]
  decisions: WritingPatternConflictDecisionInput[]
  unresolved_conflict_count: number
  source_asset_count: number
  source_work_count: number
  safety_basis: WritingPatternSafetyBasis
  source_snapshot_sha256: string
  recipe_content_sha256: string
  preview_sha256: string
}

export interface WritingPatternRecipeVersionSummary {
  id: string
  recipe_id: string
  version: number
  name: string
  description: string
  source_asset_count: number
  source_work_count: number
  safety_basis: WritingPatternSafetyBasis
  source_snapshot_sha256: string
  content_sha256: string
  created_at: string
}

export interface WritingPatternRecipeVersion extends WritingPatternRecipeVersionSummary {
  sources: WritingPatternRecipeSource[]
  conflicts: WritingPatternConflict[]
  conflict_decisions: WritingPatternConflictDecisionInput[]
}

export interface WritingPatternRecipeSummary {
  id: string
  lifecycle_state: WritingPatternLifecycleState
  lifecycle_revision: number
  latest_version: WritingPatternRecipeVersionSummary
  created_at: string
  updated_at: string
}

export interface WritingPatternRecipePage {
  items: WritingPatternRecipeSummary[]
  total: number
  limit: number
  offset: number
}

export interface WritingPatternRecipeSeries {
  id: string
  lifecycle_state: WritingPatternLifecycleState
  lifecycle_revision: number
  versions: WritingPatternRecipeVersionSummary[]
  created_at: string
  updated_at: string
}

export interface PreviewWritingPatternReuseInput {
  expected_recipe_content_sha256: string
  expected_topic_revision: number
}

export interface ReuseWritingPatternRecipeInput extends PreviewWritingPatternReuseInput {
  expected_preview_sha256: string
}

export interface WritingPatternProfilePreview {
  recipe_version_id: string
  recipe_content_sha256: string
  topic_decision_version_id: string
  topic_revision: number
  topic_content_sha256: string
  safety_basis: WritingPatternSafetyBasis
  model_safe_profile: ModelSafeWritingPatternProfile
  conflicts: WritingPatternConflict[]
  decisions: AppliedWritingPatternConflictDecision[]
  excluded_entry_keys: string[]
  source_snapshot_sha256: string
  profile_fingerprint_sha256: string
  preview_sha256: string
}

export interface WritingPatternProfileSummary {
  id: string
  project_id: string
  recipe_version_id: string
  recipe_content_sha256: string
  topic_revision: number
  topic_content_sha256: string
  safety_basis: WritingPatternSafetyBasis
  profile_fingerprint_sha256: string
  lifecycle_state: WritingPatternLifecycleState
  lifecycle_revision: number
  is_current: boolean
  created_at: string
  updated_at: string
}

export interface WritingPatternProfileVersion extends WritingPatternProfileSummary {
  topic_decision_version_id: string
  compiler_version: string
  source_snapshot_sha256: string
  model_safe_profile: ModelSafeWritingPatternProfile
  conflicts: WritingPatternConflict[]
  decisions: AppliedWritingPatternConflictDecision[]
  excluded_entry_keys: string[]
}

export interface UpdateWritingPatternLifecycleInput {
  state: WritingPatternLifecycleState
  expected_lifecycle_revision: number
}

export type PatternDistinctAxis =
  | 'core_conflict'
  | 'character_relationships'
  | 'resource_progression'
  | 'scene_organization'
  | 'ending'

export type PatternAdaptationResultState = 'pending' | 'available' | 'stale' | 'invalid'

export type PatternAdaptationCostStatus = 'free' | 'known' | 'unavailable'

export type PatternAdaptationCandidateSource = 'model' | 'author_edit'

export interface PatternAdaptationPreflightInput {
  profile_version_id: string
  expected_profile_fingerprint_sha256: string
  expected_topic_revision: number
  expected_topic_content_sha256: string
  expected_base_blueprint_revision: number | null
  expected_base_blueprint_content_sha256: string | null
  author_intent: string
  provider_profile_id: string | null
}

export interface SubmitPatternAdaptationInput extends PatternAdaptationPreflightInput {
  expected_preview_sha256: string
  confirm_external_processing: boolean
  max_estimated_cost_microusd: number | null
}

export interface PatternAdaptationPreflight {
  profile_version_id: string
  profile_fingerprint_sha256: string
  recipe_version_id: string
  recipe_content_sha256: string
  source_availability: WritingPatternSafetyBasis
  topic_decision_version_id: string
  topic_revision: number
  topic_content_sha256: string
  base_blueprint_id: string | null
  base_blueprint_revision: number | null
  base_blueprint_content_sha256: string | null
  dependency_fingerprint_sha256: string
  safe_context_sha256: string
  lock_snapshot_sha256: string
  provider: string
  provider_profile_id: string | null
  provider_profile_name: string
  provider_profile_revision: number | null
  model: string
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_calls: 1
  estimated_cost_microusd: number | null
  cost_status: PatternAdaptationCostStatus
  data_types: string[]
  content_scope: string
  locked_fields: BookBlueprintField[]
  relationship_mode: 'rebuild_by_default'
  preview_sha256: string
}

export interface PatternAdaptationCandidateVersion {
  id: string
  candidate_id: string
  revision: number
  blueprint: BookBlueprintContent
  key_scene_sequence: string[]
  transformation_notes: string[]
  content_sha256: string
  changed_fields: BookBlueprintField[]
  source: PatternAdaptationCandidateSource
  created_at: string
}

export interface PatternAdaptationCandidate {
  id: string
  proposal_id: string
  ordinal: number
  label: string
  why_distinct: string
  distinct_axes: PatternDistinctAxis[]
  risk_hypotheses: string[]
  current_version: PatternAdaptationCandidateVersion
  created_at: string
  updated_at: string
}

export interface PatternAdaptationProposal {
  id: string
  job_id: string
  project_id: string
  profile_version_id: string
  profile_fingerprint_sha256: string
  recipe_version_id: string
  recipe_content_sha256: string
  topic_decision_version_id: string
  topic_revision: number
  topic_content_sha256: string
  base_blueprint_id: string | null
  base_blueprint_revision: number | null
  base_blueprint_content_sha256: string | null
  dependency_fingerprint_sha256: string
  safe_context_sha256: string
  lock_snapshot_sha256: string
  provider: string
  provider_profile_id: string | null
  provider_profile_revision: number | null
  model: string
  input_cost_microusd_per_million: number | null
  output_cost_microusd_per_million: number | null
  result_state: PatternAdaptationResultState
  stale_reason: string | null
  candidates: PatternAdaptationCandidate[]
  created_at: string
  updated_at: string
}

export interface EditPatternAdaptationCandidateInput {
  blueprint: BookBlueprintContent
  key_scene_sequence: string[]
  transformation_notes: string[]
  changed_fields: BookBlueprintField[]
  expected_revision: number
  expected_content_sha256: string
}

export interface AdoptPatternAdaptationCandidateInput {
  expected_candidate_revision: number
  expected_candidate_content_sha256: string
  expected_profile_fingerprint_sha256: string
  expected_recipe_content_sha256: string
  expected_topic_revision: number
  expected_topic_content_sha256: string
  expected_base_blueprint_revision: number | null
  expected_base_blueprint_content_sha256: string | null
  idempotency_key: string
}

export interface PatternAdaptationAdoption {
  id: string
  project_id: string
  proposal_id: string
  candidate_id: string
  candidate_version_id: string
  blueprint_id: string
  blueprint_revision: number
  blueprint_content_sha256: string
  profile_fingerprint_sha256: string
  recipe_content_sha256: string
  created_at: string
}

export interface AdoptPatternAdaptationResult {
  adoption: PatternAdaptationAdoption
  blueprint: BookBlueprint
  originality_status: 'needs_check'
}

export interface RunPatternOriginalityCheckInput {
  expected_blueprint_revision: number
  expected_blueprint_content_sha256: string
  expected_profile_fingerprint_sha256: string
  expected_recipe_content_sha256: string
}

export interface PatternOriginalityFinding {
  id: string
  ordinal: number
  signal: string
  score: number
  summary: string
  source_fingerprint_sha256: string
  evidence_sha256: string
}

export interface PatternOriginalityReport {
  id: string
  project_id: string
  adoption_id: string
  profile_fingerprint_sha256: string
  recipe_content_sha256: string
  blueprint_id: string
  blueprint_revision: number
  blueprint_content_sha256: string
  candidate_version_id: string
  candidate_content_sha256: string
  risk_level: OriginalityRiskLevel
  status: OriginalityStatus
  score: number
  threshold_version: string
  input_sha256: string
  source_availability: WritingPatternSafetyBasis
  findings: PatternOriginalityFinding[]
  viewed_at: string | null
  acknowledged_at: string | null
  created_at: string
}

export type PatternOriginalityGateStatus =
  | 'legacy'
  | 'needs_adaptation'
  | 'needs_check'
  | 'review_required'
  | 'blocked'
  | 'passed'
  | 'stale'

export interface PatternOriginalityGateState {
  project_id: string
  state: PatternOriginalityGateStatus
  reason: string | null
  requires_check: boolean
  adoption: PatternAdaptationAdoption | null
  blueprint_id: string | null
  blueprint_revision: number | null
  blueprint_content_sha256: string | null
  latest_report: PatternOriginalityReport | null
  report_is_current: boolean
}

export interface ReferenceDimensionSynthesis {
  summary: string
  source_segment_ids: string[]
  transferable_logic: string
  adaptation_risk: string
}

export interface ReferenceSynthesisProposal {
  era: ReferenceDimensionSynthesis
  core_desire: ReferenceDimensionSynthesis
  conflict_causality: ReferenceDimensionSynthesis
  resource_system: ReferenceDimensionSynthesis
  key_scene_sequence: ReferenceDimensionSynthesis
  ending: ReferenceDimensionSynthesis
  shared_patterns: string[]
  differences: string[]
  relationship_recomposition: string
  originality_risks: string[]
}

export interface ReferencePatternCard extends ReferenceSynthesisProposal {
  id: string
  project_id: string
  source_job_id: string | null
  selected_segment_ids: string[]
  author_focus: string
  provider: AiProvider
  model: string
  created_at: string
}

export interface AppliedReferenceDimension {
  summary: string
  transferable_logic: string
}

export interface BlueprintNamedEntity {
  kind: BlueprintEntityKind
  name: string
  function: string
}

export interface BlueprintRelationship {
  left_role: string
  right_role: string
  relation: string
  notes: string
}

export interface BlueprintDimensionState {
  source: ReferenceDimensionSynthesis
  mode: BlueprintMode
  author_edits: string
  generated_variant: AppliedReferenceDimension
  version: number
  locked: boolean
  named_entities: BlueprintNamedEntity[]
  source_beats: string[]
  key_beats: string[]
}

export interface BlueprintRelationshipState {
  source: string
  mode: BlueprintMode
  author_edits: string
  generated_variant: string
  version: number
  locked: boolean
  relationships: BlueprintRelationship[]
}

export interface ReferenceBlueprintState {
  dimensions: Partial<Record<ReferencePatternDimension, BlueprintDimensionState>>
  relationship: BlueprintRelationshipState
}

export interface OriginalityEvidence {
  signal: OriginalitySignal
  score: number
  summary: string
  dimension: ReferencePatternDimension | null
  source_segment_id: string | null
  source_character_start: number | null
  source_character_end: number | null
  evidence_sha256: string
}

export interface OriginalityReport {
  id: string
  application_id: string
  blueprint_revision: number
  risk_level: OriginalityRiskLevel
  score: number
  threshold_version: string
  checked_dimensions: ReferencePatternDimension[]
  evidence: OriginalityEvidence[]
  source_segment_ids: string[]
  input_sha256: string
  legal_notice: string
  viewed_at: string | null
  acknowledged_at?: string | null
  created_at: string
}

export type SceneOriginalitySignal =
  | 'semantic_scene'
  | 'ordered_sequence'
  | 'causal_graph'
  | 'character_function_graph'
  | 'multi_source_convergence'

export interface SceneGraphNode {
  id: string
  label: string
  semantic_terms: string[]
}

export interface SceneGraphEdge {
  source: string
  target: string
  relation: string
}

export interface SceneOriginalityFinding {
  signal: SceneOriginalitySignal
  score: number
  summary: string
  source_segment_ids: string[]
  evidence_sha256: string
}

export interface SceneOriginalityCheck {
  id: string
  application_id: string
  blueprint_revision: number
  risk_level: OriginalityRiskLevel
  score: number
  threshold_version: string
  candidate_graph: {
    nodes: SceneGraphNode[]
    edges: SceneGraphEdge[]
  }
  findings: SceneOriginalityFinding[]
  source_segment_ids: string[]
  source_work_count: number
  input_sha256: string
  legal_notice: string
  status: OriginalityStatus
  viewed_at: string | null
  acknowledged_at: string | null
  created_at: string
}

export interface ReferencePatternApplication {
  id: string
  project_id: string
  pattern_card_id: string
  lifecycle_state: ReferenceApplicationLifecycleState
  lifecycle_revision: number
  selected_dimensions: ReferencePatternDimension[]
  dimensions: Partial<Record<ReferencePatternDimension, AppliedReferenceDimension>>
  relationship_recomposition: string
  application_note: string
  blueprint: ReferenceBlueprintState | null
  originality_status: OriginalityStatus
  risk_level: OriginalityRiskLevel | null
  latest_report_id: string | null
  threshold_version: string | null
  revision: number
  created_at: string
  updated_at: string | null
}

export interface ApplyReferencePatternInput {
  selected_dimensions: ReferencePatternDimension[]
  application_note: string
  confirm_original_adaptation: boolean
  blueprint?: ReferenceBlueprintState
}

export interface UpdateReferenceApplicationLifecycleInput {
  lifecycle_state: ReferenceApplicationLifecycleState
  expected_lifecycle_revision: number
}

export interface UpdateReferenceBlueprintInput {
  blueprint: ReferenceBlueprintState
  changed_dimensions: ReferencePatternDimension[]
  relationship_changed: boolean
  expected_revision: number
}

export interface AcknowledgeOriginalityReportInput {
  expected_revision: number
}

export interface UpdateChapterInput {
  content: string
  expected_revision: number
}

export interface UpdateChapterBriefInput {
  title?: string
  reader_promise: string
  opening_hook: string
  state_change: string
  emotional_payoff: string
  ending_cliffhanger: string
  expected_revision: number
}

export interface CreateChapterInput {
  expected_last_chapter_number: number
  title?: string
  reader_promise?: string
  opening_hook?: string
  state_change?: string
  emotional_payoff?: string
  ending_cliffhanger?: string
}

export interface TransitionChapterInput {
  target_status: ChapterStatus
  expected_revision: number
}

export interface GenerationRun {
  id: string
  chapter_id: string
  state: GenerationState
  expected_chapter_revision: number
  candidate_content: string | null
  error_message: string | null
  provider: string
  model: string
  created_at: string
  updated_at: string
}

export interface DirectorChapterPipelineResult {
  job_id: string
  project_id: string
  chapter_id: string
  chapter_revision: number
  completed_stages: DirectorPipelineStage[]
  brief: AiChapterBriefProposal
  pre_review: DirectorPreReview
  draft: GenerationRun
}

export interface Job {
  id: string
  project_id: string
  chapter_id: string | null
  parent_job_id: string | null
  kind: JobKind
  workflow: string
  state: JobState
  idempotency_key: string
  progress_current: number
  progress_total: number
  current_step: string
  estimated_calls: number
  completed_calls: number
  provider: string
  provider_profile_id: string | null
  model: string
  lease_owner: string | null
  lease_expires_at: string | null
  heartbeat_at: string | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
}

export interface JobChunk {
  id: string
  job_id: string
  kind: JobKind
  ordinal: number
  state: JobChunkState
  idempotency_key: string
  attempt_count: number
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface JobAttempt {
  id: string
  job_id: string
  chunk_id: string | null
  ordinal: number
  state: JobAttemptState
  provider: string
  provider_profile_id: string | null
  model: string
  input_tokens: number | null
  output_tokens: number | null
  duration_ms: number | null
  estimated_cost_microusd: number | null
  error_code: string | null
  error_message: string | null
  started_at: string
  completed_at: string | null
}

export interface JobArtifact {
  id: string
  job_id: string
  chunk_id: string | null
  kind: string
  artifact_key: string
  content_type: 'application/json' | 'text/plain'
  payload_sha256: string
  metadata: Record<string, unknown>
  provider: string
  provider_profile_id: string | null
  model: string
  created_at: string
}

export interface JobArtifactContent extends JobArtifact {
  payload: string
}

export interface JobEvent {
  id: string
  job_id: string
  sequence: number
  event_type: string
  from_state: JobState | null
  to_state: JobState | null
  detail: Record<string, unknown>
  created_at: string
}

export interface JobDetail extends Job {
  chunks: JobChunk[]
  attempts: JobAttempt[]
  artifacts: JobArtifact[]
  events: JobEvent[]
}

export type ComicAdaptationMode = 'faithful' | 'balanced' | 'dramatic'
export type ComicProjectState = 'draft' | 'planning' | 'outlined' | 'producing' | 'completed'
export type ComicApprovalState = 'candidate' | 'approved' | 'rejected'
export type ComicScriptState = 'empty' | ComicApprovalState
export type ComicTargetKind = 'season' | 'episode_outline' | 'episode_script'

export interface ComicDialogueDraft {
  character: string
  line: string
  emotion: string
}

export interface ComicAssetRequirement {
  kind: 'character' | 'location' | 'costume' | 'prop' | 'effect' | 'other'
  name: string
  description: string
}

export interface ComicSceneDraft {
  scene_number: number
  interior_exterior: 'INT' | 'EXT' | 'INT/EXT'
  location: string
  time_of_day: string
  cast: string[]
  action: string
  dialogue: ComicDialogueDraft[]
  narration: string
  visual_focus: string
  ending_beat: string
  source_chapter_ids: string[]
  asset_requirements: ComicAssetRequirement[]
}

export interface ComicEpisodeOutlineDraft {
  episode_number: number
  title: string
  source_chapter_ids: string[]
  opening_hook: string
  episode_goal: string
  core_conflict: string
  reversal: string
  emotional_payoff: string
  ending_cliffhanger: string
  cast: string[]
  locations: string[]
  key_props: string[]
  next_episode_promise: string
}

export interface ComicSeasonDraft {
  logline: string
  theme: string
  core_desire: string
  main_conflict: string
  adaptation_strategy: string
  character_recomposition: string[]
  episode_outlines: ComicEpisodeOutlineDraft[]
}

export interface ComicEpisodeScriptDraft {
  episode_number: number
  title: string
  estimated_seconds: number
  scenes: ComicSceneDraft[]
}

export interface CreateComicProjectInput {
  title: string
  source_chapter_ids: string[]
  episode_target_count: number
  episode_duration_seconds: number
  aspect_ratio: '9:16' | '16:9' | '1:1'
  art_style: string
  adaptation_mode: ComicAdaptationMode
  narration_preference: string
  author_requirements: string
}

export interface ComicProject {
  id: string
  project_id: string
  title: string
  source_chapter_ids: string[]
  source_snapshot_sha256: string
  episode_target_count: number
  episode_duration_seconds: number
  aspect_ratio: '9:16' | '16:9' | '1:1'
  art_style: string
  adaptation_mode: ComicAdaptationMode
  narration_preference: string
  author_requirements: string
  state: ComicProjectState
  season_revision: number
  created_at: string
  updated_at: string
}

export interface ComicEpisode {
  id: string
  comic_project_id: string
  episode_number: number
  title: string
  source_chapter_ids: string[]
  outline_state: ComicApprovalState
  script_state: ComicScriptState
  outline_revision: number
  script_revision: number
  created_at: string
  updated_at: string
}

export interface ComicVersion {
  id: string
  comic_project_id: string
  episode_id: string | null
  target_kind: ComicTargetKind
  target_id: string
  version_number: number
  state: ComicApprovalState
  content: ComicSeasonDraft | ComicEpisodeOutlineDraft | ComicEpisodeScriptDraft
  content_sha256: string
  source_snapshot_sha256: string
  job_id: string | null
  created_at: string
  reviewed_at: string | null
}

export interface ComicScene {
  id: string
  comic_project_id: string
  episode_id: string
  script_version_id: string
  scene_number: number
  content: ComicSceneDraft
  source_chapter_ids: string[]
  created_at: string
}

export interface ComicWorkspace {
  project: ComicProject
  episodes: ComicEpisode[]
  versions: ComicVersion[]
  scenes: ComicScene[]
}

export interface ComicAiPreview {
  source_snapshot_sha256: string
  character_count: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_cost_microusd: number | null
  profile_id: string
  profile_name: string
  provider: string
  model: string
  requires_external_confirmation: boolean
  data_types: string[]
  content_scope: string
}

export interface ComicSeasonSubmission { comic_project_id: string; job: Job }
export interface ComicEpisodeSubmission { comic_project_id: string; episode_id: string; job: Job }

export interface ComicAuditIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
  episode_id: string
  episode_number: number
  scene_number: number | null
}

export interface ComicAsset {
  kind: string
  name: string
  description: string
  first_episode: number
  episode_numbers: number[]
}

export interface ComicDeleteImpact {
  comic_project_id: string
  episode_count: number
  version_count: number
  scene_count: number
  can_delete: boolean
}

export interface ComicProductionPackage {
  format: 'mozhou-ai-comic-production-package'
  format_version: 1
  ai_generated: true
  project: ComicProject
  season: ComicSeasonDraft | null
  season_version: number | null
  episodes: Array<Record<string, unknown>>
  assets: ComicAsset[]
  audit: ComicAuditIssue[]
  compliance_checklist: string[]
  source_snapshot_sha256: string
  package_sha256: string
}

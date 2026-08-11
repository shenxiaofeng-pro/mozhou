import type { Workspace, WorkspaceSummary } from '@mozhou/contracts'

import { genreLabels } from '../genre'
import { ReferenceLabPanel } from './ReferenceLabPanel'

interface ReferenceLibraryPageProps {
  workspace: WorkspaceSummary
  onWorkspaceChanged: (workspace: Workspace | WorkspaceSummary) => void
  onBack: () => void
  onOpenTaskCenter: () => void
  onOpenGlobalLibrary: () => void
}

export function ReferenceLibraryPage({
  workspace,
  onWorkspaceChanged,
  onBack,
  onOpenTaskCenter,
  onOpenGlobalLibrary,
}: ReferenceLibraryPageProps) {
  const segmentCount = workspace.reference_works.reduce(
    (total, work) => total + work.segments.length,
    0,
  )

  return (
    <main className="reference-library-page">
      <header className="reference-library-bar">
        <div className="reference-library-brand">
          <span aria-hidden="true">墨</span>
          <div><small>墨舟 · 拆书库</small><strong>{workspace.project.title}</strong></div>
        </div>
        <div className="reference-library-actions">
          <button type="button" onClick={onOpenGlobalLibrary}>全局资料码头</button>
          <button type="button" onClick={onOpenTaskCenter}>任务中心</button>
          <button type="button" onClick={onBack}>返回创作台</button>
        </div>
      </header>

      <section className="reference-library-hero" aria-labelledby="reference-library-title">
        <div>
          <p>REFERENCE DOSSIER / {genreLabels[workspace.project.genre]}</p>
          <h1 id="reference-library-title">先拆成规律，再带回你的书</h1>
          <span>参考原文留在隔离库；只有作者选中的抽象结构，才能成为当前作品的创作蓝图。</span>
        </div>
        <dl>
          <div><dt>参考作品</dt><dd>{workspace.reference_works.length}</dd></div>
          <div><dt>分析区段</dt><dd>{segmentCount}</dd></div>
          <div><dt>模式卡</dt><dd>{workspace.reference_pattern_cards.length}</dd></div>
          <div><dt>已应用</dt><dd>{workspace.reference_pattern_applications.length}</dd></div>
        </dl>
      </section>

      <div className="reference-library-desk">
        <aside className="reference-flow-rail" aria-label="拆书应用流程">
          <p>内容边界</p>
          <ol>
            <li data-complete={workspace.reference_works.length > 0}>
              <span>原文隔离</span><small>多书导入与 50 万字切段</small>
            </li>
            <li data-complete={workspace.reference_pattern_cards.length > 0}>
              <span>六维模式</span><small>只留下可验证的抽象规律</small>
            </li>
            <li data-complete={workspace.reference_pattern_applications.length > 0}>
              <span>应用蓝图</span><small>由作者选择后进入当前作品</small>
            </li>
          </ol>
          <blockquote>“参考”提供功能规律，不提供可以照搬的桥段。</blockquote>
        </aside>
        <div className="reference-library-content">
          <ReferenceLabPanel
            workspace={workspace}
            onWorkspaceChanged={onWorkspaceChanged}
          />
        </div>
      </div>
    </main>
  )
}

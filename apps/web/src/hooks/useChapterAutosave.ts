import type { Chapter } from '@mozhou/contracts'
import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api'

export type SaveStatus = 'saved' | 'dirty' | 'saving' | 'error'

interface AutosaveResult {
  draft: string
  saveStatus: SaveStatus
  saveError: string | null
  setDraft: (value: string) => void
  flushNow: () => Promise<boolean>
  retry: () => void
  adoptServerVersion: (chapter: Chapter) => void
}

export function useChapterAutosave(
  chapter: Chapter,
  onSaved: (chapter: Chapter) => void,
): AutosaveResult {
  const [draft, setDraftState] = useState(chapter.content)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('saved')
  const [saveError, setSaveError] = useState<string | null>(null)
  const chapterIdRef = useRef(chapter.id)
  const revisionRef = useRef(chapter.revision)
  const savedContentRef = useRef(chapter.content)
  const draftRef = useRef(chapter.content)
  const pendingRef = useRef<string | null>(null)
  const savingPromiseRef = useRef<Promise<boolean> | null>(null)

  const performFlush = useCallback(async (): Promise<boolean> => {
    while (pendingRef.current !== null) {
      const content = pendingRef.current
      pendingRef.current = null
      setSaveStatus('saving')
      setSaveError(null)
      try {
        const updated = await api.updateChapter(chapterIdRef.current, {
          content,
          expected_revision: revisionRef.current,
        })
        revisionRef.current = updated.revision
        savedContentRef.current = updated.content
        onSaved(updated)
        setSaveStatus(draftRef.current === updated.content && pendingRef.current === null ? 'saved' : 'dirty')
      } catch (error) {
        pendingRef.current = draftRef.current === savedContentRef.current ? null : draftRef.current
        setSaveStatus('error')
        setSaveError(error instanceof Error ? error.message : '自动保存失败')
        return false
      }
    }
    return true
  }, [onSaved])

  const flushNow = useCallback(async (): Promise<boolean> => {
    if (draftRef.current !== savedContentRef.current) {
      pendingRef.current = draftRef.current
    }
    if (savingPromiseRef.current) {
      const currentSave = savingPromiseRef.current
      const succeeded = await currentSave
      if (!succeeded) return false
      if (savingPromiseRef.current === currentSave) savingPromiseRef.current = null
    }
    if (pendingRef.current === null) return true

    const operation = performFlush()
    savingPromiseRef.current = operation
    const succeeded = await operation
    if (savingPromiseRef.current === operation) savingPromiseRef.current = null
    return succeeded
  }, [performFlush])

  useEffect(() => {
    if (draft === savedContentRef.current) {
      if (!savingPromiseRef.current) setSaveStatus('saved')
      return
    }
    setSaveStatus('dirty')
    const timeout = window.setTimeout(() => {
      void flushNow()
    }, 700)
    return () => window.clearTimeout(timeout)
  }, [draft, flushNow])

  const setDraft = useCallback((value: string) => {
    draftRef.current = value
    setDraftState(value)
  }, [])

  const retry = useCallback(() => {
    void flushNow()
  }, [flushNow])

  const adoptServerVersion = useCallback((updated: Chapter) => {
    chapterIdRef.current = updated.id
    revisionRef.current = updated.revision
    savedContentRef.current = updated.content
    draftRef.current = updated.content
    pendingRef.current = null
    setDraftState(updated.content)
    setSaveStatus('saved')
    setSaveError(null)
  }, [])

  return { draft, saveStatus, saveError, setDraft, flushNow, retry, adoptServerVersion }
}

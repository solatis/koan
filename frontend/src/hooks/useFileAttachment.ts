import { useState, useRef, useCallback, useMemo, type DragEvent } from 'react'
import { uploadFile, type UploadedFile } from '../api/client'

type FileChipState = 'ready' | 'uploading' | 'error'

export interface AttachedFile {
  id: string
  name: string
  size: string
  state: FileChipState
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`
  return `${(bytes / (1024 * 1024)).toFixed(1)}M`
}

export function useFileAttachment() {
  const [files, setFiles] = useState<AttachedFile[]>([])
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const dragCounter = useRef(0)

  const addFiles = useCallback(async (fileList: FileList | File[]) => {
    const incoming = Array.from(fileList)
    const placeholders: AttachedFile[] = incoming.map(f => ({
      id: `pending-${Date.now()}-${f.name}`,
      name: f.name,
      size: formatSize(f.size),
      state: 'uploading' as const,
    }))

    setFiles(prev => [...prev, ...placeholders])

    for (let i = 0; i < incoming.length; i++) {
      const f = incoming[i]
      const placeholderId = placeholders[i].id
      try {
        const uploaded: UploadedFile = await uploadFile(f)
        setFiles(prev => prev.map(af =>
          af.id === placeholderId
            ? { id: uploaded.id, name: uploaded.filename, size: formatSize(uploaded.size), state: 'ready' as const }
            : af
        ))
      } catch {
        setFiles(prev => prev.map(af =>
          af.id === placeholderId
            ? { ...af, state: 'error' as const }
            : af
        ))
      }
    }
  }, [])

  const removeFile = useCallback((id: string) => {
    setFiles(prev => prev.filter(f => f.id !== id))
  }, [])

  const clearFiles = useCallback(() => {
    setFiles([])
  }, [])

  const openPicker = useCallback(() => {
    inputRef.current?.click()
  }, [])

  const onInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(e.target.files)
      e.target.value = ''
    }
  }, [addFiles])

  const onDragEnter = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current++
    if (e.dataTransfer.types.includes('Files')) {
      setDragging(true)
    }
  }, [])

  const onDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current--
    if (dragCounter.current === 0) {
      setDragging(false)
    }
  }, [])

  const onDragOver = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const onDrop = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current = 0
    setDragging(false)
    if (e.dataTransfer.files.length > 0) {
      addFiles(e.dataTransfer.files)
    }
  }, [addFiles])

  const onPaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData.items
    const pastedFiles: File[] = []
    for (let i = 0; i < items.length; i++) {
      if (items[i].kind === 'file') {
        const f = items[i].getAsFile()
        if (f) pastedFiles.push(f)
      }
    }
    if (pastedFiles.length > 0) {
      addFiles(pastedFiles)
    }
  }, [addFiles])

  // Memoized so consumers depending on fileIds in effect dep arrays don't
  // re-fire on every render. Identity is stable until files change.
  const fileIds = useMemo(
    () => files.filter(f => f.state === 'ready').map(f => f.id),
    [files],
  )

  const dragProps = { onDragEnter, onDragLeave, onDragOver, onDrop }

  return {
    files,
    fileIds,
    dragging,
    inputRef,
    addFiles,
    removeFile,
    clearFiles,
    openPicker,
    onInputChange,
    onPaste,
    dragProps,
  }
}

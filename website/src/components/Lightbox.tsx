import { X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { SCREENS, shot } from '../screens'

export function Lightbox({ file, onClose }: { file: string | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!file) return
    const prev = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = ''; prev?.focus() }
  }, [file, onClose])
  if (!file) return null
  const label = SCREENS.find(s => s.file === file)?.label ?? 'Screenshot'
  return (
    <div role="dialog" aria-modal="true" aria-label={`${label} — full size`} onClick={onClose}
         className="fixed inset-0 z-[100] flex items-center justify-center bg-[#01040c]/92 p-3 sm:p-8">
      <button ref={closeRef} type="button" onClick={onClose} aria-label="Close preview"
              className="absolute right-4 top-4 grid size-10 place-items-center rounded-lg border border-line-strong bg-surface text-ink">
        <X className="size-5" />
      </button>
      <img src={shot(file)} alt={`${label} screen, full size`} onClick={e => e.stopPropagation()}
           className="shot-in max-h-full max-w-full rounded-lg border border-line-strong object-contain" />
    </div>
  )
}

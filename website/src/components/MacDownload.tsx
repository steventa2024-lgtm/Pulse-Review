import { Apple } from 'lucide-react'
import type { ReleaseInfo } from '../hooks/useRelease'
import { Button } from './ui'

export function MacDownload({ release }: { release: ReleaseInfo | null }) {
  if (!release) return (
    <button type="button" disabled aria-disabled="true" className="inline-flex items-center justify-center gap-2 rounded-xl border border-line-strong px-6 h-12 text-[15px] font-semibold text-muted opacity-70 w-full sm:w-auto">
      <Apple className="size-4" aria-hidden="true" /> macOS beta coming soon
    </button>
  )
  return <Button href={release.downloadUrl} variant="secondary" className="w-full sm:w-auto h-12 px-6">
    <Apple className="size-4" aria-hidden="true" /> Download for macOS
  </Button>
}

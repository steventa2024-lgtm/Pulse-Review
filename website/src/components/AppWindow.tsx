import type { ReactNode } from 'react'

/** Frames a real screenshot of the desktop app like its Windows window. The screenshot itself is never altered. */
export function AppWindow({ children, title = 'ZeroPulse PR Review Agent' }: { children: ReactNode; title?: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line-strong bg-[#050d20] shadow-[0_30px_80px_rgb(0_4_20/0.65),0_0_0_1px_rgb(0_0_0/0.4)]">
      <div className="flex h-8 items-center gap-2 border-b border-line bg-[#071126] px-3 select-none" aria-hidden="true">
        <img src="./brand/icon.png" alt="" className="size-4 rounded-[4px]" />
        <span className="text-[12px] text-ink-2">{title}</span>
        <span className="ml-auto flex items-center gap-4 text-muted">
          <span className="block h-px w-2.5 bg-current" />
          <span className="block size-2.5 border border-current" />
          <span className="text-[13px] leading-none">✕</span>
        </span>
      </div>
      {children}
    </div>
  )
}

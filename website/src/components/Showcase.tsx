import { Maximize2 } from 'lucide-react'
import { useRef, useState, type KeyboardEvent } from 'react'
import { SCREENS, shot } from '../screens'
import { AppWindow } from './AppWindow'
import { Section } from './ui'

export function Showcase({ onZoom }: { onZoom: (file: string) => void }) {
  const [idx, setIdx] = useState(0)
  const tabs = useRef<(HTMLButtonElement | null)[]>([])
  const s = SCREENS[idx]

  const onKey = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const next = (idx + (e.key === 'ArrowRight' ? 1 : SCREENS.length - 1)) % SCREENS.length
    setIdx(next)
    tabs.current[next]?.focus()
  }

  return (
    <Section id="screenshots" eyebrow="Screenshots" title="Experience PulseReview."
             intro="Real screenshots of the desktop app. Pick a screen to see what it does.">
      <div role="tablist" aria-label="Application screens" onKeyDown={onKey}
           className="-mx-5 sm:mx-0 flex gap-2 overflow-x-auto px-5 sm:px-0 pb-2 [scrollbar-width:none]">
        {SCREENS.map((sc, i) => (
          <button key={sc.id} ref={el => { tabs.current[i] = el }} role="tab" id={`tab-${sc.id}`} aria-selected={i === idx}
                  aria-controls="screen-panel" tabIndex={i === idx ? 0 : -1} onClick={() => setIdx(i)}
                  className={`shrink-0 rounded-lg border px-4 h-10 text-sm font-medium transition-colors ${i === idx
                    ? 'border-accent-2/60 bg-accent-soft text-ink'
                    : 'border-line bg-surface/60 text-muted hover:text-ink hover:border-line-strong'}`}>
            {sc.label}
          </button>
        ))}
      </div>
      <div id="screen-panel" role="tabpanel" aria-labelledby={`tab-${s.id}`} className="mt-6 grid gap-8 lg:grid-cols-[1fr_300px] items-start">
        <button type="button" onClick={() => onZoom(s.file)} className="group relative block cursor-zoom-in text-left" aria-label={`Enlarge the ${s.label} screenshot`}>
          <AppWindow>
            <img key={s.file} src={shot(s.file)} alt={`${s.label} screen of PulseReview`} width={2880} height={1800}
                 loading="lazy" decoding="async" className="shot-in block w-full h-auto" />
          </AppWindow>
          <span className="absolute right-3 bottom-3 inline-flex items-center gap-1.5 rounded-lg border border-line-strong bg-bg/85 px-2.5 py-1.5 text-xs text-ink-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            <Maximize2 className="size-3.5" /> Enlarge
          </span>
        </button>
        <div key={s.id} className="shot-in lg:pt-4">
          <p className="text-[13px] font-semibold uppercase tracking-[0.14em] text-accent-2">{s.label}</p>
          <h3 className="mt-2 text-2xl font-semibold tracking-tight">{s.title}</h3>
          <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{s.text}</p>
          <p className="mt-6 text-sm text-muted">{idx + 1} / {SCREENS.length} · use ← → to switch</p>
        </div>
      </div>
    </Section>
  )
}

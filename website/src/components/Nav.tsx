import { Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { WindowsIcon } from './BrandIcons'

const LINKS = [
  { id: 'features', label: 'Features' },
  { id: 'how-it-works', label: 'How It Works' },
  { id: 'screenshots', label: 'Screenshots' },
  { id: 'open-source', label: 'AI models' },
  { id: 'faq', label: 'FAQ' },
]

export function Nav({ downloadUrl }: { downloadUrl: string }) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState<string>('')
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    const io = new IntersectionObserver(entries => {
      for (const e of entries) if (e.isIntersecting) setActive(e.target.id)
    }, { rootMargin: '-45% 0px -50% 0px' })
    LINKS.forEach(l => { const el = document.getElementById(l.id); if (el) io.observe(el) })
    return () => { window.removeEventListener('scroll', onScroll); io.disconnect() }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <header className={`sticky top-0 z-50 border-b transition-colors duration-200 ${scrolled || open ? 'border-line bg-bg/90 backdrop-blur-md' : 'border-transparent bg-transparent'}`}>
      <nav className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-5 sm:px-8" aria-label="Main">
        <a href="#top" className="flex items-center gap-2.5 shrink-0" aria-label="PulseReview — home">
          <img src="./brand/icon.png" alt="" className="size-8 rounded-lg" width={32} height={32} />
          <span className="font-semibold tracking-tight">Pulse<span className="text-accent-2">Review</span> <span className="text-ink-2 font-medium hidden sm:inline">by ZeroPulse</span></span>
        </a>
        <ul className="mx-auto hidden lg:flex items-center gap-1">
          {LINKS.map(l => (
            <li key={l.id}>
              <a href={`#${l.id}`} aria-current={active === l.id ? 'true' : undefined}
                 className={`relative rounded-lg px-3 py-2 text-sm font-medium transition-colors ${active === l.id ? 'text-ink' : 'text-muted hover:text-ink'}`}>
                {l.label}
                <span className={`absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-accent transition-opacity ${active === l.id ? 'opacity-100' : 'opacity-0'}`} />
              </a>
            </li>
          ))}
        </ul>
        <a href={downloadUrl} className="ml-auto lg:ml-0 hidden sm:inline-flex items-center gap-2 rounded-lg bg-accent px-4 h-9 text-sm font-semibold text-white hover:bg-accent-hover transition-colors">
          <WindowsIcon className="size-3.5" /> Download for Windows
        </a>
        <button type="button" className="lg:hidden ml-auto sm:ml-0 grid size-10 place-items-center rounded-lg border border-line text-ink-2"
                aria-expanded={open} aria-controls="mobile-menu" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen(o => !o)}>
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </nav>
      <div id="mobile-menu" hidden={!open} className="lg:hidden border-t border-line bg-bg px-5 pb-5">
        <ul className="flex flex-col py-2">
          {LINKS.map(l => (
            <li key={l.id}>
              <a href={`#${l.id}`} onClick={() => setOpen(false)} className="block rounded-lg px-3 py-3 text-base font-medium text-ink-2 hover:bg-surface hover:text-ink">{l.label}</a>
            </li>
          ))}
        </ul>
        <a href={downloadUrl} className="flex items-center justify-center gap-2 rounded-xl bg-accent h-12 font-semibold text-white">
          <WindowsIcon /> Download for Windows
        </a>
      </div>
    </header>
  )
}

import type { ReactNode } from 'react'
import { useReveal } from '../hooks/useReveal'

type BtnProps = { href: string; children: ReactNode; variant?: 'primary' | 'secondary'; className?: string; external?: boolean; ariaLabel?: string }

export function Button({ href, children, variant = 'primary', className = '', external, ariaLabel }: BtnProps) {
  const base = 'inline-flex items-center justify-center gap-2 rounded-xl px-5 h-11 text-[15px] font-semibold transition-colors duration-150 whitespace-nowrap'
  const styles = variant === 'primary'
    ? 'bg-accent text-white hover:bg-accent-hover shadow-[0_0_0_1px_rgb(120_180_255/0.5),0_8px_24px_rgb(47_124_255/0.28)]'
    : 'bg-surface text-ink border border-line-strong hover:bg-surface-2 hover:border-accent-2/50'
  return (
    <a href={href} aria-label={ariaLabel} className={`${base} ${styles} ${className}`}
       {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
      {children}
    </a>
  )
}

export function Section({ id, eyebrow, title, intro, children, className = '' }: {
  id?: string; eyebrow?: string; title: string; intro?: ReactNode; children: ReactNode; className?: string
}) {
  const ref = useReveal<HTMLDivElement>()
  return (
    <section id={id} className={`relative px-5 sm:px-8 py-20 sm:py-28 ${className}`}>
      <div ref={ref} className="reveal mx-auto max-w-6xl">
        <div className="max-w-2xl">
          {eyebrow && <p className="text-[13px] font-semibold tracking-[0.14em] uppercase text-accent-2">{eyebrow}</p>}
          <h2 className="mt-3 text-3xl sm:text-4xl font-bold tracking-tight text-balance">{title}</h2>
          {intro && <p className="mt-4 text-lg text-ink-2 leading-relaxed">{intro}</p>}
        </div>
        <div className="mt-12">{children}</div>
      </div>
    </section>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`min-w-0 rounded-2xl border border-line bg-surface/70 p-6 transition-colors duration-200 hover:border-line-strong ${className}`}>
      {children}
    </div>
  )
}

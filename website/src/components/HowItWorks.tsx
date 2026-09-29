import { ScanSearch, SquareCheckBig } from 'lucide-react'
import { GitHubIcon } from './BrandIcons'
import { Section } from './ui'

const STEPS = [
  { icon: GitHubIcon, title: 'Connect GitHub', text: 'Sign in with GitHub (or use a personal access token), then pick the repository and the pull request you want reviewed.' },
  { icon: ScanSearch, title: 'Run AI Analysis', text: 'Choose an available model and start. The agent reads the actual changes, runs static checks and asks the model to analyse the diff.' },
  { icon: SquareCheckBig, title: 'Explore Results', text: 'Review verified findings, suggested fixes, the risk rating and the proposed test file. Post to GitHub only if you want to.' },
]

export function HowItWorks() {
  return (
    <Section id="how-it-works" eyebrow="How it works" title="From Pull Request to Actionable Insights.">
      <ol className="relative grid gap-10 md:grid-cols-3 md:gap-6">
        <span aria-hidden="true" className="absolute left-[21px] top-2 bottom-2 w-px bg-line md:left-[calc(16.66%)] md:right-[calc(16.66%)] md:top-[21px] md:bottom-auto md:h-px md:w-auto" />
        {STEPS.map(({ icon: Icon, title, text }, i) => (
          <li key={title} className="relative flex gap-5 md:flex-col md:items-center md:text-center">
            <span className="relative z-10 grid size-11 shrink-0 place-items-center rounded-full border border-accent-2/60 bg-bg text-[15px] font-bold text-accent-2 shadow-[0_0_0_6px_var(--color-bg)]">
              {i + 1}
            </span>
            <div className="md:mt-5 md:max-w-xs">
              <h3 className="flex items-center gap-2 text-lg font-semibold md:justify-center"><Icon className="size-4 text-muted" />{title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{text}</p>
            </div>
          </li>
        ))}
      </ol>
    </Section>
  )
}

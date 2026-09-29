import { Boxes, Eye, FlaskConical, GitPullRequestArrow, History, KeyRound, ListChecks, Send, ShieldAlert, TestTubeDiagonal } from 'lucide-react'
import type { ComponentType } from 'react'
import { Card, Section } from './ui'

// Every item below is implemented in the app (see README / ARCHITECTURE.md). No metrics or benchmarks are claimed.
const FEATURES: { icon: ComponentType<{ className?: string }>; title: string; text: string }[] = [
  { icon: GitPullRequestArrow, title: 'AI Code Reviews', text: 'Analyze GitHub pull requests and receive actionable feedback about the changed code — correctness, error handling, security, performance and maintainability.' },
  { icon: ListChecks, title: 'Detailed Findings', text: 'Each finding names the file and line, quotes the evidence and suggests a fix. Findings are checked against the real diff and labelled verified, plausible or unverified.' },
  { icon: TestTubeDiagonal, title: 'Test Generation', text: 'Generate one suggested test file per review in the repository’s own framework (pytest, Jest/Vitest, Go testing and more) to cover the change.' },
  { icon: ShieldAlert, title: 'Risk Analysis', text: 'An overall risk rating plus static checks for committed credentials, risky calls, syntax errors and behavioural changes without tests.' },
  { icon: KeyRound, title: 'Code Reviewer', text: 'Audit a whole repository, a folder or one file for vulnerabilities, leaked API keys, bugs, performance and maintainability, with a scored breakdown.' },
  { icon: Boxes, title: 'Multiple AI Models', text: 'Use free models from OpenRouter (API key required) or models running locally through Ollama. Switch at any time without restarting.' },
  { icon: History, title: 'Review History', text: 'Every review is stored in a local database on your computer. Reopen, filter, export as Markdown or JSON, or delete it.' },
  { icon: Eye, title: 'Watched Repositories', text: 'Add repositories and see new or updated pull requests. Optional automatic analysis — never automatic publishing.' },
  { icon: FlaskConical, title: 'Test Lab', text: 'All generated tests in one place, with an optional isolated Docker sandbox to run them. Results are only reported after a real run.' },
  { icon: Send, title: 'You Approve What Gets Posted', text: 'Preview and edit the review, confirm the exact repository and PR, then post a COMMENT review. Stale and duplicate posts are blocked.' },
]

export function Features() {
  return (
    <Section id="features" eyebrow="Features" title="Everything You Need for Better Code Reviews."
             intro="A desktop companion that reads the real changes, explains what could go wrong and helps you fix it — while you stay in control.">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, text }, i) => {
          const wide = i === FEATURES.length - 1 // closing card spans the row instead of leaving an orphan
          return (
            <Card key={title} className={wide ? 'sm:col-span-2 lg:col-span-3 sm:flex sm:items-center sm:gap-6' : ''}>
              <div className="grid size-11 shrink-0 place-items-center rounded-xl border border-line-strong bg-accent-soft text-accent-2">
                <Icon className="size-5" />
              </div>
              <div>
                <h3 className={`${wide ? 'mt-5 sm:mt-0' : 'mt-5'} text-lg font-semibold`}>{title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{text}</p>
              </div>
            </Card>
          )
        })}
      </div>
    </Section>
  )
}

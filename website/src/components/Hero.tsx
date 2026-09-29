import { Bot, Code2, GitPullRequest, Monitor } from 'lucide-react'
import { REPO_URL } from '../config'
import { prettyVersion, type ReleaseInfo } from '../hooks/useRelease'
import { shot } from '../screens'
import { AppWindow } from './AppWindow'
import { GitHubIcon, WindowsIcon } from './BrandIcons'
import { Button } from './ui'

export function Hero({ release, onZoom }: { release: ReleaseInfo; onZoom: (file: string) => void }) {
  return (
    <section id="top" className="relative px-5 sm:px-8 pt-14 sm:pt-20 pb-10">
      <div className="mx-auto max-w-6xl text-center">
        <a href={release.url} className="enter inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface/70 px-3.5 py-1.5 text-[13px] text-ink-2 hover:text-ink transition-colors"
           style={{ animationDelay: '0s' }}>
          <span className="size-1.5 rounded-full bg-ok" aria-hidden="true" />
          {prettyVersion(release.tag)} is available for Windows
        </a>
        <h1 className="enter mt-6 text-4xl sm:text-6xl lg:text-7xl font-bold tracking-tight text-balance" style={{ animationDelay: '.08s' }}>
          Turn Pull Requests Into <span className="text-accent-2">Better Code.</span>
        </h1>
        <p className="enter mx-auto mt-6 max-w-2xl text-lg sm:text-xl text-ink-2 leading-relaxed text-pretty" style={{ animationDelay: '.2s' }}>
          AI-powered GitHub pull request reviews, actionable code suggestions, automated test generation, and risk analysis
          using open-source AI models. Built for developers who want deeper insights into their code.
        </p>
        <div className="enter mt-9 flex flex-col sm:flex-row items-center justify-center gap-3" style={{ animationDelay: '.32s' }}>
          <Button href={release.downloadUrl} className="w-full sm:w-auto h-12 px-6"><WindowsIcon /> Download for Windows</Button>
          <Button href={REPO_URL} variant="secondary" external className="w-full sm:w-auto h-12 px-6"><GitHubIcon /> View on GitHub</Button>
        </div>
        <ul className="enter mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-3 text-sm text-muted" style={{ animationDelay: '.42s' }}>
          <li className="flex items-center gap-2"><Code2 className="size-4 text-accent-2" />Source on GitHub</li>
          <li className="flex items-center gap-2"><Monitor className="size-4 text-accent-2" />Windows desktop</li>
          <li className="flex items-center gap-2"><Bot className="size-4 text-accent-2" />AI-powered reviews</li>
          <li className="flex items-center gap-2"><GitPullRequest className="size-4 text-accent-2" />GitHub integration</li>
        </ul>
      </div>

      <div className="enter-app relative mx-auto mt-14 sm:mt-16 max-w-6xl">
        <button type="button" onClick={() => onZoom('dashboard')} className="block w-full cursor-zoom-in text-left" aria-label="Enlarge the dashboard screenshot">
          <AppWindow>
            <img src={shot('dashboard')} alt="ZeroPulse PR Review Agent dashboard: sidebar navigation, GitHub, model and sandbox status in the top bar, review totals and the recent reviews table"
                 width={2880} height={1800} className="block w-full h-auto" fetchPriority="high" decoding="async" />
          </AppWindow>
        </button>
        <p className="mt-4 text-center text-xs text-muted">Actual application screenshot (sample data).</p>
      </div>
    </section>
  )
}

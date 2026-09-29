import { REPO_URL } from '../config'
import { prettyVersion, type ReleaseInfo } from '../hooks/useRelease'
import { useReveal } from '../hooks/useReveal'
import { GitHubIcon, WindowsIcon } from './BrandIcons'
import { Button } from './ui'

export function Download({ release }: { release: ReleaseInfo }) {
  const ref = useReveal<HTMLDivElement>()
  return (
    <section id="download" className="px-5 sm:px-8 py-20 sm:py-28">
      <div ref={ref} className="reveal mx-auto max-w-4xl rounded-3xl border border-line-strong bg-surface px-6 py-14 sm:px-14 text-center shadow-[0_24px_70px_rgb(0_4_20/0.55)]">
        <img src="./brand/icon.png" alt="" className="mx-auto size-16 rounded-2xl" width={64} height={64} loading="lazy" />
        <h2 className="mt-6 text-3xl sm:text-4xl font-bold tracking-tight text-balance">Better Code Starts With Better Reviews.</h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-ink-2">
          Download PulseReview and bring AI-powered code review into your development workflow.
        </p>
        <div className="mt-9 flex flex-col sm:flex-row items-center justify-center gap-3">
          <Button href={release.downloadUrl} className="w-full sm:w-auto h-12 px-6"><WindowsIcon /> Download for Windows</Button>
          <Button href={REPO_URL} variant="secondary" external className="w-full sm:w-auto h-12 px-6"><GitHubIcon /> View on GitHub</Button>
        </div>
        <p className="mt-5 text-sm text-muted">
          {prettyVersion(release.tag)}{release.sizeMB ? ` · ${release.sizeMB} MB` : ''} · Windows 10/11 (64-bit) ·{' '}
          <a className="text-accent-2 hover:underline" href={release.url} target="_blank" rel="noopener noreferrer">release notes & checksum</a>
        </p>
      </div>
    </section>
  )
}

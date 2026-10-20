import { ExternalLink } from 'lucide-react'
import { DEVELOPER, PRODUCT, REPO, REPO_URL } from '../config'
import { prettyVersion, type ReleaseInfo } from '../hooks/useRelease'
import { Section } from './ui'

export function Details({ release, macos }: { release: ReleaseInfo; macos: ReleaseInfo | null }) {
  const date = release.publishedAt ? new Date(release.publishedAt).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : null
  const rows: [string, React.ReactNode][] = [
    ['Product', PRODUCT],
    ['Developer', DEVELOPER],
    ['Windows release', <>{prettyVersion(release.tag)}{release.prerelease && <span className="ml-2 rounded-md border border-warn/50 px-2 py-0.5 text-xs font-semibold text-warn">pre-release</span>}</>],
    ['macOS release', macos ? <a href={macos.url} className="text-accent-2 hover:underline">{macos.tag} · Apple Silicon · macOS 14+</a> : 'Apple Silicon beta in preparation'],
    ['Released', date ?? 'See the releases page'],
    ['Download', release.sizeMB ? `PulseReview.exe · ${release.sizeMB} MB · single file` : 'PulseReview.exe · single file'],
    ['Operating system', 'Windows 10 / 11'],
    ['Architecture', <span style={{ fontFeatureSettings: '"calt" 0' }}>x64 (64-bit)</span>],
    ['Requirements', 'Microsoft Edge WebView2 runtime for the native window (otherwise opens in your browser). Optional: Docker Desktop for the test sandbox, Ollama for local models.'],
    ['License', <a href={`${REPO_URL}/blob/main/LICENSE`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-accent-2 hover:underline">PulseReview Beta License · © ZeroPulse<ExternalLink className="size-3.5" /></a>],
    ['Repository', <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-accent-2 hover:underline">{REPO}<ExternalLink className="size-3.5" /></a>],
    ['Release notes', <a href={release.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-accent-2 hover:underline">{release.tag} on GitHub<ExternalLink className="size-3.5" /></a>],
  ]
  return (
    <Section id="details" eyebrow="Product details" title="Built for your desktop by ZeroPulse.">
      <div className="overflow-hidden rounded-2xl border border-line bg-surface/70">
        <dl className="divide-y divide-line">
          {rows.map(([k, v]) => (
            <div key={k} className="grid gap-1 px-6 py-4 sm:grid-cols-[220px_1fr] sm:gap-6">
              <dt className="text-sm font-medium text-muted">{k}</dt>
              <dd className="text-[15px] text-ink">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      {!release.live && <p className="mt-3 text-xs text-muted">Release details could not be loaded from GitHub right now; showing the published {release.tag} defaults.</p>}
    </Section>
  )
}

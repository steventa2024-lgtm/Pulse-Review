import { ISSUES_URL, README_URL, RELEASES_URL, REPO_URL } from '../config'

export function Footer({ downloadUrl }: { downloadUrl: string }) {
  const cols: [string, [string, string, boolean][]][] = [
    ['Product', [['Features', '#features', false], ['Screenshots', '#screenshots', false], ['Download', downloadUrl, false]]],
    ['Developers', [['GitHub', REPO_URL, true], ['Releases', RELEASES_URL, true], ['Documentation', README_URL, true], ['Report an issue', ISSUES_URL, true]]],
    ['Legal', [['License: PulseReview Beta License', `${REPO_URL}/blob/main/LICENSE`, true], ['Privacy: data stays on your PC', '#faq', false]]],
  ]
  return (
    <footer className="border-t border-line px-5 sm:px-8 py-14">
      <div className="mx-auto grid max-w-6xl gap-10 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <a href="#top" className="flex items-center gap-2.5">
            <img src="./brand/icon.png" alt="" className="size-8 rounded-lg" width={32} height={32} loading="lazy" />
            <span className="font-semibold">Pulse<span className="text-accent-2">Review</span></span>
          </a>
          <p className="mt-4 max-w-xs text-sm text-muted">AI-assisted pull-request reviews on your desktop. You approve everything that gets posted.</p>
        </div>
        {cols.map(([title, links]) => (
          <nav key={title} aria-label={title}>
            <h3 className="text-sm font-semibold">{title}</h3>
            <ul className="mt-4 space-y-2.5">
              {links.map(([label, href, ext]) => (
                <li key={label}><a href={href} className="text-sm text-muted hover:text-ink transition-colors" {...(ext ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>{label}</a></li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="mx-auto mt-12 max-w-6xl border-t border-line pt-6 text-sm text-muted">© {new Date().getFullYear()} ZeroPulse. All rights reserved. PulseReview is developed and licensed by ZeroPulse.</div>
    </footer>
  )
}

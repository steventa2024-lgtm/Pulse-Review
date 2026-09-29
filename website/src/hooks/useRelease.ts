import { useEffect, useState } from 'react'
import { FALLBACK_DOWNLOAD_URL, FALLBACK_TAG, REPO, RELEASES_URL } from '../config'

export type ReleaseInfo = {
  tag: string
  name: string
  url: string // release page
  downloadUrl: string // direct .exe (or the releases page if no asset was found)
  sizeMB: number | null
  publishedAt: string | null
  prerelease: boolean
  live: boolean // true when read from the GitHub API, false when using the built-in fallback
}

const FALLBACK: ReleaseInfo = {
  tag: FALLBACK_TAG, name: `${FALLBACK_TAG}`, url: `${RELEASES_URL}/tag/${FALLBACK_TAG}`, downloadUrl: FALLBACK_DOWNLOAD_URL,
  sizeMB: null, publishedAt: null, prerelease: true, live: false,
}

type ApiAsset = { name: string; size: number; browser_download_url: string }
type ApiRelease = { tag_name: string; name: string | null; html_url: string; draft: boolean; prerelease: boolean; published_at: string | null; assets: ApiAsset[] }

/** Latest published release (pre-releases included) and its Windows executable, straight from GitHub Releases. */
export function useRelease(): ReleaseInfo {
  const [info, setInfo] = useState<ReleaseInfo>(FALLBACK)
  useEffect(() => {
    const ctrl = new AbortController()
    fetch(`https://api.github.com/repos/${REPO}/releases?per_page=10`, { signal: ctrl.signal, headers: { Accept: 'application/vnd.github+json' } })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((list: ApiRelease[]) => {
        const rel = list.find(r => !r.draft && r.assets.some(a => a.name.toLowerCase().endsWith('.exe')))
        if (!rel) return
        const exe = rel.assets.find(a => a.name.toLowerCase().endsWith('.exe'))!
        setInfo({
          tag: rel.tag_name, name: rel.name || rel.tag_name, url: rel.html_url, downloadUrl: exe.browser_download_url,
          sizeMB: Math.round((exe.size / 1024 / 1024) * 10) / 10, publishedAt: rel.published_at, prerelease: rel.prerelease, live: true,
        })
      })
      .catch(() => { /* keep the fallback */ })
    return () => ctrl.abort()
  }, [])
  return info
}

export function prettyVersion(tag: string): string {
  const m = tag.match(/^v?(\d+\.\d+\.\d+)[-.]?(alpha|beta|rc)?(\d*)$/i)
  if (!m) return tag
  return m[2] ? `${m[1]} ${m[2].toLowerCase()}${m[3] ? ' ' + m[3] : ''}` : m[1]
}

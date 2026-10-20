import { useEffect, useState } from 'react'
import { FALLBACK_DOWNLOAD_URL, FALLBACK_TAG, REPO, RELEASES_URL } from '../config'
import { selectReleases, type ApiRelease, type PlatformReleases, type ReleaseInfo } from './releaseSelection'
export type { ReleaseInfo } from './releaseSelection'

const FALLBACK: ReleaseInfo = {
  tag: FALLBACK_TAG, name: FALLBACK_TAG, url: `${RELEASES_URL}/tag/${FALLBACK_TAG}`, downloadUrl: FALLBACK_DOWNLOAD_URL,
  sizeMB: null, publishedAt: null, prerelease: true, live: false,
}

/** Independent published releases; preserve the Windows URL if GitHub is offline. */
export function useRelease(): PlatformReleases {
  const [info, setInfo] = useState<PlatformReleases>({ windows: FALLBACK, macos: null })
  useEffect(() => {
    const ctrl = new AbortController()
    async function load() {
      const releases: ApiRelease[] = []
      for (let page = 1; page <= 10; page++) {
        const response = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=100&page=${page}`,
          { signal: ctrl.signal, headers: { Accept: 'application/vnd.github+json' } })
        if (!response.ok) throw new Error(String(response.status))
        const batch: ApiRelease[] = await response.json()
        if (!Array.isArray(batch)) throw new Error('Invalid release response')
        releases.push(...batch)
        if (batch.length < 100) break
      }
      if (!ctrl.signal.aborted) setInfo(selectReleases(releases, FALLBACK))
    }
    load().catch(() => { /* Windows fallback stays usable; Mac stays unavailable. */ })
    return () => ctrl.abort()
  }, [])
  return info
}

export function prettyVersion(tag: string): string {
  const m = tag.match(/^v?(\d+\.\d+\.\d+)[-.]?(alpha|beta|rc)?(\d*)$/i)
  if (!m) return tag
  return m[2] ? `${m[1]} ${m[2].toLowerCase()}${m[3] ? ' ' + m[3] : ''}` : m[1]
}

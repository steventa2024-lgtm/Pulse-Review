import { REPO_URL } from '../config.ts'

export type ReleaseInfo = {
  tag: string; name: string; url: string; downloadUrl: string
  sizeMB: number | null; publishedAt: string | null; prerelease: boolean; live: boolean
}
export type ApiAsset = { name: string; size: number; browser_download_url: string; digest?: string | null }
export type ApiRelease = {
  tag_name: string; name: string | null; html_url: string; draft: boolean
  prerelease: boolean; published_at: string | null; body?: string | null; assets: ApiAsset[]
}
export type PlatformReleases = { windows: ReleaseInfo; macos: ReleaseInfo | null }

function asset(release: ApiRelease, name: string): ApiAsset | undefined {
  return release.assets.find(a => a.name === name && a.size > 0 &&
    a.browser_download_url === `${REPO_URL}/releases/download/${release.tag_name}/${name}`)
}

function info(release: ApiRelease, file: ApiAsset): ReleaseInfo {
  return {
    tag: release.tag_name, name: release.name || release.tag_name, url: release.html_url,
    downloadUrl: file.browser_download_url, sizeMB: Math.round(file.size / 1024 / 1024 * 10) / 10,
    publishedAt: release.published_at, prerelease: release.prerelease, live: true,
  }
}

/** Maintainers add the verification marker only after tests and publication approval.
 * A CI artifact or draft release is insufficient to enable a Mac download.
 */
export function selectReleases(list: ApiRelease[], fallback: ReleaseInfo): PlatformReleases {
  const published = list.filter(r => !r.draft && r.published_at && Array.isArray(r.assets))
    .sort((a, b) => Date.parse(b.published_at!) - Date.parse(a.published_at!))
  let windows: ReleaseInfo | undefined
  let macos: ReleaseInfo | null = null
  for (const release of published) {
    const exe = asset(release, 'PulseReview.exe')
    if (!windows && !release.tag_name.startsWith('macos-') && exe && asset(release, 'PulseReview.exe.sha256')) {
      windows = info(release, exe)
    }
    const dmg = asset(release, 'PulseReview-macOS-arm64.dmg')
    if (!macos && /^macos-v\d+\.\d+\.\d+-beta\.\d+$/.test(release.tag_name) && dmg &&
        /^sha256:[a-f0-9]{64}$/.test(dmg.digest || '') &&
        asset(release, 'PulseReview-macOS-arm64.dmg.sha256') &&
        /^PulseReview-Verified: macos-arm64\s*$/m.test(release.body || '') &&
        /^Source-Commit: [a-f0-9]{40}\s*$/m.test(release.body || '')) {
      macos = info(release, dmg)
    }
  }
  return { windows: windows || fallback, macos }
}

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { selectReleases, type ApiRelease, type ReleaseInfo } from '../src/hooks/releaseSelection.ts'
import { REPO_URL } from '../src/config.ts'

const fallback: ReleaseInfo = {
  tag: 'v0.1.2beta', name: 'Windows', url: `${REPO_URL}/releases/tag/v0.1.2beta`,
  downloadUrl: `${REPO_URL}/releases/download/v0.1.2beta/PulseReview.exe`,
  sizeMB: null, publishedAt: null, prerelease: true, live: false,
}
function release(tag: string, file: string, date = '2026-10-20T00:00:00Z'): ApiRelease {
  return {
    tag_name: tag, name: tag, html_url: `${REPO_URL}/releases/tag/${tag}`, draft: false,
    prerelease: true, published_at: date,
    body: `PulseReview-Verified: macos-arm64\nSource-Commit: ${'a'.repeat(40)}`,
    assets: [file, `${file}.sha256`].map(name => ({ name, size: 100,
      digest: `sha256:${'b'.repeat(64)}`, browser_download_url: `${REPO_URL}/releases/download/${tag}/${name}` })),
  }
}
const windows = release('v0.1.2beta', 'PulseReview.exe', '2026-10-01T00:00:00Z')
const mac = release('macos-v0.1.3-beta.1', 'PulseReview-macOS-arm64.dmg')

test('Mac beta cannot replace Windows; each platform has its own version', () => {
  const selected = selectReleases([mac, windows], fallback)
  assert.equal(selected.windows.tag, windows.tag_name)
  assert.equal(selected.macos?.tag, mac.tag_name)
  assert.ok(selected.windows.downloadUrl.endsWith('.exe'))
  assert.ok(selected.macos?.downloadUrl.endsWith('.dmg'))
})
test('No published Mac asset means no Mac link, including API fallback', () => {
  assert.equal(selectReleases([windows], fallback).macos, null)
  assert.deepEqual(selectReleases([], fallback), { windows: fallback, macos: null })
})
test('Draft, unverified, empty, renamed or incomplete Mac releases stay unavailable', () => {
  for (const mutate of [
    (r: ApiRelease) => { r.draft = true },
    (r: ApiRelease) => { r.body = '' },
    (r: ApiRelease) => { r.body = 'PulseReview-Verified: macos-arm64' },
    (r: ApiRelease) => { r.assets.pop() },
    (r: ApiRelease) => { r.assets[0].size = 0 },
    (r: ApiRelease) => { r.assets[0].digest = null },
    (r: ApiRelease) => { r.assets[0].name = 'PulseReview.exe' },
    (r: ApiRelease) => { r.assets[0].browser_download_url = 'https://example.com/malicious.dmg' },
  ]) {
    const copy = structuredClone(mac)
    mutate(copy)
    assert.equal(selectReleases([copy, windows], fallback).macos, null)
  }
})
test('Select latest published date independently of API order', () => {
  const newer = release('v0.1.4beta', 'PulseReview.exe', '2026-10-21T00:00:00Z')
  assert.equal(selectReleases([windows, mac, newer], fallback).windows.tag, newer.tag_name)
})
test('Wrong OS assets never become a download', () => {
  assert.equal(selectReleases([release('macos-v0.1.3-beta.1', 'PulseReview.exe')], fallback).macos, null)
  assert.equal(selectReleases([release('v0.1.4beta', 'PulseReview-macOS-arm64.dmg')], fallback).windows, fallback)
})

import { useCallback, useState } from 'react'
import { Details } from './components/Details'
import { Download } from './components/Download'
import { Faq } from './components/Faq'
import { Features } from './components/Features'
import { Footer } from './components/Footer'
import { Hero } from './components/Hero'
import { HowItWorks } from './components/HowItWorks'
import { Lightbox } from './components/Lightbox'
import { Models } from './components/Models'
import { Nav } from './components/Nav'
import { Showcase } from './components/Showcase'
import { useRelease } from './hooks/useRelease'

export default function App() {
  const release = useRelease()
  const [zoom, setZoom] = useState<string | null>(null)
  const close = useCallback(() => setZoom(null), [])
  return (
    <>
      <a href="#features" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[200] focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2">Skip to content</a>
      <Nav downloadUrl={release.downloadUrl} />
      <main>
        <Hero release={release} onZoom={setZoom} />
        <Features />
        <HowItWorks />
        <Showcase onZoom={setZoom} />
        <Models />
        <Details release={release} />
        <Faq />
        <Download release={release} />
      </main>
      <Footer downloadUrl={release.downloadUrl} />
      <Lightbox file={zoom} onClose={close} />
    </>
  )
}

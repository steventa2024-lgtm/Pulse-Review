import { ChevronDown } from 'lucide-react'
import { Section } from './ui'

const FAQ: [string, string][] = [
  ['Is it free?', 'The app is free to download. Hosted reviews use models that OpenRouter lists as free, which need a free OpenRouter account and API key and are rate-limited. Local reviews through Ollama need no key but use your own hardware.'],
  ['Does it post anything to GitHub automatically?', 'No. Reviews are generated locally. Publishing is a separate step: you preview and can edit the text, type the repository and PR number to confirm, and it is posted as a plain COMMENT review — never an approval or change request.'],
  ['Does it run the code from my pull requests?', 'Only if you ask it to run a generated test, and then only inside an isolated Docker container with networking disabled, no access to your files or credentials, and CPU/memory/time limits. Nothing from the pull request runs directly on your PC.'],
  ['Where is my data stored?', 'Windows keeps settings, SQLite review history and logs in %APPDATA%\\ZeroPulse\\PRReviewAgent, with credentials encrypted using Windows DPAPI. The Apple Silicon macOS beta uses ~/Library/Application Support/ZeroPulse/PulseReview and macOS Keychain for GitHub tokens and API keys.'],
  ['What should I expect from the macOS beta?', 'The Apple Silicon download appears only after a verified release is published. It requires macOS 14 or later. The free beta is ad-hoc signed and not notarized, so Gatekeeper may block its first launch. Read the Mac release installation instructions; do not disable system-wide security protections.'],
  ['Which GitHub permissions does it need?', 'Read access to repository contents and pull requests. Publishing reviews additionally needs pull-request write access. You can sign in with GitHub or use a fine-grained personal access token.'],
  ['Windows warns me when I open the .exe. Why?', 'This beta is not code-signed yet, so SmartScreen may show a warning on first launch (More info → Run anyway). A SHA-256 checksum is published next to every download.'],
  ['Can I review private repositories?', 'Yes, if your GitHub account can access them. With OpenRouter the app asks for your explicit consent before private code is sent; with Ollama the code never leaves your PC.'],
]

export function Faq() {
  return (
    <Section id="faq" eyebrow="FAQ" title="Questions, answered.">
      <div className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface/70">
        {FAQ.map(([q, a]) => (
          <details key={q} className="group px-6 py-1 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-6 py-4 text-[16px] font-medium">
              {q}<ChevronDown className="size-5 shrink-0 text-muted transition-transform group-open:rotate-180" />
            </summary>
            <p className="pb-5 text-[15px] leading-relaxed text-ink-2">{a}</p>
          </details>
        ))}
      </div>
    </Section>
  )
}

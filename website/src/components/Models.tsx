import { Cloud, Cpu, KeyRound, Lock, RefreshCw, ShieldCheck } from 'lucide-react'
import { Card, Section } from './ui'

// Mirrors core/providers (OpenRouter free-only guard, Ollama) and core/providers/ollama.py SUGGESTED_MODELS.
const OLLAMA_MODELS = [
  ['qwen2.5-coder:7b', '~4.7 GB', true], ['llama3.1:8b', '~4.9 GB', true], ['qwen3:8b', '~5.2 GB', true],
  ['deepseek-coder-v2:16b', '~8.9 GB', false], ['qwen2.5-coder:14b', '~9 GB', false], ['qwen3-coder:30b', '~19 GB', false],
] as const

export function Models() {
  return (
    <Section id="open-source" eyebrow="Open-weight AI" title="Your Workflow. Your Models."
             intro="Reviews run on open-weight models — either free hosted models through OpenRouter or models running on your own PC with Ollama. The review logic is identical for both.">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5 sm:p-7">
          <div className="flex items-center gap-3">
            <span className="grid size-11 place-items-center rounded-xl border border-line-strong bg-accent-soft text-accent-2"><Cloud className="size-5" /></span>
            <div>
              <h3 className="text-lg font-semibold">OpenRouter — free hosted models</h3>
              <p className="text-sm text-muted">Cloud inference · no GPU needed</p>
            </div>
          </div>
          <ul className="mt-6 space-y-3 text-[15px] text-ink-2">
            <li className="flex gap-3"><KeyRound className="mt-0.5 size-4 shrink-0 text-accent-2" />Requires a free OpenRouter account and API key, stored encrypted on your PC.</li>
            <li className="flex gap-3"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent-2" />Only models OpenRouter currently lists at $0 are offered, and every call re-checks that — paid models are never used.</li>
            <li className="flex gap-3"><RefreshCw className="mt-0.5 size-4 shrink-0 text-accent-2" />Free models are rate-limited and change over time; the list is loaded live and code-focused models are ranked first.</li>
            <li className="flex gap-3"><Lock className="mt-0.5 size-4 shrink-0 text-accent-2" />Code leaves your PC: secret-like values are redacted, and private repositories need your explicit consent.</li>
          </ul>
        </Card>
        <Card className="p-5 sm:p-7">
          <div className="flex items-center gap-3">
            <span className="grid size-11 place-items-center rounded-xl border border-line-strong bg-accent-soft text-accent-2"><Cpu className="size-5" /></span>
            <div>
              <h3 className="text-lg font-semibold">Ollama — local models</h3>
              <p className="text-sm text-muted">Runs on your hardware · no API key</p>
            </div>
          </div>
          <ul className="mt-6 space-y-3 text-[15px] text-ink-2">
            <li className="flex gap-3"><Lock className="mt-0.5 size-4 shrink-0 text-accent-2" />Code and prompts stay on your computer. Requires Ollama installed and running.</li>
            <li className="flex gap-3"><RefreshCw className="mt-0.5 size-4 shrink-0 text-accent-2" />Pick any installed model, or download suggested ones from inside the app — only when you click Download.</li>
          </ul>
          <div className="mt-6 overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-sm">
              <caption className="sr-only">Suggested Ollama models</caption>
              <thead className="bg-surface-2/70 text-left text-xs uppercase tracking-wider text-muted">
                <tr><th className="px-4 py-2.5 font-semibold">Suggested model</th><th className="px-4 py-2.5 font-semibold">Download</th><th className="px-4 py-2.5 font-semibold">8 GB GPU</th></tr>
              </thead>
              <tbody>
                {OLLAMA_MODELS.map(([name, size, fits]) => (
                  <tr key={name} className="border-t border-line">
                    <td className="px-4 py-2.5 font-mono text-[13px] text-ink whitespace-nowrap">{name}</td>
                    <td className="px-4 py-2.5 text-ink-2">{size}</td>
                    <td className="px-4 py-2.5">{fits
                      ? <span className="rounded-md border border-ok/50 px-2 py-0.5 text-xs font-semibold text-ok">fits</span>
                      : <span className="text-xs text-muted">CPU + GPU</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </Section>
  )
}

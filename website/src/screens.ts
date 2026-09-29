export type Screen = { id: string; label: string; file: string; title: string; text: string }

/** Real screenshots captured from the running app (website/scripts/capture_screenshots.py). */
export const SCREENS: Screen[] = [
  { id: 'dashboard', label: 'Dashboard', file: 'dashboard', title: 'Everything at a glance',
    text: 'Totals for reviews, findings, generated tests and publications, plus your most recent pull-request reviews. The top bar shows the live GitHub, model and sandbox status.' },
  { id: 'new-review', label: 'New Review', file: 'new-review', title: 'Pick a repository and pull request',
    text: 'Choose one of your repositories and an open pull request, select a free cloud model or a local Ollama model, set the depth and start. Progress shows the real pipeline stages.' },
  { id: 'results', label: 'Review Results', file: 'review-results', title: 'Findings you can verify',
    text: 'Severity, category and a verification label for every finding, the exact changed lines, evidence and a suggested fix, plus the proposed test file and publishing controls.' },
  { id: 'code', label: 'Code Reviewer', file: 'code-reviewer', title: 'Audit a whole repository',
    text: 'Scan a repository, folder or single file for security issues, leaked secrets and API keys, bugs, performance and maintainability — with an overall score and a per-area breakdown.' },
  { id: 'history', label: 'Review History', file: 'review-history', title: 'Every review, stored locally',
    text: 'Reviews are kept in a local SQLite database on your PC. Filter, reopen or delete them at any time.' },
  { id: 'watched', label: 'Watched Repositories', file: 'watched-repositories', title: 'Keep an eye on open PRs',
    text: 'Add repositories and see new or updated pull requests, checked by polling with conditional requests. Start a review with one click.' },
  { id: 'testlab', label: 'Test Lab', file: 'test-lab', title: 'Generated tests in one place',
    text: 'All generated test files across your reviews. Run them in an isolated Docker sandbox with no network access; results are only reported as passed after a real run.' },
  { id: 'settings', label: 'Settings', file: 'settings', title: 'Your models, your setup',
    text: 'Switch between OpenRouter free models and local Ollama models without restarting, download more Ollama models, and configure GitHub sign-in and review defaults.' },
]

export const shot = (file: string) => `./screenshots/${file}.webp`

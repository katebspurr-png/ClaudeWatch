# ClaudeWatch Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-page static landing page for ClaudeWatch with teal brand identity, and update the in-app dashboard to match.

**Architecture:** The landing page is a self-contained `site/index.html` (HTML + CSS, no framework). The dashboard is generated inline within `claude_monitor.py` as a string — its accent color is swapped from orange (`#D97757`) to teal (`#0D9488`) to match. Both share the same design tokens: teal accent, dark surfaces, system-ui font.

**Tech Stack:** HTML5, CSS (custom properties), no JavaScript framework, Netlify or Vercel for hosting.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `site/index.html` | Full landing page — markup + all styles inline |
| Create | `site/screenshots/` | Directory for app screenshot images |
| Modify | `claude_monitor.py` | Replace all `#D97757` → `#0D9488` (7 occurrences) |
| Modify | `~/.claude_monitor/claude_monitor.py` | Same change, live running copy |

---

## Task 1: Update dashboard accent color

**Files:**
- Modify: `claude_monitor.py` (all 7 `#D97757` occurrences)
- Sync: `~/.claude_monitor/claude_monitor.py`

- [ ] **Step 1: Replace accent color in project copy**

```bash
sed -i '' 's/#D97757/#0D9488/g' "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/claude_monitor.py"
```

- [ ] **Step 2: Verify all 7 occurrences changed**

```bash
grep -n "D97757\|0D9488" "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/claude_monitor.py"
```

Expected: 0 lines with `D97757`, 7 lines with `0D9488`.

- [ ] **Step 3: Sync to live copy**

```bash
cp "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/claude_monitor.py" ~/.claude_monitor/claude_monitor.py
```

- [ ] **Step 4: Restart the app**

```bash
launchctl unload ~/Library/LaunchAgents/com.katespurr.claudewatch.plist
launchctl load ~/Library/LaunchAgents/com.katespurr.claudewatch.plist
```

- [ ] **Step 5: Open the dashboard and verify teal**

Click "View Dashboard" in the ClaudeWatch menu. Usage bars and accent elements should be teal (`#0D9488`), not orange. The logo circle in the header should also be teal.

- [ ] **Step 6: Commit**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add claude_monitor.py
git commit -m "rebrand: update dashboard accent from orange to teal (#0D9488)"
```

---

## Task 2: Create site directory and screenshot placeholders

**Files:**
- Create: `site/` directory
- Create: `site/screenshots/` directory

- [ ] **Step 1: Create directories**

```bash
mkdir -p "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/screenshots"
```

- [ ] **Step 2: Add your screenshots**

Copy two screenshots into `site/screenshots/`:

- `site/screenshots/menubar.png` — the menu bar showing the ClaudeWatch title string (e.g., `◈ 34% | 64%`)
- `site/screenshots/dropdown.png` — the full dropdown open, showing session %, weekly %, reset time, model guide etc.

Take these via macOS screenshot (`⌘⇧4` then click the menu bar icon). Crop tightly. PNG is fine — no need to convert to WebP now.

- [ ] **Step 3: Verify files exist**

```bash
ls "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/screenshots/"
```

Expected: `menubar.png` and `dropdown.png`

---

## Task 3: Landing page — HTML skeleton + CSS foundation

**Files:**
- Create: `site/index.html`

- [ ] **Step 1: Create index.html with full CSS and empty sections**

Create `site/index.html` with this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ClaudeWatch — Know your Claude limits before they know you</title>
  <meta name="description" content="ClaudeWatch puts your Claude session and weekly usage right in the menu bar. Always visible, always current. Free on GitHub or pay what you can.">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --accent:     #0D9488;
      --accent-hover: #0F766E;
      --bg:         #0a0a0f;
      --surface:    #1c1c1e;
      --border:     #2d2d2d;
      --text:       #f5f5f5;
      --muted:      #9ca3af;
      --radius:     12px;
      --font:       -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    body {
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }

    /* ── Layout ── */
    .container {
      max-width: 860px;
      margin: 0 auto;
      padding: 0 1.5rem;
    }

    section {
      padding: 5rem 0;
    }

    /* ── Typography ── */
    h1 {
      font-size: clamp(2rem, 5vw, 3.25rem);
      font-weight: 800;
      line-height: 1.1;
      letter-spacing: -0.02em;
    }

    h2 {
      font-size: clamp(1.4rem, 3vw, 2rem);
      font-weight: 700;
      line-height: 1.2;
      letter-spacing: -0.01em;
    }

    h3 {
      font-size: 1rem;
      font-weight: 600;
      color: var(--text);
    }

    p {
      color: var(--muted);
      font-size: 1.05rem;
      line-height: 1.7;
    }

    /* ── Buttons ── */
    .btn-primary {
      display: inline-block;
      background: var(--accent);
      color: #fff;
      font-family: var(--font);
      font-size: 0.95rem;
      font-weight: 600;
      padding: 0.75rem 1.5rem;
      border-radius: 8px;
      text-decoration: none;
      transition: background 0.15s;
    }
    .btn-primary:hover { background: var(--accent-hover); }

    .btn-ghost {
      display: inline-block;
      color: var(--muted);
      font-family: var(--font);
      font-size: 0.9rem;
      font-weight: 500;
      padding: 0.75rem 0;
      text-decoration: none;
      transition: color 0.15s;
    }
    .btn-ghost:hover { color: var(--text); }

    /* ── Cards ── */
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1.5rem;
    }

    /* ── Screenshot images ── */
    .screenshot {
      border-radius: var(--radius);
      border: 1px solid var(--border);
      max-width: 100%;
      height: auto;
      display: block;
    }

    /* ── Divider ── */
    hr {
      border: none;
      border-top: 1px solid var(--border);
    }

    /* ── Nav ── */
    nav {
      padding: 1.5rem 0;
      border-bottom: 1px solid var(--border);
    }
    nav .container {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .nav-brand {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-weight: 700;
      font-size: 1rem;
      color: var(--text);
      text-decoration: none;
    }
    .nav-brand .dot {
      width: 10px;
      height: 10px;
      background: var(--accent);
      border-radius: 50%;
    }
    .nav-links {
      display: flex;
      gap: 1.5rem;
      list-style: none;
    }
    .nav-links a {
      color: var(--muted);
      text-decoration: none;
      font-size: 0.9rem;
      transition: color 0.15s;
    }
    .nav-links a:hover { color: var(--text); }

    /* ── Responsive ── */
    @media (max-width: 640px) {
      section { padding: 3rem 0; }
      .nav-links { display: none; }
    }
  </style>
</head>
<body>

  <!-- NAV -->
  <nav>
    <div class="container">
      <a href="/" class="nav-brand">
        <span class="dot"></span>
        ClaudeWatch
      </a>
      <ul class="nav-links">
        <li><a href="https://github.com/katebspurr-png/ClaudeWatch">GitHub</a></li>
      </ul>
    </div>
  </nav>

  <!-- HERO (Task 4) -->
  <!-- PAIN (Task 5) -->
  <!-- SOLUTION (Task 6) -->
  <!-- HOW IT WORKS (Task 7) -->
  <!-- CTA (Task 8) -->

  <!-- FOOTER -->
  <footer style="border-top:1px solid var(--border);padding:2rem 0;text-align:center">
    <p style="font-size:0.8rem">
      ClaudeWatch is not affiliated with Anthropic. &nbsp;·&nbsp;
      <a href="https://github.com/katebspurr-png/ClaudeWatch" style="color:var(--accent);text-decoration:none">GitHub</a>
    </p>
  </footer>

</body>
</html>
```

- [ ] **Step 2: Open in browser and verify**

```bash
open "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/index.html"
```

Expected: dark page with teal dot in nav, "ClaudeWatch" brand name, empty body, footer with disclaimer. No layout errors.

- [ ] **Step 3: Commit**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add site/
git commit -m "feat: add landing page skeleton with CSS foundation"
```

---

## Task 4: Hero section

**Files:**
- Modify: `site/index.html` (replace `<!-- HERO (Task 4) -->` comment)

- [ ] **Step 1: Replace the hero comment with this markup**

Find `<!-- HERO (Task 4) -->` and replace with:

```html
  <!-- HERO -->
  <section class="hero">
    <div class="container">
      <div class="hero-inner">
        <div class="hero-copy">
          <p class="eyebrow">ClaudeWatch for Mac</p>
          <h1>You're flying blind on Claude limits.</h1>
          <p class="hero-sub">Claude cuts you off mid-project and you never see it coming. ClaudeWatch puts your session and weekly usage right in the menu bar — always visible, always current.</p>
          <div class="hero-actions">
            <a href="https://claudewatch.gumroad.com/l/download" class="btn-primary">Download · pay what you can</a>
            <a href="https://github.com/katebspurr-png/ClaudeWatch" class="btn-ghost">Free on GitHub →</a>
          </div>
        </div>
        <div class="hero-image">
          <img src="screenshots/menubar.png" alt="ClaudeWatch showing 34% | 64% in the Mac menu bar" class="screenshot">
        </div>
      </div>
    </div>
  </section>
```

Also add these styles inside the `<style>` block, before the closing `</style>`:

```css
    /* ── Hero ── */
    .hero { padding: 6rem 0 4rem; }
    .hero-inner {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 4rem;
      align-items: center;
    }
    .eyebrow {
      font-size: 0.75rem;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 1.25rem;
    }
    .hero h1 { margin-bottom: 1.25rem; }
    .hero-sub {
      font-size: 1.15rem;
      margin-bottom: 2rem;
    }
    .hero-actions {
      display: flex;
      gap: 1.25rem;
      align-items: center;
      flex-wrap: wrap;
    }
    @media (max-width: 720px) {
      .hero-inner {
        grid-template-columns: 1fr;
        gap: 2.5rem;
      }
      .hero { padding: 3rem 0 2rem; }
    }
```

- [ ] **Step 2: Update the Gumroad URL**

Replace `https://claudewatch.gumroad.com/l/download` with your actual Gumroad product URL once created. For now leave the placeholder — it won't break anything.

- [ ] **Step 3: Open in browser and verify**

```bash
open "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/index.html"
```

Expected: two-column hero on desktop (copy left, screenshot right), stacked on mobile. Teal "Download" button. "Free on GitHub →" ghost link. If `menubar.png` doesn't exist yet, the image area will be empty — that's fine.

- [ ] **Step 4: Commit**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add site/index.html
git commit -m "feat: add hero section to landing page"
```

---

## Task 5: Pain section

**Files:**
- Modify: `site/index.html` (replace `<!-- PAIN (Task 5) -->` comment)

- [ ] **Step 1: Replace the pain comment with this markup**

Find `<!-- PAIN (Task 5) -->` and replace with:

```html
  <!-- PAIN -->
  <section class="pain">
    <div class="container">
      <div class="pain-grid">
        <div class="card pain-card">
          <div class="pain-icon">⏱</div>
          <h3>You're deep in a project.</h3>
          <p>Claude slows down. You had no idea you were close to the limit.</p>
        </div>
        <div class="card pain-card">
          <div class="pain-icon">🔍</div>
          <h3>You go looking for your usage.</h3>
          <p>It's buried in settings, three clicks deep. By then you've already lost your flow.</p>
        </div>
        <div class="card pain-card">
          <div class="pain-icon">🛑</div>
          <h3>You hit the limit.</h3>
          <p>The work stops. You wait. Again.</p>
        </div>
      </div>
    </div>
  </section>
```

Also add these styles inside the `<style>` block:

```css
    /* ── Pain ── */
    .pain { padding: 0 0 5rem; }
    .pain-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1rem;
    }
    .pain-card { text-align: center; padding: 2rem 1.5rem; }
    .pain-icon {
      font-size: 1.75rem;
      margin-bottom: 1rem;
    }
    .pain-card h3 {
      margin-bottom: 0.5rem;
      font-size: 1rem;
    }
    .pain-card p { font-size: 0.9rem; }
    @media (max-width: 640px) {
      .pain-grid { grid-template-columns: 1fr; }
    }
```

- [ ] **Step 2: Open in browser and verify**

```bash
open "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/index.html"
```

Expected: three cards in a row (stacked on mobile), each with emoji icon, bold heading, muted body text. Dark surface cards with subtle border.

- [ ] **Step 3: Commit**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add site/index.html
git commit -m "feat: add pain section to landing page"
```

---

## Task 6: Solution section

**Files:**
- Modify: `site/index.html` (replace `<!-- SOLUTION (Task 6) -->` comment)

- [ ] **Step 1: Replace the solution comment with this markup**

Find `<!-- SOLUTION (Task 6) -->` and replace with:

```html
  <!-- SOLUTION -->
  <section class="solution">
    <div class="container">
      <div class="solution-inner">
        <div class="solution-image">
          <img src="screenshots/dropdown.png" alt="ClaudeWatch dropdown showing session usage, weekly usage, and reset time" class="screenshot">
        </div>
        <div class="solution-copy">
          <p class="eyebrow">The fix</p>
          <h2>Now you always know.</h2>
          <p>ClaudeWatch sits in your menu bar and polls your usage every few minutes. Session usage. Weekly usage. Time until reset. All there, at a glance. No surprises.</p>
          <ul class="feature-list">
            <li>5-hour session usage %</li>
            <li>7-day weekly usage %</li>
            <li>Time until session resets</li>
            <li>Model guide — what to use when</li>
            <li>Usage history &amp; analytics dashboard</li>
          </ul>
        </div>
      </div>
    </div>
  </section>
```

Also add these styles inside the `<style>` block:

```css
    /* ── Solution ── */
    .solution-inner {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 4rem;
      align-items: center;
    }
    .solution-copy h2 { margin-bottom: 1rem; }
    .solution-copy p  { margin-bottom: 1.5rem; }
    .feature-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 0.6rem;
    }
    .feature-list li {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      font-size: 0.95rem;
      color: var(--text);
    }
    .feature-list li::before {
      content: '';
      width: 6px;
      height: 6px;
      background: var(--accent);
      border-radius: 50%;
      flex-shrink: 0;
    }
    @media (max-width: 720px) {
      .solution-inner {
        grid-template-columns: 1fr;
        gap: 2rem;
      }
      .solution-image { order: -1; }
    }
```

- [ ] **Step 2: Open in browser and verify**

```bash
open "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/index.html"
```

Expected: two-column layout — screenshot left, copy right. Feature list with teal bullet dots. "The fix" eyebrow in teal.

- [ ] **Step 3: Commit**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add site/index.html
git commit -m "feat: add solution section to landing page"
```

---

## Task 7: How It Works section

**Files:**
- Modify: `site/index.html` (replace `<!-- HOW IT WORKS (Task 7) -->` comment)

- [ ] **Step 1: Replace the how-it-works comment with this markup**

Find `<!-- HOW IT WORKS (Task 7) -->` and replace with:

```html
  <!-- HOW IT WORKS -->
  <section class="how">
    <div class="container">
      <h2 style="text-align:center;margin-bottom:3rem">Up and running in 60 seconds.</h2>
      <div class="steps">
        <div class="step">
          <div class="step-num">1</div>
          <h3>Download the DMG</h3>
          <p>Pay what you can on Gumroad, or grab it free from GitHub.</p>
        </div>
        <div class="step-arrow">→</div>
        <div class="step">
          <div class="step-num">2</div>
          <h3>Drag to Applications</h3>
          <p>Open the DMG and drag ClaudeWatch into your Applications folder.</p>
        </div>
        <div class="step-arrow">→</div>
        <div class="step">
          <div class="step-num">3</div>
          <h3>Right-click → Open</h3>
          <p>Required on first launch — the app is unsigned. ClaudeWatch will offer to start at login.</p>
        </div>
      </div>
      <p style="text-align:center;margin-top:2rem;font-size:0.85rem">
        Requires macOS · Claude desktop app installed and signed in
      </p>
    </div>
  </section>
```

Also add these styles inside the `<style>` block:

```css
    /* ── How It Works ── */
    .steps {
      display: flex;
      align-items: flex-start;
      gap: 1rem;
    }
    .step {
      flex: 1;
      text-align: center;
    }
    .step-num {
      width: 2.5rem;
      height: 2.5rem;
      background: var(--surface);
      border: 1px solid var(--accent);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 1rem;
      color: var(--accent);
      margin: 0 auto 1rem;
    }
    .step h3 { margin-bottom: 0.4rem; }
    .step p { font-size: 0.9rem; }
    .step-arrow {
      color: var(--border);
      font-size: 1.5rem;
      padding-top: 0.6rem;
      flex-shrink: 0;
    }
    @media (max-width: 640px) {
      .steps { flex-direction: column; align-items: center; }
      .step-arrow { transform: rotate(90deg); }
    }
```

- [ ] **Step 2: Open in browser and verify**

```bash
open "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/index.html"
```

Expected: three numbered steps in a row connected by arrows, teal-bordered number circles, muted requirement note below.

- [ ] **Step 3: Commit**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add site/index.html
git commit -m "feat: add how-it-works section to landing page"
```

---

## Task 8: Bottom CTA section

**Files:**
- Modify: `site/index.html` (replace `<!-- CTA (Task 8) -->` comment)

- [ ] **Step 1: Replace the CTA comment with this markup**

Find `<!-- CTA (Task 8) -->` and replace with:

```html
  <!-- CTA -->
  <section class="cta-section">
    <div class="container">
      <div class="cta-box">
        <h2>Stop flying blind.</h2>
        <p>Pay what you can — or get it free on GitHub.</p>
        <div class="hero-actions" style="justify-content:center;margin-top:1.5rem">
          <a href="https://claudewatch.gumroad.com/l/download" class="btn-primary">Download · pay what you can</a>
          <a href="https://github.com/katebspurr-png/ClaudeWatch" class="btn-ghost">Free on GitHub →</a>
        </div>
      </div>
    </div>
  </section>
```

Also add these styles inside the `<style>` block:

```css
    /* ── Bottom CTA ── */
    .cta-section { padding: 3rem 0 5rem; }
    .cta-box {
      background: var(--surface);
      border: 1px solid var(--border);
      border-top: 3px solid var(--accent);
      border-radius: var(--radius);
      padding: 3rem 2rem;
      text-align: center;
    }
    .cta-box h2 { margin-bottom: 0.75rem; }
```

- [ ] **Step 2: Open in browser and verify**

```bash
open "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/index.html"
```

Expected: a centered card with teal top border, "Stop flying blind." headline, same two CTAs as the hero.

- [ ] **Step 3: Review the full page end to end**

Scroll through the entire page. Check:
- Nav → Hero → Pain cards → Solution → How It Works → CTA → Footer
- All sections present, no broken layout
- Teal accent consistent throughout
- No orange (`#D97757`) visible anywhere

- [ ] **Step 4: Commit**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add site/index.html
git commit -m "feat: add bottom CTA section, complete landing page markup"
```

---

## Task 9: Add screenshots and deploy config

**Files:**
- Modify: `site/index.html` (no markup changes — just verifying screenshots load)
- Create: `netlify.toml` (or `vercel.json`) for deploy config

- [ ] **Step 1: Add screenshots if not already done (from Task 2)**

Verify:
```bash
ls "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/screenshots/"
```

If missing, take screenshots now:
- Menu bar icon: `⌘⇧4`, click the ClaudeWatch icon area in the menu bar → save as `site/screenshots/menubar.png`
- Dropdown: click the icon to open the menu, then `⌘⇧4` → drag to capture it → save as `site/screenshots/dropdown.png`

- [ ] **Step 2: Open the page and verify screenshots display**

```bash
open "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/site/index.html"
```

Both images should render in the hero and solution sections. If they appear very large, add a `max-height` in the CSS:

```css
.hero-image .screenshot  { max-height: 80px; }   /* menu bar strip — usually very wide */
.solution-image .screenshot { max-height: 420px; } /* dropdown — taller */
```

Add these overrides inside the `<style>` block if needed.

- [ ] **Step 3: Create Netlify deploy config**

Create `netlify.toml` at the repo root:

```toml
[build]
  publish = "site"
```

This tells Netlify to serve the `site/` directory as the website root. No build command needed — it's static HTML.

- [ ] **Step 4: Verify config**

```bash
cat "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch/netlify.toml"
```

Expected output:
```
[build]
  publish = "site"
```

- [ ] **Step 5: Commit everything**

```bash
cd "/Users/katespurr/Library/Mobile Documents/com~apple~CloudDocs/ClaudeWatch"
git add site/ netlify.toml
git commit -m "feat: add screenshots and Netlify deploy config"
```

- [ ] **Step 6: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 7: Deploy on Netlify**

1. Go to [netlify.com](https://netlify.com) → New site → Import from GitHub
2. Select the `ClaudeWatch` repo
3. Build settings will auto-detect from `netlify.toml` — publish directory: `site`
4. Click Deploy
5. Once live, set your custom domain in Site settings → Domain management

---

## Done

The landing page is live and the dashboard accent is updated. Both share the teal (`#0D9488`) brand identity.

**To update the landing page later:** edit `site/index.html`, commit, push — Netlify auto-deploys on every push to `main`.

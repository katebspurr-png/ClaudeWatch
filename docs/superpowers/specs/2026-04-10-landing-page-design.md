# ClaudeWatch Landing Page Design

**Date:** 2026-04-10  
**Approach:** A — "Flying Blind"  
**Status:** Approved

---

## Summary

A single-page static landing page for ClaudeWatch hosted on Netlify or Vercel. Dark theme, pain-first copy, real app screenshots. Monetization via PWYC Gumroad download with free GitHub fallback.

---

## Visual Direction

- **Background:** #0a0a0f (near-black)
- **Accent:** #6c47ff (purple, matches Claude's brand)
- **Text:** white / #888 secondary
- **Typography:** system-ui, bold headlines
- **Images:** real screenshots of ClaudeWatch (menu bar icon + dropdown)
- **Layout:** single-page, vertical scroll, responsive (desktop + mobile)

---

## Page Structure

### 1. Hero

**Headline:** "You're flying blind on Claude limits."

**Subhead:** Claude cuts you off mid-project and you never see it coming. ClaudeWatch puts your session and weekly usage right in the menu bar — always visible, always current.

**CTAs (side by side):**
- Primary: `Download · pay what you can` → Gumroad (purple button)
- Secondary: `Free on GitHub →` (text/ghost link)

**Visual:** Screenshot of the menu bar showing the ClaudeWatch title string (e.g., `34% | 64%`), beside or below copy on desktop, stacked on mobile.

---

### 2. Pain Section

Three short cards, no CTA. Goal: make the user feel seen before offering the fix.

1. *"You're deep in a project. Claude slows down. You had no idea you were close."*
2. *"You go looking for your usage. It's buried in settings, three clicks deep."*
3. *"You hit the limit. The work stops. You wait."*

---

### 3. Solution Section

**Screenshot:** ClaudeWatch dropdown open, showing session %, weekly %, reset time.

**Copy:** ClaudeWatch sits in your menu bar and polls your usage every few minutes. Session usage. Weekly usage. Time until reset. All there. No surprises.

---

### 4. How It Works

Three numbered steps, kept minimal:

1. Download the DMG
2. Drag to Applications
3. Right-click → Open on first launch

**Note:** Requires macOS and the Claude desktop app.

---

### 5. Download CTA (repeat)

**Headline:** "Stop flying blind."

Same two CTAs as the hero. Small supporting text: *Pay what you want — or get it free on GitHub.*

---

## Tech

- **Format:** Single HTML file + inline or linked CSS. No framework needed.
- **Hosting:** Netlify or Vercel (static deploy from repo)
- **Images:** App screenshots provided by user; optimized for web (WebP preferred)
- **No JavaScript required** for core functionality (optional: smooth scroll)

---

## Copy Principles

- Lead with pain, flip to solution
- Use "you" language throughout
- Short sentences, no jargon
- PWYC framing: "pay what you can" not "pay what you want" — implies community norm

---

## Out of Scope

- Blog, changelog, or docs pages
- Email capture / waitlist
- Analytics beyond basic page view tracking (optional add later)
- Dark/light mode toggle

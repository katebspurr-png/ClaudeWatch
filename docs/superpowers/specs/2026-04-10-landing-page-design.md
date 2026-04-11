# ClaudeWatch Landing Page Design

**Date:** 2026-04-10  
**Approach:** A — "Flying Blind"  
**Status:** Approved

---

## Summary

A single-page static landing page for ClaudeWatch hosted on Netlify or Vercel. Dark theme, pain-first copy, real app screenshots. Monetization via PWYC Gumroad download with free GitHub fallback.

---

## Visual Direction

The landing page and the in-app dashboard share a visual language — same tokens, same card style, same font stack. Someone who's used the dashboard should feel at home on the website immediately.

**Design principle:** Deliberately avoid the purple/indigo palette saturating AI tools. Teal is ClaudeWatch's own identity — technical, distinct, nothing like Anthropic or the dozen other Claude utilities out there.

**Shared design tokens (applied to both landing page and dashboard):**
- **Accent:** `#0D9488` (teal — bars, CTAs, highlights, left-borders)
- **Font:** `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`
- **Card style:** rounded corners (12px), subtle `1px` border, surface background
- **Muted text:** `#9ca3af` (dark mode) / `#6b7280` (light mode)

**Dark palette (landing page and dashboard dark mode):**
- **Hero background:** `#0a0a0f` (richer dark for dramatic hero)
- **Card/surface background:** `#1c1c1e`
- **Border:** `#2d2d2d`
- **Text:** `#f5f5f5` / `#9ca3af` secondary

**Note:** The dashboard currently uses `#D97757` (orange). As part of this work, the dashboard accent will be updated to `#0D9488` to match the new brand identity.

**Images:** real screenshots of ClaudeWatch (menu bar icon + dropdown)  
**Layout:** single-page, vertical scroll, responsive (desktop + mobile)

---

## Page Structure

### 1. Hero

**Headline:** "You're flying blind on Claude limits."

**Subhead:** Claude cuts you off mid-project and you never see it coming. ClaudeWatch puts your session and weekly usage right in the menu bar — always visible, always current.

**CTAs (side by side):**
- Primary: `Download · pay what you can` → Gumroad (teal button)
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

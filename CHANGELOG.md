# Changelog

## v1.0.8 — 2026-09-10

### Fixed
- **"Reset clock time" now works on its own** — enabling the clock time without "Reset countdown" left the display size matched to the Compact preset, which hides all reset info in the menu bar. The preset matcher now includes the clock-time flag, so toggling it alone switches to Custom and the clock shows.

## v1.0.7 — 2026-06-13

### Added
- **Fable 5 model support** — `claude-fable-5` added to model display mapping and conversation cost ranking. Fable 5 appears in the Model Guide (menu bar and dashboard) under "Creative & narrative" for storytelling, character building, creative ideation, and brand copy.

### Changed
- **Design usage removed as separate metric** — Claude Design is now counted within the weekly (7d) limit rather than having its own quota. Removed the separate Design card from the dashboard, the Design section from the menu bar dropdown, and the "Design % (7d)" toggle from Settings.

---

## Previous releases

See [GitHub commits](https://github.com/katebspurr-png/ClaudeWatch/commits/main) for full history.

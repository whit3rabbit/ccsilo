# Changelog

All notable changes to this project will be documented in this file.

## [0.7.2] - 2026-06-23

### Added
- Added Claude Code prompt catalogs and patch compatibility reports for 2.1.186 and 2.1.187.
- Added MCP tool timeout defaults.

### Changed
- Widened curated patch tested ranges through Claude Code 2.1.187 after Docker runtime smoke.

### Fixed
- Fixed `suppress-rate-limit-options` for Claude Code's JSX runtime render shape.

## [0.7.1] - 2026-06-21

### Added
- Added Claude Code 2.1.185 patch compatibility report with Docker runtime smoke evidence.

### Changed
- Widened curated patch tested ranges through Claude Code 2.1.185 after Docker runtime smoke.

### Fixed
- Fixed model proxy variants preserving stale Python interpreter paths across setup rebuilds.

## [0.7.0] - 2026-06-17

### Added
- Added Claude Code prompt catalogs for 2.1.179 and 2.1.181.
- Added latest Claude Code patch compatibility artifacts through 2.1.181.

### Changed
- Widened curated patch tested ranges through Claude Code 2.1.181 after Docker runtime smoke.

### Fixed
- Fixed `token-count-rounding` for Claude Code 2.1.179's arrow statusline token display.
- Bounded token-count fallback matching to avoid runaway regex scans on no-match bundles.

## [0.6.6] - 2026-06-13

### Added
- Added a `compact-window` environment tweak and `--compact-window` variant option for `CLAUDE_CODE_AUTO_COMPACT_WINDOW`.

### Changed
- Updated Z.ai defaults to GLM-5.2[1m] for Opus and Sonnet mappings.
- Updated MiniMax Cloud defaults to MiniMax-M3 and set provider compact-window defaults.

## [0.6.5] - 2026-06-13

### Added
- Improved release automation: updated `.github/workflows/release.yml` to automatically build, publish to PyPI, and upload distributions to the GitHub Release when a Release is published.

### Fixed
- Robustness improvements for variant configuration and model updates:
  - Ensured variant model updates call `_write_settings_config` to sync settings properly.
  - Preserved user-defined environment variables in variant settings.
  - Omitted `export ANTHROPIC_MODEL` in wrappers when using Architect mode (`opusplan1m` tweak) so the silo default model configuration wins.
  - Cleaned up statusline configuration dynamically when disabling the statusline tweak.

## [0.6.4] - 2026-06-08

### Added
- Improved latest version selection and created preview install UX.
- Refactored patch compatibility workflow.

## [0.6.3] - 2026-05-30

### Added
- Hardened prompt metadata review checks.
- Updated Architect Mode model picker and patch report index.

## [0.6.2] - 2026-05-20

### Added
- Support for Claude Code 2.1.172.

## [0.6.1] - 2026-05-10

### Added
- Organized provider selector by type.
- Added input border patch and startup banner anchor fixes for Claude Code 2.1.167.

## [0.6.0] - 2026-04-28

### Added
- Added tweak to hide the npm deprecation warning in newer Claude Code native binaries.

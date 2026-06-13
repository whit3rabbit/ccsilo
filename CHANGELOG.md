# Changelog

All notable changes to this project will be documented in this file.

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

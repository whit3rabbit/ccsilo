# Claude Code Router Support

ccsilo supports Claude Code Router through the `ccrouter` provider. The
default mode is managed and isolated: ccsilo installs CCR inside the
setup, creates a setup-local home directory, copies or seeds CCR config, starts
CCR on demand, and runs the patched Claude Code binary directly.

The `ccr-oauth` provider uses the same managed CCR runtime, but enables the
Architect model proxy flow from the TUI. Use it when planner/`claude-*` calls
should keep Claude Code OAuth/session auth while worker aliases route through
CCR.

## Managed CCR

Create a managed setup:

```bash
ccsilo variant create --name ccrouter --provider ccrouter
```

Managed files live under the setup:

```text
.ccsilo/variants/<setup-id>/ccr-runtime/
.ccsilo/variants/<setup-id>/ccr-home/.claude-code-router/config.json
.ccsilo/variants/<setup-id>/tmp/ccrouter.log
```

Important behavior:

- `HOME` and `USERPROFILE` are set to the setup-local `ccr-home` before running
  `ccr`, so CCR reads and writes setup-local config.
- `@musistudio/claude-code-router` is installed locally with npm under
  `ccr-runtime`; no global npm install is required.
- If the real `~/.claude-code-router/config.json` exists, managed create uses
  `copy-global` by default. The copy is one-time and not a symlink.
- If no global config exists, managed create uses `empty` and writes a minimal
  config with `PORT`, `Providers`, and `Router`.
- The copied or seeded config gets a setup-specific local port unless
  `--ccrouter-port` is supplied.
- The wrapper starts `ccr start` when auto-start is enabled, parses the isolated
  config safely, exports the Anthropic-compatible CCR endpoint, and then execs
  the ccsilo patched Claude binary. It does not call `ccr code`.

Useful create options:

```bash
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-config empty
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-config copy-global
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-package @musistudio/claude-code-router@2.0.0
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-port 4567
ccsilo variant create --name ccrouter --provider ccrouter --no-ccrouter-autostart
```

Use `variant doctor` to check the wrapper, config, local `ccr` install, Node
version, and CCR running state:

```bash
ccsilo variant doctor ccrouter
```

## External CCR

Use external mode when you intentionally want to manage a global CCR service
yourself:

```bash
npm install -g @musistudio/claude-code-router
# edit ~/.claude-code-router/config.json
ccr start
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-mode external
```

In external mode, ccsilo keeps the old behavior: the setup points Claude
Code at `http://127.0.0.1:3456` unless you override the endpoint, and
ccsilo does not install or start CCR.

## TUI Notes

The setup wizard shows managed CCR options on the credentials step when the
`ccrouter` or `ccr-oauth` provider is selected:

- managed or external mode;
- config source (`copy-global`, `empty`, or `shared-home`);
- npm package spec;
- port (`auto` or a number);
- auto-start toggle.

After creating a managed CCR setup, the setup detail screen shows CCR metadata
and actions for status, start, stop, restart, UI, and copying the setup-local
CCR config path.

The `ccr-oauth` provider defaults the wizard's Tweaks step to Architect model
proxy enabled and selects the `opusplan1m` Architect Mode tweak. The Models step
still matters: set Opus to a `claude-*` model and set worker aliases to names
your CCR config can route.

## Architect Model Proxy

`--model-proxy architect` is separate from CCR. It is a managed, setup-local
Anthropic-compatible proxy for Architect Mode setups. The proxy refuses every
mode except `architect`; use it with the Architect Mode tweak so Claude Code can
split planner/Claude calls from worker/backend calls.

This mode requires a Claude Code account and a valid Claude Code login. The
wrapper starts the proxy on `127.0.0.1`, points `ANTHROPIC_BASE_URL` at that
local proxy, and unsets Claude API/auth token variables before launching Claude
Code so the normal OAuth/session path remains active.

How requests route:

- only `POST /<per-run-nonce>/v1/messages` is accepted by the local proxy;
- the configured `claude-*` planner models go to Anthropic using the user's
  Claude Code OAuth/session headers;
- the configured backend worker models go to the provider backend using the
  backend credential;
- the backend credential is passed only to the proxy process, then removed from
  the wrapper environment before Claude Code starts;
- upstream calls use the provider `API_TIMEOUT_MS` value recorded in the
  generated proxy config;
- the proxy stops when the setup command exits.

Create with the Architect Mode tweak:

```bash
ccsilo variant create \
  --name architect-proxy \
  --provider deepseek \
  --credential-env DEEPSEEK_API_KEY \
  --model-proxy architect \
  --model-opus claude-opus-4-6 \
  --tweak opusplan1m
```

OpenRouter example with explicit worker models:

```bash
ccsilo variant create \
  --name openrouter-architect \
  --provider openrouter \
  --credential-env OPENROUTER_API_KEY \
  --model-proxy architect \
  --model-opus claude-opus-4-6 \
  --model-sonnet deepseek/deepseek-v4-pro \
  --model-haiku deepseek/deepseek-v4-pro \
  --tweak opusplan1m
```

Rules:

- `--model-proxy` only accepts `architect`.
- The provider must have backend credentials.
- You need a Claude Code account because `claude-*` planner/Opus requests are
  still served by Anthropic through Claude Code OAuth.
- `--model-opus` is required and must be a `claude-*` model because
  Opus/architect calls are kept on Claude and the proxy uses an exact route map.
- Worker/default model aliases can point at backend models.
- Existing Architect proxy setups created before route-map support must be
  reapplied or updated before use; stale proxy configs fail closed.
- Complete the normal Claude Code login flow before using the wrapper if this
  machine is not already logged in.
- The wrapper starts the proxy for the lifetime of the setup command and stops
  it on exit.
- `remote-control` and other Claude Code subcommands run through the generated
  setup wrapper, for example `<setup-command> remote-control`.

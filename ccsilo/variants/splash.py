"""Provider splash art rendered by generated variant wrappers."""

import shlex
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


RESET = r"\033[0m"
ASCII_DIR = Path(__file__).with_name("ascii")


PALETTES: Dict[str, Tuple[str, str, str, str]] = {
    "9router": (r"\033[38;5;208m", r"\033[38;5;75m", r"\033[38;5;45m", r"\033[38;5;240m"),
    "alibaba": (r"\033[38;5;51m", r"\033[38;5;81m", r"\033[38;5;141m", r"\033[38;5;60m"),
    "anthropic": (r"\033[38;5;216m", r"\033[38;5;223m", r"\033[38;5;215m", r"\033[38;5;94m"),
    "ccrouter": (r"\033[38;5;39m", r"\033[38;5;45m", r"\033[38;5;33m", r"\033[38;5;31m"),
    "ccr-oauth": (r"\033[38;5;45m", r"\033[38;5;121m", r"\033[38;5;39m", r"\033[38;5;31m"),
    "cerebras": (r"\033[38;5;214m", r"\033[38;5;220m", r"\033[38;5;208m", r"\033[38;5;94m"),
    "custom": (r"\033[38;5;255m", r"\033[38;5;183m", r"\033[38;5;147m", r"\033[38;5;245m"),
    "deepseek": (r"\033[38;5;39m", r"\033[38;5;75m", r"\033[38;5;33m", r"\033[38;5;25m"),
    "gatewayz": (r"\033[38;5;141m", r"\033[38;5;135m", r"\033[38;5;99m", r"\033[38;5;60m"),
    "kimi": (r"\033[38;5;81m", r"\033[38;5;75m", r"\033[38;5;69m", r"\033[38;5;67m"),
    "llamacpp": (r"\033[38;5;118m", r"\033[38;5;76m", r"\033[38;5;111m", r"\033[38;5;240m"),
    "litellm": (r"\033[38;5;45m", r"\033[38;5;82m", r"\033[38;5;159m", r"\033[38;5;239m"),
    "lmstudio": (r"\033[38;5;80m", r"\033[38;5;116m", r"\033[38;5;45m", r"\033[38;5;66m"),
    "local-custom": (r"\033[38;5;250m", r"\033[38;5;121m", r"\033[38;5;43m", r"\033[38;5;240m"),
    "minimax": (r"\033[38;5;203m", r"\033[38;5;209m", r"\033[38;5;208m", r"\033[38;5;167m"),
    "minimax-cn": (r"\033[38;5;196m", r"\033[38;5;214m", r"\033[38;5;220m", r"\033[38;5;88m"),
    "mirror": (r"\033[38;5;252m", r"\033[38;5;250m", r"\033[38;5;45m", r"\033[38;5;243m"),
    "nanogpt": (r"\033[38;5;120m", r"\033[38;5;51m", r"\033[38;5;154m", r"\033[38;5;66m"),
    "ollama": (r"\033[38;5;180m", r"\033[38;5;223m", r"\033[38;5;137m", r"\033[38;5;101m"),
    "anyllm": (r"\033[38;5;78m", r"\033[38;5;120m", r"\033[38;5;43m", r"\033[38;5;240m"),
    "omlx": (r"\033[38;5;105m", r"\033[38;5;141m", r"\033[38;5;111m", r"\033[38;5;60m"),
    "openrouter": (r"\033[38;5;252m", r"\033[38;5;250m", r"\033[38;5;45m", r"\033[38;5;243m"),
    "poe": (r"\033[38;5;141m", r"\033[38;5;177m", r"\033[38;5;99m", r"\033[38;5;60m"),
    "vercel": (r"\033[38;5;255m", r"\033[38;5;250m", r"\033[38;5;34m", r"\033[38;5;240m"),
    "zai": (r"\033[38;5;220m", r"\033[38;5;214m", r"\033[38;5;208m", r"\033[38;5;172m"),
    "opencode-go": (r"\033[38;5;99m", r"\033[38;5;105m", r"\033[38;5;111m", r"\033[38;5;60m"),
    "opencode-zen": (r"\033[38;5;129m", r"\033[38;5;135m", r"\033[38;5;141m", r"\033[38;5;60m"),
    "default": (r"\033[38;5;255m", r"\033[38;5;250m", r"\033[38;5;45m", r"\033[38;5;245m"),
}


SPLASH_TEXT: Dict[str, Tuple[str, ...]] = {
    "9router": ("   9ROUTER", "  [ LOCAL AI GATEWAY ]", "  FALLBACK READY"),
    "alibaba": ("   ALIBABA CLOUD", "  [ DASH SCOPE ]", "  QWEN CODING LANE"),
    "anthropic": ("   ANTHROPIC", "  < CONSOLE API >", "  FIRST PARTY CLAUDE"),
    "ccrouter": ("   CC ROUTER", "  < ANY MODEL >", "  LOCAL ROUTE ONLINE"),
    "ccr-oauth": ("   CCR OAUTH", "  < ARCHITECT PROXY >", "  CLAUDE LOGIN + CCR"),
    "cerebras": ("   CEREBRAS", "  [ WAFER SCALE ]", "  ROUTED VIA CCR"),
    "custom": ("   CUSTOM", "  [ BRING YOUR ENDPOINT ]", "  CONFIGURED VARIANT"),
    "deepseek": ("   DEEPSEEK", "  < REASONING DEPTH >", "  CODE SEARCH MODE"),
    "gatewayz": ("   GATEWAYZ", "  [ MULTI MODEL GATEWAY ]", "  ROUTING ACTIVE"),
    "kimi": ("   KIMI CODE", "  < LONG CONTEXT >", "  MOONSHOT CODING"),
    "llamacpp": ("   LLAMA.CPP", "  [ LOCAL SERVER ]", "  GGUF ROUTE READY"),
    "litellm": ("   LITELLM", "  [ AI GATEWAY ]", "  ROUTES READY"),
    "lmstudio": ("   LM STUDIO", "  [ LOCAL MODELS ]", "  SERVER ONLINE"),
    "local-custom": ("   LOCAL LLM", "  [ CUSTOM ENDPOINT ]", "  MODEL PORT READY"),
    "minimax": ("   MINIMAX", "  [ MODEL SPECTRUM ]", "  AGI FOR ALL"),
    "minimax-cn": ("   MINIMAX CN", "  [ MODEL SPECTRUM ]", "  CHINA API ROUTE"),
    "mirror": ("   MIRROR CLAUDE", "  < CLEAN REFLECTION >", "  ISOLATED VANILLA"),
    "nanogpt": ("   NANOGPT", "  [ ANY MODEL ]", "  PAY PER TOKEN"),
    "ollama": ("   OLLAMA", "  < LOCAL FIRST >", "  MODELS NEARBY"),
    "anyllm": ("   ANYLLM PROXY", "  < LOCAL BRIDGE >", "  MODELS ONLINE"),
    "omlx": ("   OMLX", "  [ MLX LOCAL ]", "  APPLE SILICON LANE"),
    "openrouter": ("   OPENROUTER", "  [ ONE API ]", "  ANY MODEL"),
    "poe": ("   POE", "  < MODEL HUB >", "  TOKEN ROUTE READY"),
    "vercel": ("   VERCEL", "  [ AI GATEWAY ]", "  EDGE ROUTE ACTIVE"),
    "zai": ("   ZAI CLOUD", "  < GLM CODING PLAN >", "  REASONING ONLINE"),
    "opencode-go": ("   OPENCODE GO", "  < LOW COST OPEN CODING >", "  MODELS ONLINE"),
    "opencode-zen": ("   OPENCODE ZEN", "  < CURATED AI GATEWAY >", "  MODELS ONLINE"),
    "default": ("   CCSILO", "  [ PROVIDER VARIANT ]", "  CLAUDE CODE WRAPPED"),
}


def known_styles() -> Tuple[str, ...]:
    styles = {style for style in SPLASH_TEXT if style != "default"}
    if ASCII_DIR.is_dir():
        styles.update(path.stem for path in ASCII_DIR.glob("*.txt") if path.stem != "default")
    return tuple(sorted(styles))


def has_style(style: str) -> bool:
    return style in SPLASH_TEXT or _ascii_file_path(style).is_file()


def splash_lines(style: str) -> Tuple[str, ...]:
    """Return ANSI-colored splash lines for a known provider style."""
    resolved = style if has_style(style) else "default"
    primary, secondary, accent, dim = PALETTES.get(resolved, PALETTES["default"])
    art = splash_ascii_lines(resolved)
    body_colors = (primary, secondary, accent)
    last_index = len(art) - 1
    colored = []
    for index, line in enumerate(art):
        color = dim if index in {0, last_index} else body_colors[(index - 1) % len(body_colors)]
        colored.append(f"{color}{line}{RESET}")
    return ("", *colored, "")


def splash_ascii_lines(style: str) -> Tuple[str, ...]:
    """Return uncolored provider splash art lines for copying or machine output."""
    resolved = style if has_style(style) else "default"
    file_lines = _file_ascii_lines(resolved)
    if file_lines is not None:
        return file_lines
    text = SPLASH_TEXT[resolved]
    width = max(len(line) for line in text) + 4
    rule = "=" * width
    return (
        f"+{rule}+",
        f"|  {text[0].ljust(width - 2)}|",
        f"|  {text[1].ljust(width - 2)}|",
        f"|  {text[2].ljust(width - 2)}|",
        f"+{rule}+",
    )


def splash_ascii_art(style: str) -> str:
    """Return uncolored provider splash art as a copyable multi-line string."""
    return "\n".join(splash_ascii_lines(style))


def splash_quote_block(style: str) -> str:
    """Return provider splash art formatted as a Markdown quote block."""
    return "\n".join(f"> {line}" for line in splash_ascii_lines(style))


def _file_ascii_lines(style: str) -> Optional[Tuple[str, ...]]:
    path = _ascii_file_path(style)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    lines = tuple(text.splitlines())
    return lines or None


def _ascii_file_path(style: str) -> Path:
    return ASCII_DIR / f"{style}.txt"


def shell_splash_lines(styles: Iterable[str] = None) -> List[str]:
    """Return POSIX shell lines that render splash art from wrapper env."""
    styles = tuple(styles or known_styles())
    lines = [
        'if [ "${CCSILO_SPLASH:-0}" = "1" ] && [ -t 1 ]; then',
        "  __ccsilo_skip_splash=0",
        '  for __ccsilo_arg in "$@"; do',
        '    case "$__ccsilo_arg" in',
        "      --output-format|--output-format=*|--print|-p) __ccsilo_skip_splash=1 ;;",
        "    esac",
        "  done",
        '  if [ "$__ccsilo_skip_splash" = "0" ]; then',
        '    __ccsilo_style="${CCSILO_SPLASH_STYLE:-default}"',
        '    __ccsilo_label="${CCSILO_PROVIDER_LABEL:-ccsilo}"',
        '    __ccsilo_known_style=1',
        '    case "$__ccsilo_style" in',
    ]
    for style in styles:
        lines.extend(_shell_style_case(style))
    lines.extend(
        [
            "      *)",
            "        __ccsilo_known_style=0",
            *(_shell_print_line(line) for line in splash_lines("default")),
            "        ;;",
            "    esac",
            '    if [ "$__ccsilo_known_style" = "0" ]; then',
            '      printf " %s\\n\\n" "$__ccsilo_label"',
            "    fi",
            "  fi",
            "fi",
        ]
    )
    return lines


def _shell_style_case(style: str) -> List[str]:
    lines = [f"      {style})"]
    lines.extend(_shell_print_line(line) for line in splash_lines(style))
    lines.append("        ;;")
    return lines


def _shell_print_line(line: str) -> str:
    return f"        printf '%b\\n' {shlex.quote(line)}"

"""Ratatui widget and frame rendering helpers."""

import textwrap
from typing import Optional

from ._const import TABS
from .options import variant_provider_detail_lines, variant_provider_selector_labels
from .render_labels import (
    _variant_provider_selector_active,
    active_tab_index,
    ascii_progress,
    body_text,
    clamp_ratio,
    context_line,
    current_labels,
    empty_text,
    footer_lines,
    key_line,
    layout_heights,
    panel_title,
    selected_label_index,
    status_line,
    tweaks_detail_text,
    visible_items,
)
from .themes import active_theme

__all__ = ['style', 'color', 'status_style', 'tabs_widget', 'list_widget', 'tweaks_detail_widget', 'gauge_widget', '_fit_text', '_box_top', '_box_middle', '_box_bottom', '_single_role_row', '_box_rows', '_body_content_rows', '_label_role', '_body_box_rows', '_modal_content_rows', '_tweaks_detail_box_rows', '_provider_detail_box_rows', '_wrap_detail_lines', '_combine_segment_rows', '_tweaks_two_pane_rows', '_provider_selector_two_pane_rows', '_progress_box_rows', '_plain_rows', '_minimal_frame_rows', '_frame_rows', '_frame_styles', 'render_frame']

_BOX_TOP_LEFT = "\u250c"
_BOX_TOP_RIGHT = "\u2510"
_BOX_BOTTOM_LEFT = "\u2514"
_BOX_BOTTOM_RIGHT = "\u2518"
_BOX_HORIZONTAL = "\u2500"
_BOX_VERTICAL = "\u2502"

def style(Style, Color, fg: Optional[str] = None, bg: Optional[str] = None, bold: bool = False):
    s = Style(fg=color(Color, fg), bg=color(Color, bg))
    if bold:
        s = s.bold()
    return s

def color(Color, name: Optional[str]):
    return getattr(Color, name or "Reset")

def status_style(state, Style, Color):
    theme = active_theme(state)
    lowered = state.message.lower()
    if "failed" in lowered or "invalid" in lowered or "missing" in lowered or "broken" in lowered:
        return style(Style, Color, theme.error_fg, theme.footer_bg, bold=True)
    if "warning" in lowered:
        return style(Style, Color, theme.warning_fg, theme.footer_bg, bold=True)
    if "complete" in lowered or "created" in lowered or "loaded" in lowered or "healthy" in lowered:
        return style(Style, Color, theme.success_fg, theme.footer_bg, bold=True)
    return style(Style, Color, theme.warning_fg, theme.footer_bg)

def tabs_widget(state, Tabs, Style, Color, theme):
    tabs = Tabs()
    tabs.set_titles(TABS)
    tabs.set_selected(active_tab_index(state))
    tabs.set_divider(" | ")
    tabs.set_block_title("Tabs", True)
    tabs.set_styles(
        style(Style, Color, theme.tab_fg, theme.tab_bg),
        style(Style, Color, theme.tab_selected_fg, theme.tab_selected_bg, bold=True),
    )
    return tabs

def list_widget(state, height, TuiList, Style, Color, theme):
    title, labels = current_labels(state)
    body = TuiList()
    body.set_block_title(title, True)
    body.set_highlight_symbol(">> ")
    body.set_highlight_style(
        style(Style, Color, theme.highlight_fg, theme.highlight_bg, bold=True)
    )

    if labels:
        for label in labels:
            role = _label_role(label)
            fg = {
                "success": theme.success_fg,
                "warning": theme.warning_fg,
                "error": theme.error_fg,
            }.get(role, theme.body_fg)
            body.append_item(label, style(Style, Color, fg, theme.body_bg))
        cursor = selected_label_index(state)
        body.set_selected(cursor)
        body.set_scroll_offset(max(0, cursor - max(0, height // 2)))
    else:
        body.append_item(empty_text(state), style(Style, Color, theme.body_fg, theme.body_bg))
        body.set_selected(None)
    return body

def tweaks_detail_widget(state, Paragraph, Style, Color, theme):
    """Right-pane Paragraph for tweaks-edit mode."""
    text = tweaks_detail_text(state)
    paragraph = Paragraph.from_text(text)
    paragraph.set_block_title("Tweak details", True)
    paragraph.set_style(style(Style, Color, theme.body_fg, theme.body_bg))
    paragraph.set_wrap(True)
    return paragraph

def gauge_widget(title, ratio, label, Gauge, Style, Color, theme):
    gauge = Gauge()
    gauge.ratio(clamp_ratio(ratio))
    gauge.label(label)
    gauge.set_block_title(title, True)
    gauge.set_styles(
        style(Style, Color, theme.gauge_fg, theme.gauge_bg),
        style(Style, Color, theme.gauge_label_fg, theme.gauge_label_bg, bold=True),
        style(Style, Color, theme.gauge_fill_fg, theme.gauge_fill_bg, bold=True),
    )
    return gauge

def _fit_text(text, width):
    if width <= 0:
        return ""
    text = str(text).replace("\n", " ")
    if len(text) > width:
        return text[:width]
    return text + (" " * (width - len(text)))

def _box_top(title, width):
    if width <= 1:
        return _fit_text(title, width)
    inner_width = width - 2
    label = str(title)[:inner_width]
    return _BOX_TOP_LEFT + label + (_BOX_HORIZONTAL * (inner_width - len(label))) + _BOX_TOP_RIGHT

def _box_middle(text, width):
    if width <= 1:
        return _fit_text(text, width)
    return _BOX_VERTICAL + _fit_text(text, width - 2) + _BOX_VERTICAL

def _box_bottom(width):
    if width <= 1:
        return _BOX_HORIZONTAL[:width]
    return _BOX_BOTTOM_LEFT + (_BOX_HORIZONTAL * (width - 2)) + _BOX_BOTTOM_RIGHT

def _single_role_row(text, role):
    return [(text, role)]

def _box_rows(title, content_rows, width, height, role):
    if height <= 0:
        return []
    if height == 1:
        return [_single_role_row(_fit_text(title, width), role)]

    rows = [_single_role_row(_box_top(title, width), role)]
    if height > 2:
        visible_rows = list(content_rows)[:height - 2]
        while len(visible_rows) < height - 2:
            visible_rows.append(("", role))
        for row in visible_rows:
            if isinstance(row, tuple):
                text, row_role = row
            else:
                text, row_role = row, role
            rows.append(_single_role_row(_box_middle(text, width), row_role))
    rows.append(_single_role_row(_box_bottom(width), role))
    return rows[:height]

def _body_content_rows(state, height):
    _, labels = current_labels(state)
    if _variant_provider_selector_active(state):
        labels = variant_provider_selector_labels(state)
    cursor = selected_label_index(state)
    visible = visible_items(labels, cursor, max(1, height))
    if not visible:
        return [(f"  {empty_text(state)}", "body")]

    rows = []
    start_index, visible_labels = visible
    for offset, label in enumerate(visible_labels):
        index = start_index + offset
        selected = index == cursor
        prefix = "> " if selected else "  "
        rows.append((prefix + label, "highlight" if selected else _label_role(label)))
    return rows

def _label_role(label):
    lowered = str(label).lower()
    if " broken" in lowered or "blocked:" in lowered or "unsupported" in lowered:
        return "error"
    if " warning" in lowered or "advanced" in lowered or "unknown" in lowered:
        return "warning"
    if " healthy" in lowered or " ready" in lowered:
        return "success"
    return "body"

def _body_box_rows(state, width, height, title_override=None):
    title, _ = current_labels(state)
    box_title = panel_title(state, title) if title_override is None else title_override
    inner_height = max(0, height - 2)
    if state.mode == "inspect-delete-confirm":
        _, labels = current_labels(state)
        content_rows = _modal_content_rows("Confirm delete", labels, max(1, width - 2), inner_height)
        return _box_rows(box_title, content_rows, width, height, "body")

    content_rows = []
    if inner_height >= 1:
        content_rows.append((context_line(state), "body"))
    if inner_height >= 2:
        content_rows.append(("", "body"))
    item_height = max(1, inner_height - len(content_rows))
    content_rows.extend(_body_content_rows(state, item_height))
    return _box_rows(box_title, content_rows, width, height, "body")

def _modal_content_rows(title, labels, width, height):
    if height <= 0:
        return []
    content_width = max(1, width)
    label_width = max([len(str(title)), *(len(str(label)) for label in labels)] or [1])
    modal_width = min(content_width, max(42, label_width + 4))
    modal_height = min(height, max(5, len(labels) + 2))
    top_pad = max(0, (height - modal_height) // 2)
    left_pad = max(0, (content_width - modal_width) // 2)
    rows = [("", "body") for _ in range(top_pad)]
    for row in _box_rows(title, labels, modal_width, modal_height, "body"):
        text = "".join(part for part, _role in row)
        rows.append(((" " * left_pad) + text, "body"))
    while len(rows) < height:
        rows.append(("", "body"))
    return rows[:height]

def _tweaks_detail_box_rows(state, width, height):
    detail_rows = [(line, "body") for line in tweaks_detail_text(state).splitlines()]
    return _box_rows("Tweak details", detail_rows, width, height, "body")

def _provider_detail_box_rows(state, width, height):
    content_width = max(1, width - 2)
    detail_rows = [
        (line, "body")
        for line in _wrap_detail_lines(variant_provider_detail_lines(state), content_width)
    ]
    detail_rows = _compact_blank_rows(detail_rows, max(0, height - 2))
    return _box_rows("Provider details", detail_rows, width, height, "body")

def _compact_blank_rows(rows, max_rows):
    compacted = list(rows)
    while len(compacted) > max_rows:
        for index in range(len(compacted) - 1, -1, -1):
            text, _role = compacted[index]
            if not text:
                del compacted[index]
                break
        else:
            break
    return compacted

def _wrap_detail_lines(lines, width):
    wrapped = []
    for line in lines:
        text = str(line)
        if not text:
            wrapped.append("")
            continue
        if text.startswith("- "):
            wrapped.extend(textwrap.wrap(
                text,
                width=max(1, width),
                subsequent_indent="  ",
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""])
            continue
        wrapped.extend(textwrap.wrap(
            text,
            width=max(1, width),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""])
    return wrapped

def _combine_segment_rows(left_rows, right_rows, gap_width):
    gap = " " * max(0, gap_width)
    rows = []
    for left, right in zip(left_rows, right_rows):
        rows.append(left + [(gap, "body")] + right)
    return rows

def _tweaks_two_pane_rows(state, width, height):
    if width <= 1:
        return _body_box_rows(state, width, height)
    gap = 1
    left_width = max(1, int((width - gap) * 0.45))
    right_width = max(1, width - gap - left_width)
    left_rows = _body_box_rows(state, left_width, height)
    right_rows = _tweaks_detail_box_rows(state, right_width, height)
    return _combine_segment_rows(left_rows, right_rows, gap)

def _provider_selector_two_pane_rows(state, width, height):
    if width <= 1:
        return _body_box_rows(state, width, height)
    gap = 1
    left_width = max(1, int((width - gap) * 0.42))
    right_width = max(1, width - gap - left_width)
    title, _ = current_labels(state)
    left_title = str(title).split(": ", 1)[-1]
    left_rows = _body_box_rows(state, left_width, height, title_override=left_title)
    right_rows = _provider_detail_box_rows(state, right_width, height)
    return _combine_segment_rows(left_rows, right_rows, gap)

def _progress_box_rows(title, ratio, label, width):
    progress_width = max(4, min(24, width - len(title) - len(label) - 8))
    return _box_rows(title, [ascii_progress(title, ratio, label, width=progress_width)], width, 3, "gauge")

def _plain_rows(lines, width, role):
    return [_single_role_row(_fit_text(line, width), role) for line in lines]

def _minimal_frame_rows(state, width, height):
    footer_candidates = [status_line(state), key_line(state)]
    footer_height = min(len(footer_candidates), max(0, height - 1))
    body_height = max(1, height - footer_height)
    body_rows = body_text(state, body_height).splitlines()[:body_height]
    rows = []
    rows.extend(_plain_rows(body_rows, width, "body"))
    rows.extend(_plain_rows(footer_candidates[:footer_height], width, "footer"))
    return rows[:height]

def _frame_rows(state, width, height):
    width = max(1, width)
    height = max(1, height)
    if height < 12:
        rows = _minimal_frame_rows(state, width, height)
        if len(rows) < height:
            rows.extend(_single_role_row(_fit_text("", width), "body") for _ in range(height - len(rows)))
        return rows[:height]

    top_height, footer_height = layout_heights(height)
    body_height = max(1, height - top_height - footer_height)

    rows = []
    if _variant_provider_selector_active(state) and width > 72 and body_height >= 10:
        title, _ = current_labels(state)
        rows.extend(_plain_rows([panel_title(state, title)], width, "header"))
        rows.extend(_provider_selector_two_pane_rows(state, width, body_height - 1))
    elif state.mode in {"tweaks-edit", "tweak-editor"} and not state.tweak_apply_preview and width > 60:
        rows.extend(_tweaks_two_pane_rows(state, width, body_height))
    else:
        rows.extend(_body_box_rows(state, width, body_height))
    rows.extend(_box_rows("Status", footer_lines(state), width, footer_height, "footer"))

    if len(rows) < height:
        rows.extend(_single_role_row(_fit_text("", width), "body") for _ in range(height - len(rows)))
    return rows[:height]

def _frame_styles(state, Style, Color, theme):
    return {
        "header": style(Style, Color, theme.header_fg, theme.header_bg, bold=True),
        "tabs": style(Style, Color, theme.tab_fg, theme.tab_bg),
        "body": style(Style, Color, theme.body_fg, theme.body_bg),
        "highlight": style(Style, Color, theme.highlight_fg, theme.highlight_bg, bold=True),
        "success": style(Style, Color, theme.success_fg, theme.body_bg),
        "warning": style(Style, Color, theme.warning_fg, theme.body_bg),
        "error": style(Style, Color, theme.error_fg, theme.body_bg, bold=True),
        "gauge": style(Style, Color, theme.gauge_fg, theme.gauge_bg),
        "footer": status_style(state, Style, Color),
    }

def render_frame(term, state, width, height, Paragraph, Style, Color, DrawCmd, Tabs, TuiList, Gauge):
    width = max(1, width)
    height = max(1, height)
    theme = active_theme(state)
    frame = Paragraph.new_empty()
    styles = _frame_styles(state, Style, Color, theme)
    for row_index, row in enumerate(_frame_rows(state, width, height)):
        if row_index:
            frame.line_break()
        for text, role in row:
            frame.append_span(text, styles[role])
    frame.set_wrap(False)
    term.draw_frame([DrawCmd.paragraph(frame, (0, 0, width, height))])

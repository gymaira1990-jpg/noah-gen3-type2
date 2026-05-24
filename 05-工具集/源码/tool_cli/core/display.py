"""统一输出格式化 — human/json/quiet 三级"""
import json


def human_table(headers: list, rows: list, title: str = "") -> str:
    """画一个简易表格 (不用外部库)"""
    if not headers or not rows:
        return title + "\n  (无数据)\n"

    # 计算列宽
    col_widths = []
    for i, h in enumerate(headers):
        w = len(h)
        for r in rows:
            val = str(r[i]) if i < len(r) else ""
            cjk_w = sum(2 if ord(c) > 127 else 1 for c in val)
            w = max(w, cjk_w)
        col_widths.append(w)

    sep = "─" * (sum(col_widths) + len(headers) * 3 + 1)

    lines = []
    if title:
        lines.append(f"┌{'─' * (sum(col_widths) + len(headers) * 3 - 1)}┐")
        lines.append(f"│ {title}{' ' * (sum(col_widths) + len(headers) * 3 - 3 - len(title))}│")
        lines.append(f"├{sep}┤")
    else:
        lines.append(f"┌{sep}┐")

    # header
    hdr = "│"
    for i, h in enumerate(headers):
        w = col_widths[i]
        cjk_w = sum(2 if ord(c) > 127 else 1 for c in h)
        hdr += f" {h}{' ' * (w - cjk_w)} │"
    lines.append(hdr)
    lines.append(f"├{sep}┤")

    # rows
    for row in rows:
        rl = "│"
        for i, val in enumerate(row):
            v = str(val) if i < len(row) else ""
            w = col_widths[i]
            cjk_w = sum(2 if ord(c) > 127 else 1 for c in v)
            rl += f" {v}{' ' * (w - cjk_w)} │"
        lines.append(rl)

    lines.append(f"└{sep}┘")
    return "\n".join(lines)


def status_badge(status: str) -> str:
    icons = {"alive": "🟢", "degraded": "🟡", "dead": "🔴", "unknown": "⚪"}
    return icons.get(status, "❓")


def format_output(data, mode: str = "human", title: str = "") -> str:
    """统一出口: human/json/quiet"""
    if mode == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)
    elif mode == "quiet":
        return ""
    if isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)

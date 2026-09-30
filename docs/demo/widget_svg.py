#!/usr/bin/env python3
"""Draws a static SVG sketch of the /agent-top chat widget from `agent-top --json` output (for the README).

The real widget is the HTML fragment of `agent-top --widget`, styled by the chat host; this sketch mimics its
layout in a light theme so the README can show it without a host.
"""
import json
import sys
from html import escape as e

snap = json.load(open(sys.argv[1]))
W = 760
c = snap["counts"]
q_open = sum(q.get("open", 0) for q in (snap.get("questions") or {}).values())
q_over = sum(q.get("overdue", 0) for q in (snap.get("questions") or {}).values())
win = ((snap.get("limits") or {}).get("info") or {}).get("unifiedWindows") or {}
bad = c["error"] + c["dead"]
cards = [("running", str(c["live"]), "#1a7f37" if c["live"] else "#1f2328"), ("done", str(c["done"]), "#1f2328"),
         ("failed", str(bad), "#cf222e" if bad else "#1f2328"),
         ("questions" + (f", {q_over} overdue" if q_over else ""), f"{q_open}", "#cf222e" if q_over else "#1f2328")]
for k, lab in (("five_hour", "limit 5 h"), ("seven_day", "limit week")):
    if isinstance(win.get(k), dict):
        u = float(win[k].get("utilization") or 0)
        cards.append((lab, f"{round(u * 100)}%", "#cf222e" if u >= 0.9 else ("#9a6700" if u >= 0.7 else "#1f2328")))
STATE = {"live": ("live", "#1a7f37"), "done": ("done", "#59636e"), "error": ("error", "#cf222e"), "dead": ("died", "#cf222e")}


def clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def age(s):
    if s is None:
        return "—"
    return f"{s} s" if s < 90 else (f"{s // 60} min" if s < 5400 else f"{s // 3600} h")


out = []
y = 20
out.append(f'<text x="20" y="{y + 14}" class="h">agent-top · stages {e(", ".join(snap["stages"]))}</text>')
y += 32
cw = (W - 40 - 8 * (len(cards) - 1)) / len(cards)
for i, (lab, val, col) in enumerate(cards):
    x = 20 + i * (cw + 8)
    out.append(f'<rect x="{x:.0f}" y="{y}" width="{cw:.0f}" height="58" rx="8" fill="#f6f8fa"/>'
               f'<text x="{x + 12:.0f}" y="{y + 20}" class="s">{e(lab)}</text>'
               f'<text x="{x + 12:.0f}" y="{y + 45}" class="v" style="fill:{col}">{e(val)}</text>')
y += 74
for a in snap["agents"]:
    word, col = STATE[a["state"]]
    if a.get("quiet"):
        word, col = "quiet", "#9a6700"
    act = a.get("action")
    now = (f"▸ {act['text']}" + (f" · {age(act['elapsed_s'])}" if act.get("elapsed_s") is not None else "")) if act else \
        ("✎ " + (a.get("last_text") or (a.get("result") or {}).get("text") or ""))
    meta = [a["model"].replace("claude-", "") + (f"/{a['effort']}" if a.get("effort") else ""), f"{age(a['age_s'])} ago",
            f"{a['turns']} turn{'' if a['turns'] == 1 else 's'}"]
    if a.get("cost_usd") is not None:
        meta.append(f"${a['cost_usd']:.2f}")
    if a.get("unread"):
        meta.append(f"unread {len(a['unread'])}")
    out.append(f'<line x1="20" x2="{W - 20}" y1="{y}" y2="{y}" stroke="#d1d9e0" stroke-width="0.8"/>'
               f'<text x="20" y="{y + 22}" class="n" font-weight="600">{e(a["role"])}</text>'
               f'<text x="20" y="{y + 40}" class="s" style="fill:{col}">{e(word)}</text>'
               f'<text x="120" y="{y + 22}" class="n">{e(clip(a.get("title"), 80))}</text>'
               f'<text x="120" y="{y + 40}" class="s">{e(clip(now, 96))}</text>'
               f'<text x="120" y="{y + 56}" class="x">{e(" · ".join(meta))}</text>')
    y += 66
locks = [lk for lk in snap.get("locks") or [] if lk.get("active")]
for lk in locks:
    out.append(f'<text x="20" y="{y + 18}" class="s">lock {e(lk["kind"])} {e(lk["repo"])} — {e(lk["owner_name"])}, '
               f'until {e((lk.get("until") or "")[5:16].replace("T", " "))}</text>')
    y += 20
out.append(f'<text x="20" y="{y + 24}" class="x">snapshot · an agent\'s feed — /agent-top &lt;role&gt; or '
           f'agent-top --once --agent &lt;role&gt;</text>')
H = y + 40
print(f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img"
 aria-label="Sketch of the agent-top chat widget built from synthetic data">
<style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;fill:#1f2328}}
.h{{font-size:15px;font-weight:600}}.v{{font-size:20px;font-weight:500}}.s{{font-size:12px;fill:#59636e}}
.n{{font-size:14px}}.x{{font-size:11px;fill:#818b98}}</style>
<rect width="{W}" height="{H}" rx="12" fill="#ffffff" stroke="#d1d9e0"/>
{chr(10).join(out)}
</svg>''')

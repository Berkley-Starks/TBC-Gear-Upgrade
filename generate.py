#!/usr/bin/env python3
"""
Pel's Raid Audit — site generator.

Drops reports/<character>/<date>.md  →  <character>/<date>/index.html.
Also rebuilds <character>/index.html and root index.html.

Usage:
    python generate.py

Dependencies:
    pip install markdown

Markdown conventions:
    - Front matter is a YAML-ish block at the top, fenced by --- lines.
      Recognized keys: title, date, character, realm, spec, faction,
      professions. Everything else is passed through as meta rows.
    - WoW item/enchant coloring uses inline tags:
        [epic:28729]Spiteblade[/epic]      → purple + Wowhead link + tooltip
        [rare]Sun-Gilded Shouldercaps[/rare]
        [uncommon]Fel Leather Boots[/uncommon]
        [legendary]Warglaive of Azzinoth[/legendary]
        [common]Instant Poison VII[/common]
        [enchant:27984]Mongoose[/enchant]  → green mono + spell= link
    - Task-list checkboxes are supported:
        - [x] done
        - [ ] todo
    - GitHub-style admonition blockquotes are supported:
        > [!note] Optional title
        > body text
"""

from __future__ import annotations

import re
import html
import shutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

import markdown

# --------------------------------------------------------------------------- #
# Paths                                                                       #
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
ASSETS_DIR = ROOT / "assets"

# --------------------------------------------------------------------------- #
# Data                                                                        #
# --------------------------------------------------------------------------- #

QUALITIES = (
    "poor", "common", "uncommon", "rare",
    "epic", "legendary", "artifact", "enchant",
)


@dataclass
class Report:
    character: str
    date: str                           # YYYY-MM-DD
    md_path: Path
    meta: dict = field(default_factory=dict)
    body_md: str = ""

    @property
    def url_rel(self) -> str:
        return f"{self.character}/{self.date}/"

    @property
    def out_path(self) -> Path:
        return ROOT / self.character / self.date / "index.html"

    @property
    def title(self) -> str:
        return self.meta.get("title") or f"Audit — {self.date}"


# --------------------------------------------------------------------------- #
# Parsing                                                                     #
# --------------------------------------------------------------------------- #

FRONT_MATTER_RE = re.compile(
    r"\A---\s*\n(.*?\n)---\s*\n",
    re.DOTALL,
)


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    block = m.group(1)
    meta: dict = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def load_report(md_path: Path) -> Report:
    raw = md_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(raw)
    character = md_path.parent.name
    date = md_path.stem
    meta.setdefault("character", character)
    meta.setdefault("date", date)
    # Strip leading H1 from body if front matter supplies a title.
    if meta.get("title"):
        body = re.sub(r"\A\s*#\s+[^\n]+\n+", "", body, count=1)
    return Report(
        character=character,
        date=date,
        md_path=md_path,
        meta=meta,
        body_md=body,
    )


def discover_reports() -> list[Report]:
    out: list[Report] = []
    if not REPORTS_DIR.exists():
        return out
    for char_dir in sorted(REPORTS_DIR.iterdir()):
        if not char_dir.is_dir():
            continue
        for md_file in sorted(char_dir.glob("*.md")):
            out.append(load_report(md_file))
    return out


# --------------------------------------------------------------------------- #
# Markdown preprocessing                                                      #
# --------------------------------------------------------------------------- #

def _quality_sub(text: str) -> str:
    """
    Convert WoW item-quality tags into colored HTML.

        [epic]Malchazeen[/epic]          → <span class="q-epic">Malchazeen</span>
        [epic:28729]Spiteblade[/epic]    → <a class="q-epic" href="wowhead.com/tbc/item=28729"
                                              data-wowhead="item=28729"
                                              target="_blank" rel="noopener">Spiteblade</a>
        [enchant:27927]Stats[/enchant]   → linked anchor to spell=27927
    """
    tag_kind = {q: "item" for q in QUALITIES}
    tag_kind["enchant"] = "spell"

    for q in QUALITIES:
        kind = tag_kind[q]
        pat = re.compile(
            rf"\[{q}(?::([a-z]+=\d+|\d+))?\](.+?)\[/{q}\]",
            re.DOTALL,
        )

        def _repl(m, qq=q, kk=kind):
            raw_id = m.group(1)
            label = m.group(2)
            if not raw_id:
                return f'<span class="q-{qq}">{label}</span>'
            frag = raw_id if "=" in raw_id else f"{kk}={raw_id}"
            url = f"https://www.wowhead.com/tbc/{frag}"
            return (
                f'<a class="q-{qq}" href="{url}" '
                f'data-wowhead="{frag}" target="_blank" rel="noopener">'
                f'{label}</a>'
            )

        text = pat.sub(_repl, text)
    return text


_ADMON_TYPES = {"note", "tip", "important", "warning", "caution", "critical", "good"}


def _admon_sub(text: str) -> str:
    """
    Collapse GitHub-style admonition blockquotes:
        > [!note] Optional title
        > body
    Into a raw HTML <div class="admonition admonition-note">…</div>.
    """
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^>\s*\[!(\w+)\](.*)$", line)
        if m and m.group(1).lower() in _ADMON_TYPES:
            kind = m.group(1).lower()
            title_raw = m.group(2).strip()
            body_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                inner = lines[i][1:]
                if inner.startswith(" "):
                    inner = inner[1:]
                body_lines.append(inner)
                i += 1
            body_html = markdown.markdown(
                "\n".join(body_lines),
                extensions=["tables", "fenced_code", "attr_list"],
            )
            title_html = (
                f'<div class="admonition-title">{html.escape(title_raw or kind)}</div>'
            )
            out.append(
                f'<div class="admonition admonition-{kind}">{title_html}{body_html}</div>'
            )
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _task_list_sub(text: str) -> str:
    r"""
    Convert GitHub-flavored task list items into raw HTML <li class="task ...">.
    Matches /^\s*- \[[ xX]\] / lines and collects consecutive runs.
    """
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    task_re = re.compile(r"^(\s*)- \[([ xX])\]\s+(.*)$")
    while i < len(lines):
        m = task_re.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        items: list[tuple[bool, str]] = []
        while i < len(lines):
            mm = task_re.match(lines[i])
            if not mm:
                break
            done = mm.group(2).lower() == "x"
            items.append((done, mm.group(3)))
            i += 1
        out.append('<ul class="task-list clean">')
        for done, body in items:
            body_html = markdown.markdown(body, extensions=["attr_list"])
            body_html = re.sub(r"^<p>(.*)</p>\s*$", r"\1", body_html, flags=re.DOTALL)
            cls = "task done" if done else "task todo"
            out.append(f'  <li class="{cls}">{body_html}</li>')
        out.append("</ul>")
    return "\n".join(out)


def _table_wrap_sub(html_text: str) -> str:
    """Wrap bare <table>…</table> in <div class="table-wrap"> for mobile overflow."""
    return re.sub(
        r"(<table>.*?</table>)",
        r'<div class="table-wrap">\1</div>',
        html_text,
        flags=re.DOTALL,
    )


def render_body(md_text: str) -> str:
    md_text = _quality_sub(md_text)
    md_text = _admon_sub(md_text)
    md_text = _task_list_sub(md_text)
    html_text = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "attr_list", "def_list"],
        output_format="html5",
    )
    html_text = _table_wrap_sub(html_text)
    return html_text


# --------------------------------------------------------------------------- #
# HTML templates                                                              #
# --------------------------------------------------------------------------- #

HEAD_COMMON = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,300..600,0..100&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{css}">
<meta name="color-scheme" content="dark">
<script>const whTooltips = {{colorLinks: false, iconizeLinks: false, renameLinks: false}};</script>
<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>
</head>
<body>
<div class="shell{extra_class}">
<header class="mast">
  <a class="mast-brand" href="{root}">Pel's Raid Audit <em>codex</em></a>
  <nav class="mast-nav">{nav}</nav>
</header>
"""

FOOT_COMMON = """\
<footer class="site-foot">
  <span>Generated {gen_time}</span>
  <span>TBC Classic · Phase 1</span>
</footer>
</div>
</body>
</html>
"""


def _nav(crumbs: list[tuple[str, str]]) -> str:
    parts = []
    for i, (label, href) in enumerate(crumbs):
        if i > 0:
            parts.append('<span class="crumb-sep">/</span>')
        if href:
            parts.append(f'<a href="{html.escape(href)}">{html.escape(label)}</a>')
        else:
            parts.append(f"<span>{html.escape(label)}</span>")
    return "".join(parts)


def _rel_root_from(depth: int) -> str:
    return "../" * depth if depth > 0 else "./"


def _rel_css(depth: int) -> str:
    return _rel_root_from(depth) + "assets/styles.css"


# --------------------------------------------------------------------------- #
# Page rendering                                                              #
# --------------------------------------------------------------------------- #

META_KEY_ORDER = ("character", "realm", "spec", "faction", "professions")


def _meta_row(meta: dict) -> str:
    parts = []
    seen = set()
    for k in META_KEY_ORDER:
        v = meta.get(k)
        if not v:
            continue
        seen.add(k)
        parts.append(
            f'<dt>{html.escape(k)}</dt>'
            f'<dd class="val-{html.escape(v.lower().split()[0])}">'
            f'{html.escape(str(v))}</dd>'
        )
    skip = seen | {"title", "date"}
    for k, v in meta.items():
        if k in skip or not v:
            continue
        parts.append(
            f'<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>'
        )
    if not parts:
        return ""
    return '<dl class="report-meta">' + "".join(parts) + "</dl>"


def render_report(report: Report) -> str:
    body_html = render_body(report.body_md)
    nav = _nav([
        ("all characters", "../../index.html"),
        (report.character, "../index.html"),
        (report.date, ""),
    ])
    head = HEAD_COMMON.format(
        title=html.escape(f"{report.character} — {report.date}"),
        css=_rel_css(2),
        root=_rel_root_from(2) + "index.html",
        nav=nav,
        extra_class="",
    )
    meta_html = _meta_row(report.meta)
    header_html = (
        f'<header class="report-head">'
        f'<h1>{html.escape(report.title)}</h1>'
        f'{meta_html}'
        f'</header>'
    )
    foot = FOOT_COMMON.format(gen_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    return head + header_html + body_html + foot


def render_character_index(character: str, reports: list[Report]) -> str:
    nav = _nav([
        ("all characters", "../index.html"),
        (character, ""),
    ])
    head = HEAD_COMMON.format(
        title=html.escape(f"{character} — audit index"),
        css=_rel_css(1),
        root=_rel_root_from(1) + "index.html",
        nav=nav,
        extra_class="",
    )

    latest = reports[-1] if reports else None
    meta_line = ""
    if latest:
        bits = []
        for k in ("spec", "realm", "faction"):
            if latest.meta.get(k):
                bits.append(latest.meta[k])
        meta_line = " · ".join(bits)

    header = (
        f'<h1 class="index-title">{html.escape(character)}</h1>'
        f'<p class="index-sub">{html.escape(meta_line) if meta_line else "audit reports"}</p>'
    )

    if not reports:
        body = '<div class="empty-state">No reports yet for this character.</div>'
    else:
        cards = []
        for r in sorted(reports, key=lambda r: r.date, reverse=True):
            title = r.meta.get("title") or "Audit"
            bits = []
            for k in ("spec", "faction", "professions"):
                if r.meta.get(k):
                    bits.append(html.escape(r.meta[k]))
            sub = '<span class="pipe">·</span>'.join(bits) if bits else ""
            cards.append(
                f'<li><a class="card" href="{r.date}/">'
                f'<div class="card-head">'
                f'<span class="card-title">{html.escape(title)}</span>'
                f'<span class="card-date">{html.escape(r.date)}</span>'
                f'</div>'
                f'<div class="card-meta">{sub}</div>'
                f'</a></li>'
            )
        body = '<ul class="card-list clean">' + "".join(cards) + "</ul>"

    foot = FOOT_COMMON.format(gen_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    return head + header + body + foot


def render_root_index(characters: dict[str, list[Report]]) -> str:
    nav = _nav([("codex root", "")])
    head = HEAD_COMMON.format(
        title="Pel's Raid Audit — Codex",
        css=_rel_css(0),
        root="./index.html",
        nav=nav,
        extra_class="",
    )
    header = (
        '<h1 class="index-title">Raid Audit Codex</h1>'
        '<p class="index-sub">Weekly gear audits · Dreamscythe-US · TBC Classic Phase 1</p>'
    )

    if not characters:
        body = '<div class="empty-state">No characters with reports yet.</div>'
    else:
        cards = []
        for char, reports in sorted(characters.items()):
            latest = max(reports, key=lambda r: r.date) if reports else None
            bits = []
            if latest and latest.meta.get("spec"):
                bits.append(html.escape(latest.meta["spec"]))
            if latest and latest.meta.get("realm"):
                bits.append(html.escape(latest.meta["realm"]))
            count = f"{len(reports)} report{'s' if len(reports) != 1 else ''}"
            bits.append(count)
            sub = '<span class="pipe">·</span>'.join(bits) if bits else ""
            latest_date = latest.date if latest else ""
            date_html = (
                f'<span class="card-date">latest: {html.escape(latest_date)}</span>'
                if latest_date
                else '<span class="card-date">no reports yet</span>'
            )
            cards.append(
                f'<li><a class="card" href="{char}/">'
                f'<div class="card-head">'
                f'<span class="card-title">{html.escape(char)}</span>'
                f'{date_html}'
                f'</div>'
                f'<div class="card-meta">{sub}</div>'
                f'</a></li>'
            )
        body = '<ul class="card-list clean">' + "".join(cards) + "</ul>"

    foot = FOOT_COMMON.format(gen_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    return head + header + body + foot


# --------------------------------------------------------------------------- #
# Build                                                                       #
# --------------------------------------------------------------------------- #

def clean_generated(characters: list[str]) -> None:
    """Wipe old generated character dirs and root index."""
    for char in characters:
        d = ROOT / char
        if d.exists() and d.is_dir():
            shutil.rmtree(d)
    idx = ROOT / "index.html"
    if idx.exists():
        idx.unlink()


def build() -> None:
    reports = discover_reports()
    by_char: dict[str, list[Report]] = {}
    for r in reports:
        by_char.setdefault(r.character, []).append(r)

    # Include empty character dirs too
    for char_dir in (REPORTS_DIR.iterdir() if REPORTS_DIR.exists() else []):
        if char_dir.is_dir():
            by_char.setdefault(char_dir.name, [])

    clean_generated(list(by_char.keys()))

    for r in reports:
        r.out_path.parent.mkdir(parents=True, exist_ok=True)
        r.out_path.write_text(render_report(r), encoding="utf-8")
        print(f"  wrote {r.out_path.relative_to(ROOT)}")

    for char, rs in by_char.items():
        path = ROOT / char / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_character_index(char, rs), encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}")

    root_idx = ROOT / "index.html"
    root_idx.write_text(render_root_index(by_char), encoding="utf-8")
    print(f"  wrote {root_idx.relative_to(ROOT)}")

    if not (ASSETS_DIR / "styles.css").exists():
        print("  WARN: assets/styles.css missing")

    print(f"\nBuilt {len(reports)} report(s) across {len(by_char)} character(s).")


if __name__ == "__main__":
    build()

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
        [epic]Spiteblade[/epic]            → purple
        [rare]Sun-Gilded Shouldercaps[/rare] → blue
        [uncommon]Fel Leather Boots[/uncommon]
        [legendary]Warglaive of Azzinoth[/legendary]
        [common]Instant Poison VII[/common]
        [enchant]Enchant Gloves — Superior Agility[/enchant] → green
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
from datetime import datetime, timezone
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
    # derive character + date from path: reports/<char>/<date>.md
    character = md_path.parent.name
    date = md_path.stem
    meta.setdefault("character", character)
    meta.setdefault("date", date)
    # If front matter supplies a title, strip a leading top-level H1 from the
    # body so we don't render the same title twice. Only strips an H1 that is
    # one of the first non-blank lines (i.e. the author's attempt at a title).
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
    """[epic]foo[/epic] → <span class="q-epic">foo</span> (inline HTML)."""
    for q in QUALITIES:
        pat = re.compile(rf"\[{q}\](.+?)\[/{q}\]", re.DOTALL)
        text = pat.sub(
            lambda m, qq=q: f'<span class="q-{qq}">{m.group(1)}</span>',
            text,
        )
    return text


_ADMON_TYPES = {"note", "tip", "important", "warning", "caution", "critical", "good"}

def _admon_sub(text: str) -> str:
    """
    Collapse GitHub-style admonition blockquotes:
        > [!note] Optional title
        > body
        > more body
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
                # strip "> " or ">"
                inner = lines[i][1:]
                if inner.startswith(" "):
                    inner = inner[1:]
                body_lines.append(inner)
                i += 1
            # Render the body as markdown itself, then emit
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
    We also have to close them into an <ul class="task-list">.

    Approach: find runs of lines matching /^\s*- \[[ xX]\] / and replace with
    a single <ul> block. This lets us keep them out of the markdown parser,
    which would otherwise turn them into checkbox inputs or nothing.
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
        # collect all consecutive task lines
        items: list[tuple[bool, str]] = []
        while i < len(lines):
            mm = task_re.match(lines[i])
            if not mm:
                break
            done = mm.group(2).lower() == "x"
            items.append((done, mm.group(3)))
            i += 1
        # emit HTML
        out.append('<ul class="task-list clean">')
        for done, body in items:
            # markdown-render the body inline (allows bold, links, [epic] etc)
            body_html = markdown.markdown(
                body, extensions=["attr_list"],
            )
            # strip surrounding <p></p> if present
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
    # 1. Quality tags (do first — produces inline HTML that markdown will leave alone)
    md_text = _quality_sub(md_text)
    # 2. Admonitions
    md_text = _admon_sub(md_text)
    # 3. Task lists → raw HTML blocks
    md_text = _task_list_sub(md_text)
    # 4. Markdown → HTML
    html_text = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "attr_list", "def_list"],
        output_format="html5",
    )
    # 5. Post-process: wrap tables for horizontal scroll on mobile
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
    """Relative path to site root from a file N directories deep."""
    return "../" * depth if depth > 0 else "./"


def _rel_css(depth: int) -> str:
    return _rel_root_from(depth) + "assets/styles.css"


# --------------------------------------------------------------------------- #
# Page rendering                                                              #
# --------------------------------------------------------------------------- #

META_KEY_ORDER = ("character", "realm", "spec", "faction", "professions")

def _meta_row(meta: dict) -> str:
    """Render the metadata strip under the report H1."""
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
    # include any other meta that isn't already shown (skip title/date/raw body hints)
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
    foot = FOOT_COMMON.format(gen_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
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

    # Pull representative meta from most recent report
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
        # newest first
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

    foot = FOOT_COMMON.format(gen_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
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
        '<h1 class="index-title">The Codex</h1>'
        '<p class="index-sub">raid audits · dreamscythe-us</p>'
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
            count = f"{len(reports)} report" + ("s" if len(reports) != 1 else "")
            bits.append(count)
            sub = '<span class="pipe">·</span>'.join(bits)
            if latest:
                right = f'<span class="card-date">latest: {html.escape(latest.date)}</span>'
            else:
                right = '<span class="card-date">no reports yet</span>'
            cards.append(
                f'<li><a class="card" href="{char}/">'
                f'<div class="card-head">'
                f'<span class="card-title">{html.escape(char)}</span>'
                f'{right}'
                f'</div>'
                f'<div class="card-meta">{sub}</div>'
                f'</a></li>'
            )
        body = '<ul class="card-list clean">' + "".join(cards) + "</ul>"

    foot = FOOT_COMMON.format(gen_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    return head + header + body + foot


# --------------------------------------------------------------------------- #
# Build                                                                       #
# --------------------------------------------------------------------------- #

def clean_generated(characters: list[str]) -> None:
    """Remove previously-generated <char>/ directories so stale files don't linger."""
    for char in characters:
        d = ROOT / char
        if d.exists() and d.is_dir():
            shutil.rmtree(d)
    # Remove old root index
    idx = ROOT / "index.html"
    if idx.exists():
        idx.unlink()


def build() -> None:
    reports = discover_reports()
    by_char: dict[str, list[Report]] = {}
    for r in reports:
        by_char.setdefault(r.character, []).append(r)

    # Also ensure characters with no reports show up if reports/<char>/ exists
    for char_dir in (REPORTS_DIR.iterdir() if REPORTS_DIR.exists() else []):
        if char_dir.is_dir():
            by_char.setdefault(char_dir.name, [])

    clean_generated(list(by_char.keys()))

    # Report pages
    for r in reports:
        r.out_path.parent.mkdir(parents=True, exist_ok=True)
        r.out_path.write_text(render_report(r), encoding="utf-8")
        print(f"  wrote {r.out_path.relative_to(ROOT)}")

    # Character indexes
    for char, rs in by_char.items():
        path = ROOT / char / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_character_index(char, rs), encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}")

    # Root index
    root_idx = ROOT / "index.html"
    root_idx.write_text(render_root_index(by_char), encoding="utf-8")
    print(f"  wrote {root_idx.relative_to(ROOT)}")

    # Sanity-check assets exist
    if not (ASSETS_DIR / "styles.css").exists():
        print("  WARN: assets/styles.css missing")

    print(f"\nBuilt {len(reports)} report(s) across {len(by_char)} character(s).")


if __name__ == "__main__":
    build()

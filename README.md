# Pel's Raid Audit — Codex

A static site for hosting weekly raid-audit reports so you can share single URLs like `username.github.io/repo/pelarogue/2026-04-20/` with raid members.

---

## What you get

- **Clean URLs** — `/<character>/<date>/` resolves to a full audit page; `/<character>/` lists every report for that character; `/` lists every character.
- **Dark grimoire aesthetic** — Fraunces display serif + IBM Plex body/mono. WoW item-quality coloring on item names ([epic]purple[/epic], [rare]blue[/rare], etc.).
- **Markdown source** — authors drop a `.md` file in `reports/<character>/` and re-run the generator; all HTML pages and indexes rebuild from scratch.
- **No JS framework, no build step** beyond a single Python script.

---

## Repo structure

```
.
├── generate.py                  ← site builder (run this after adding reports)
├── assets/
│   └── styles.css               ← the whole theme
├── reports/
│   ├── pelarogue/
│   │   └── 2026-04-20.md        ← author-edited markdown source
│   └── deucepolo/
│       └── (empty)
│
├── index.html                   ← (generated) character picker
├── pelarogue/
│   ├── index.html               ← (generated) pelarogue's report list
│   └── 2026-04-20/
│       └── index.html           ← (generated) the report
└── deucepolo/
    └── index.html               ← (generated)
```

Everything outside `reports/` and `assets/` is generated. Don't hand-edit the generated HTML.

---

## GitHub Pages setup (one time)

1. Create a new repo on GitHub (public; GitHub Pages is free for public repos).
2. Push this project to the `main` branch.
3. In the repo, go to **Settings → Pages**.
4. Under **Source**, select `Deploy from a branch`.
5. Set **Branch** to `main` and **Folder** to `/ (root)`. Save.
6. Wait 30-60 seconds. Your site will be live at:
   `https://<your-username>.github.io/<repo-name>/`

Example URLs once deployed:
- Root: `https://pelsguild.github.io/raid-audit/`
- Pelarogue's reports: `https://pelsguild.github.io/raid-audit/pelarogue/`
- Today's audit: `https://pelsguild.github.io/raid-audit/pelarogue/2026-04-20/`

---

## Adding a new report

1. Write the audit as markdown in `reports/<character>/<date>.md`. Use `YYYY-MM-DD` for the filename — that's what becomes the URL slug.
2. Front matter at the top is optional but recommended:

   ```yaml
   ---
   title: Weekly Pre-Raid Gear Audit
   date: 2026-04-27
   character: Pelarogue
   realm: Dreamscythe-US
   spec: Combat 20/41/0 (Sword)
   faction: Scryer
   professions: Enchanting
   ---
   ```

   The `title` becomes the page `<h1>`. All other keys become the metadata strip under it. If you include `title`, don't also write a `# Heading` at the top of the body — the generator will strip one for you, but it's tidier not to duplicate.

3. Write the body in regular markdown. Tables, lists, code fences, blockquotes all work.
4. Run:

   ```bash
   pip install markdown              # one time
   python generate.py
   ```

5. Commit and push:

   ```bash
   git add .
   git commit -m "add 2026-04-27 pelarogue audit"
   git push
   ```

   GitHub Pages redeploys automatically.

---

## Markdown conventions for audits

### WoW item quality coloring

Wrap item/enchant names in quality tags so they render in the right color:

```markdown
[epic]Spiteblade[/epic]                  → purple
[rare]Sun-Gilded Shouldercaps[/rare]     → blue
[uncommon]Fel Leather Boots[/uncommon]   → green
[common]Instant Poison VII[/common]      → white
[legendary]Warglaive of Azzinoth[/legendary] → orange
[artifact]Thunderfury[/artifact]         → beige
[enchant]Enchant Gloves — Superior Agility[/enchant] → enchant green (mono)
```

### Task lists

GitHub-flavored task list items become rendered checkboxes:

```markdown
- [x] Done thing
- [ ] Todo thing
```

### Admonition callouts

GitHub-style `> [!note]` blockquotes get special styling:

```markdown
> [!note]
> Just noting something.

> [!warning]
> Something to watch out for.

> [!critical]
> Hard finding.
```

Supported kinds: `note`, `tip`, `warning`, `critical`, `good`.

### Regular markdown

Everything else is standard — `#`/`##`/`###` headers, `**bold**`, `_italic_`, `` `code` ``, pipe-tables, `-` bullet lists, `1.` numbered lists, `> blockquote`, `---` horizontal rule, `[link text](url)`.

---

## Local preview

Before pushing, you can preview the generated site locally:

```bash
python generate.py
python -m http.server 8000
# open http://localhost:8000
```

---

## Adding a new character

Just add a directory under `reports/`:

```bash
mkdir reports/newalt
# add reports/newalt/2026-05-01.md when ready
python generate.py
```

The character appears on the root index automatically. Characters with zero reports show as "no reports yet" placeholders — that's fine, they'll populate once you drop markdown in.

---

## Regenerating from scratch

`generate.py` always clears and rewrites the generated directories (`<character>/` and the root `index.html`). It never touches `reports/` or `assets/`. If something breaks, delete the generated HTML dirs and re-run — nothing is lost.

---

## Dependencies

- **Python 3.9+** (uses `dict[str, list]` syntax — anything Python 3.9 or newer works)
- **`markdown`** library (`pip install markdown`). Everything else is stdlib.

No Jekyll, no Node, no build tools. Runs in ~1 second for any reasonable number of reports.

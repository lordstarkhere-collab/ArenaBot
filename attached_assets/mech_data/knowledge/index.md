# Mech Arena Wiki — Knowledge Base

_Generated 2026-06-24 10:45 UTC_

Auto-generated offline mirror of https://mecharena.wiki.gg — **every page in the main namespace is included** (92 total).

| Folder | Pages | Index |
|--------|-------|-------|
| Mechs (game units) | 41 | [open](./mechs/index.md) |
| Pilots | 36 | [open](./pilots/index.md) |
| Weapons | 3 | [open](./weapons/index.md) |
| Maps | 0 | [open](./maps/index.md) |
| Game Modes | 0 | [open](./game_modes/index.md) |
| Implants (extracted from mech pages) | 51 | [open](./implants/index.md) |
| Patches | 0 | [open](./patches/index.md) |
| Meta pages (Main Page, Social Media, etc.) | 3 | [open](./meta/index.md) |
| Overview pages (Mechs, Pilots, Weapons) | 3 | [open](./overviews/index.md) |
| Mech Arena Wiki project pages | 6 | [open](./wiki/index.md) |
| Game database (Google Sheets mirror + weapon indexes) | 24 | [open](./database/index.md) |

## How this was built

1. The MediaWiki `allpages` API was queried to enumerate **every**
   page in the main namespace (currently 92).
2. Each page was fetched via the `parse` API for clean rendered HTML.
3. Navigation, ads, headers, footers and `[edit]` links were stripped.
4. The remaining HTML was converted to GitHub-flavoured Markdown.
5. Pages were sorted into folders by namespace prefix.
6. A second pass extracted structured data (categories, rarities,
   specialized implants, pilot buffs) from mech + pilot wikitext.
7. Cross-reference indexes were generated so you can browse the data
   in any dimension (by category, by rarity, by mech, etc.).

## What if the wiki adds a new page?

Re-run the downloader with `--resume`.  Newly-added pages get picked
up automatically, downloaded, and added to the right folder.


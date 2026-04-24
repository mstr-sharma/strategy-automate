---
name: Local skill bundles shipped with this repo
description: Skill bundles authored externally and kept alongside strategy-automate for contextual reference. These are not auto-registered Claude Code skills — they are extracted markdown bundles to consult when the topic matches. Read the relevant SKILL.md on demand; do not re-author the content inline.
type: reference
---

## Bundles under `skills/`

### `skills/strategy-brand/SKILL.md`
When to read: before producing any branded deliverable for Strategy (presentations, dashboards, landing pages, one-pagers, customer decks, conference materials, sales/marketing copy). Contains:
- colors (Strategy Orange `#FA660F`, grays, muted tones, approved gradients)
- logo rules (wordmark + ₿ Strategy symbol — not "Bitcoin B")
- typography, voice/tone, layout specs, CSS variable template
- valid/invalid example captions and do/don't patterns

### `skills/strategy-product-knowledge/SKILL.md`
When to read: when talking about Strategy Software / MicroStrategy / Mosaic / Auto AI Suite / Strategy One product capabilities, competitive positioning, or when producing educational / positioning / proposal content. Contains:
- current GA feature set (February 2026 release: Mosaic AI Sync, Auto Voice, MCP Direct Mosaic Access, LLM BYOE, dashboard + subscription + admin updates)
- January 2026 release (MCP support, other AI enhancements)
- Three reference files: `references/mosaic.md`, `references/ai-features.md`, `references/strategy-one.md`

## How to use these during a task

1. If the user asks for a Strategy-branded deliverable → `Read skills/strategy-brand/SKILL.md` BEFORE you draft layout/colors/copy. Cite the canonical hex/logo rules, don't guess.
2. If the user asks a product-capability question or wants educational / proposal content about Strategy/Mosaic/Auto AI → `Read skills/strategy-product-knowledge/SKILL.md` and the relevant `references/*.md` for release-dated detail.
3. Do not copy bulk sections of these skills into memory; reference them by path. Memory stays tenant-agnostic + terse; these bundles are the knowledge source.

## Registration (optional)

These are raw markdown bundles. To expose them as Claude Code Skills in the skill list, a user can:
- copy the folders into `~/.claude/skills/` (each folder becomes a skill tied to its `SKILL.md` frontmatter), OR
- package them as plugin skills under an agent plugin and install via `/plugin marketplace`.

Until registered, they are accessible only by direct `Read` — that is the expected mode for this repo.

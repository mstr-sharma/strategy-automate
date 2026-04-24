---
name: strategy-brand
description: >
  Apply Strategy brand guidelines when creating ANY visual or written deliverable for Strategy (formerly MicroStrategy, also known as Strategy.com or Strategy Inc.). Use this skill whenever the user asks for a PowerPoint, presentation, deck, slides, HTML page, website, landing page, artifact, report, one-pager, email template, banner, branded document, or any designed output — even if they don't explicitly say "branded" or "Strategy." Also triggers for: customer decks, Lightning Talk slides, conference materials, World conference assets, sales materials, marketing copy, or any content that will be shared externally under the Strategy name. This skill contains the exact colors, fonts, logo rules, voice guidelines, and layout specs needed to produce on-brand work correctly the first time.
---

# Strategy Brand Skill

## 1. Brand Identity & Positioning

**Company description:** Strategy is the world's first and largest Bitcoin Treasury Company, and the largest independent, publicly traded business intelligence company. It provides cloud-native, AI-powered enterprise analytics software and leverages Bitcoin strategy for value creation.

**Design principles:** Clean · Distinct · Adaptive · Optimistic

**Core values (B.A.E.I.U.):**
- **Bold** — courageous and innovative
- **Agile** — act thoughtfully, move quickly
- **Engaged** — show up passionately committed
- **Impactful** — focus on the outcome
- **United** — work together to win

---

## 2. Color Palette

### Primary Colors
| Name | Hex | RGB | Pantone |
|------|-----|-----|---------|
| Strategy Orange | `#FA660F` | R250 G102 B15 | 1505C |
| Black | `#000000` | R0 G0 B0 | — |
| White | `#FFFFFF` | R255 G255 B255 | — |

### Secondary Colors (Grays)
`#F2F2F2` · `#E4E4E4` · `#D2D2D2` · `#A8A8A8` · `#717171` · `#484747`

### Secondary Colors (Muted Tones)
`#B7CCD3` · `#CEC8B7` · `#D1C3C6` · `#C4BFCA` · `#D1B4A3` · `#BEC3BE`

### Official Gradients (use only as approved)
- **Orange gradient:** `#FA660F` [55%] → `#FFFFFF` [100%] (top to bottom)
- **Dark gradient:** `#000000` [69%] → `#A8A8A8` [100%] (top to bottom)

### CSS Variables Template
```css
:root {
  --color-orange: #FA660F;
  --color-black: #000000;
  --color-white: #FFFFFF;
  --color-gray-100: #F2F2F2;
  --color-gray-200: #E4E4E4;
  --color-gray-300: #D2D2D2;
  --color-gray-400: #A8A8A8;
  --color-gray-500: #717171;
  --color-gray-600: #484747;
  --font-primary: 'Inter', Arial, sans-serif;
}
```

---

## 3. Brandmark & Logo

### Rules
- Always use the wordmark **"Strategy"** combined with the custom **Strategy symbol (₿)**
- Never refer to the ₿ as the "Bitcoin B" — it is "the Strategy symbol"
- Never use the brandmark without the ₿ symbol
- Never modify, stretch, recolor, or transform the brandmark in any way
- The brandmark must always be visible and impactful

### Three Official Variants
| Variant | Appearance | Use on |
|---------|-----------|--------|
| **Primary (Black)** | Black "Strategy" wordmark | Orange backgrounds |
| **Reversed (White)** | White "Strategy" wordmark | Black/dark backgrounds |
| **Orange** | Orange "Strategy" wordmark | White/light gray backgrounds |

The ₿ symbol is a capital **B with two short vertical bars extending above and below** the letter (visually similar to the Bitcoin symbol). It appears as a superscript at the upper right of "Strategy" — smaller than the main wordmark text and raised. It is never used alone or separated from the wordmark.

**Logo files:**
- Black: `/mnt/user-data/uploads/Strategy_Brand_Mark_Black_HighRes.png`
- Orange: `/mnt/user-data/uploads/Strategy_Brand_Mark_Orange_HighRes.png`
- Reversed (white): `/mnt/user-data/uploads/Strategy_Brand_Mark_Reversed_HighRes.png`

### Safe Zones
- Minimum clear space = height of the ₿ symbol on all sides
- No text, graphics, or elements may enter this zone

### Placement & Sizing by Format
| Format | Placement | Size |
|--------|-----------|------|
| 16:9 widescreen | Top left (default); also: left center, top right, bottom right | 1/3 slide width |
| A-format (portrait) | Top left or bottom right | 1/2 format width |
| Screen/narrow | Top center, center, or bottom center | 1/2 format width |
| Wide/banner | Left, center, or right | 1/4 format width |

---

## 4. Sub-brands

### Strategy Mosaic
- Circular supergraphic of gradient orange/amber tiles
- Use Inter font; available in Primary, Horizontal, and Compact variants
- Can be standalone or paired with the Strategy brandmark
- Monochrome (black/white) versions available for varied backgrounds

### Strategy One
- Uses Inter font; incorporate Strategy brandmark alongside when feasible
- Optional tagline pill: "AI-Powered Intelligence Everywhere" (orange box)
- Custom hexagon 3D version is website-only

### Product "S" Icon
- Orange rounded square with black "S"
- Strictly for product/software contexts only — do not use as a general brand mark
- Do not create alternative color variants

### Naming Convention
- Products follow: "Strategy + [asset]" (e.g., Strategy Workstation, Strategy One)
- "Strategy One" = the platform or full product suite

---

## 5. Typography

### Fonts
| Role | Font | Fallback | Letter Spacing |
|------|------|----------|----------------|
| Primary | Inter | Arial | -2, -4 |
| Fallback | Arial | Helvetica Neue, sans-serif | -2, -4 |

Use Inter always. Use Arial only when font installation is not possible.

### Font Hierarchy
| Level | Style | Sizes |
|-------|-------|-------|
| Heading Large (lg/xl/2xl) | Inter Semi Bold | 72, 60, 48, 36, 30, 20, 16 |
| Heading Small (md/sm) | Inter Semi Bold | 60, 48, 36, 30, 20, 16, 14 |
| Body / General Copy | Inter Regular | 60, 48, 36, 30, 20, 16, 14 |

### Case Rules
- **Default:** Sentence case
- **Exception:** Initial caps for product/brand names (e.g., Strategy Mosaic, Strategy One)
- **Never:** ALL CAPS for body text

---

## 6. Brand Voice & Writing

### Voice Pillars
- **Simple** — plain, clear language; not meaningless corporate-speak
- **Bold** — speak confidently and directly; choose words with impact
- **Smart** — precise, insightful, and informed, but not arrogant

### Writing Do's
- Keep it short — cut redundancies and fluff words that muddy the message
- Always bring value back to the audience; use examples they can relate to
- People want more than technical details — connect to real-world impact
- Lead with outcomes and business impact, not features or methodology

### Writing Don'ts
- ❌ Excessive jargon — balance technical terms with clear, conversational language
- ❌ Talking only about Strategy — always frame around audience value
- ❌ Dry, boring copy — make it human and outcome-focused
- ❌ Passive voice in headlines
- ❌ Redundant filler phrases ("In order to...", "It is important to note...")

---

## 7. PowerPoint / Presentation Rules

### Format
- **Aspect ratio:** 16:9 widescreen (1920×1080px / 13.33" × 7.5")
- **Official template:** Orange/white style — see `/mnt/user-data/uploads/Strategy_PPT_Template_Orange.pdf`
- There is **no dark/black slide style** — all Strategy presentations use the orange/white template

### Brandmark Placement
- **Cover / closing / orange-bg slides:** Black Primary brandmark, top LEFT
- **White content slides:** Orange brandmark, bottom RIGHT (small)
- Always use the full "Strategy" wordmark — never the ₿ symbol alone

### Slide-by-Slide Reference

**Cover slide (orange bg with gradient):**
- Background: `#FA660F` fading to white at bottom via approved orange gradient
- Brandmark: Black, top left
- Headline: White, Inter Semi Bold, 48–72pt; one keyword can be changed to black for emphasis
- Speaker name + date: Black, bottom left
- Photo: Right side, square or portrait crop
- Footer: "Copyright © [Year] Strategy Inc. All Rights Reserved." centered, small gray

**Cover variant (split — orange left, photo right):**
- Left ~60%: Orange bg, black brandmark top left, white headline, black name/date
- Right ~40%: Full-height photo bleed

**Section / statement slide (solid orange, no image):**
- Full orange gradient bg; brandmark black, top right
- Headline: White, Inter Regular, very large; one keyword can be black

**White content slides:**
- Background: White; slide title in orange Inter Semi Bold (~28–36pt), top left
- Brandmark: Orange, bottom right; footer + slide number bottom center

**Two-column card layout:** Two gray panels; orange section headings; black bullet copy

**Icon + key point (2 or 3 column):** Orange flat icons; orange "Key Point" heading; black body

**Numbered list:** Large orange display numerals as anchors; orange key point heading; black body; optional photo on one half

**Four-point 2×2 grid:** Large orange numerals per quadrant; orange headings; black body

**Five-icon grid (3+2):** 3D dark metallic orange-glow icons; orange headings; black body

**Testimonial / quote:** Large orange open-quote mark top left; black body quote; orange speaker name; optional portrait photo right

**Agenda slide (white or orange bg):**
- Large orange numerals; black agenda topic (Inter Semi Bold); smaller black speaker name
- On orange bg: brandmark black bottom right; on white bg: brandmark orange bottom right

**Speaker bio slide:** Orange "Speakers" title; orange square corner accent over photos; orange speaker names; black title/company

**Closing / Thank You:** Full orange gradient bg, black brandmark top left, "Thank You" in white lower left

**Table slide:**
- Header row: Orange bg, white bold text
- Alternating rows: `#F2F2F2` and white
- Highlighted column option: orange fill with white text; dark gray header (`#484747`)

**Chart slide:**
- Bar charts: Primary bar orange, remaining bars gray (`#A8A8A8`)
- Donut charts: Primary segment orange, others black and muted grays; KPI value centered
- No 3D charts

### Content Rules
- **70% outcomes/results, 30% methodology**
- Max 5 bullets per slide; prefer 3
- Never start a bullet with "We" — reframe to audience benefit
- Large KPI callouts: 48pt+
- Slide titles: orange on white slides; white on orange slides
- Emphasis within title: change one keyword to black (on orange bg) or orange (on white bg)

---

## 8. HTML & Web Artifact Rules

### Layout
- Mobile-first, responsive (flexbox or CSS Grid)
- Max content width: 1200px, centered
- Minimum 24px section padding
- Alternate section backgrounds: white / `#F2F2F2`

### Components
- **CTA button:** `#FA660F` bg, white text, 8px border-radius
- **Secondary button:** Orange outline, orange text, white bg
- **Nav/header:** Black bg, white text, orange active state
- **Cards:** White bg, subtle shadow, 8px radius; orange top border on hover
- **Callout box:** 4px orange left border, `#FFF3EC` tint bg

### Typography Scale (Web)
| Element | Size | Weight |
|---------|------|--------|
| H1 | 72px (lg) / 60px (md) | Inter Semi Bold |
| H2 | 48px (lg) / 36px (md) | Inter Semi Bold |
| H3 | 30px | Inter Semi Bold |
| Body | 16–20px | Inter Regular |
| Caption | 12–14px | Inter Regular, `#717171` |

---

## 9. Imagery Guidelines

### Photography
- People in orange-lit, modern/architectural environments
- Dark sleek settings with warm orange accent lighting
- Black attire with orange accessories
- High contrast, bold, cinematic

### 3D Icons
- Dark metallic/black material with orange glow and edge lighting
- Use Strategy's 3D icon library — never generic stock clip art

### Mascot: Auto 2.0
- White/grey rounded robot with blue accent lights
- Use for AI, automation, and product-related contexts

### Technical Illustrations
- **Isometric:** For abstract concepts, system layering, platform architecture
- **Flat/hexagon:** For Strategy One specifically
- Orange as primary accent color in all illustrations

---

## 10. Event & Conference Materials

- Use "Freedom by Design" as the thematic tagline for World conference
- Lightning Talk sessions: 12 slides max, results-first narrative
- Customer decks: restructure from methodology → business impact
- Session descriptions: business problem → outcome → how
- Logistics/room materials: clean, minimal, functional

---

## 11. What to Avoid

| ❌ Never | ✓ Instead |
|----------|-----------|
| Colors outside brand palette | `#FA660F`, `#000000`, `#FFFFFF`, approved grays |
| Modifying the brandmark | Use exact approved variants only |
| Using ₿ symbol without the "Strategy" wordmark | Always use the full "Strategy" wordmark |
| Calling ₿ the "Bitcoin B" | Call it "the Strategy symbol" |
| Non-brand fonts | Inter (primary) or Arial (fallback only) |
| ALL CAPS body text | Sentence case; initial caps for product names |
| 3D charts | Bar, line, donut, or stat-box layouts |
| "S" icon outside product contexts | Use the Strategy wordmark brandmark |
| Unauthorized sub-brand color variants | Use only approved Mosaic/One variants |
| Copy that only talks about Strategy | Always frame around audience value |
| Excessive jargon | Plain, direct business language |
| Methodology-first content | Lead with outcomes and business impact |
| Unapproved gradients | Use only the two official gradients |
| Dark/black slides | Use the orange/white template |

---

## 12. Pre-Delivery Checklist

- [ ] Orange is `#FA660F` (not `#FF6200` or other approximations)
- [ ] Correct brandmark variant for background (Black on orange · White on dark · Orange on white)
- [ ] Brandmark always includes ₿ symbol with safe zone respected
- [ ] Font is Inter (or Arial fallback) — no decorative or serif fonts
- [ ] Sentence case used unless product name exception applies
- [ ] Content leads with outcomes and business impact
- [ ] Plain, direct language — no excessive jargon
- [ ] Max 5 bullets per slide; prefer 3
- [ ] Charts are flat (bar/line/stat) with orange accents
- [ ] CSS variables used for all brand colors (web artifacts)
- [ ] Mobile-responsive layout (web artifacts)

# HTML-Based Presentation / PPT Creation: Landscape Research

## 1. Major Slide Frameworks (HTML-first)

### reveal.js
| Attribute | Detail |
|---|---|
| GitHub | `revealjs/reveal.js` |
| Stars | ~67k |
| License | MIT |
| Input | HTML / Markdown / MDX |
| Export | PDF (via print), PNG, speaker notes |
| .pptx export | **No native support** — needs external tool (DeckTape→PDF, then PDF→PPTX) |

**Key Features:**
- Declarative `<section>` elements for slides, with vertical (nested) slide support
- Fragment animations (step-by-step reveals)
- Slide transitions (slide, convex, concave, zoom, fade)
- Rich plugin ecosystem (RevealNotes, RevealSearch, RevealMarkdown, RevealHighlight, RevealMath, RevealZoom, etc.)
- Speaker view with separate window
- Supports Markdown, LaTeX (MathJax/KaTeX), Mermaid diagrams
- CSS theming system with many community themes
- Touch navigation for mobile
- Can be embedded as a web component
- Works with any bundler (Vite, Webpack) or standalone via CDN

**Pros:**
- Most popular framework by far; massive community
- Excellent plugin system
- Works client-side with zero backend
- Great for embedding in web apps (SPA-friendly)

**Cons:**
- No .pptx export natively
- Requires some HTML knowledge for advanced layouts
- PDF export quality varies

**Best for:** Web-based presentations, embedding in apps, technical talks

---

### Slidev
| Attribute | Detail |
|---|---|
| GitHub | `slidevjs/slidev` |
| Stars | **46.9k** |
| License | MIT |
| Input | Markdown + Vue components |
| Export | **PDF, PNG, PPTX** ✅ |
| .pptx export | **Yes** — built-in via CLI `slidev export --format pptx` |

**Key Features:**
- Markdown-first with Vue 3 component embedding
- UnoCSS for utility-first styling
- Built-in code highlighting (Shiki + Monaco Editor for live coding)
- Drawing/annotation support (Drauu)
- LaTeX (KaTeX), Mermaid diagrams, icons (Iconify)
- Presenter mode with dual-screen support
- Built-in recording + camera view
- Hot-reload dev server (Vite-powered)
- Theme gallery with npm-packaged themes
- Shiki-based syntax highlighting

**Pros:**
- ✅ Native PPTX export — strongest selling point
- Developer-focused with excellent DX
- Vue component interactivity
- Very actively maintained (3k+ commits, v52+)
- Massive theme ecosystem

**Cons:**
- Vue 3 dependency — not framework-agnostic
- Heavier dependency tree (Vite + Vue + UnoCSS)
- PPTX export loses animations/transitions
- Overkill for simple presentations

**Best for:** Developer presentations, embedding interactive components, web-app PPT generation

---

### Marp (Markdown Presentation Ecosystem)
| Attribute | Detail |
|---|---|
| GitHub | `marp-team/marp` (meta), `marp-team/marp-cli` (CLI), `marp-team/marp-core` (core) |
| Stars | **11.9k** |
| License | MIT |
| Input | Markdown |
| Export | **HTML, PDF, PPTX, images** ✅ |
| .pptx export | **Yes** — `marp --pptx input.md` |

**Key Features:**
- Pure Markdown with Marp-specific directives (`<!-- _class: lead -->`)
- Built-in themes (default, gaia, uncover)
- Custom CSS themes
- CLI tool for headless conversion (HTML, PDF, PPTX, PNG/JPG)
- VS Code extension for live preview
- Framework-agnostic core library (`@marp-team/marp-core`)
- React and Vue renderer components (`@marp-team/marp-react`, `@marp-team/marp-vue`)
- Marpit framework (skinny slide framework underneath)

**Pros:**
- ✅ Native PPTX export via CLI (uses Puppeteer for rendering)
- Lightweight and focused
- Framework-agnostic core — works with React/Vue/vanilla
- Excellent CLI for CI/CD pipelines
- Simple learning curve (just Markdown)

**Cons:**
- Limited interactivity (no Vue/React component embedding)
- Fewer layout options than Slidev
- PPTX export renders via Puppeteer → visual fidelity depends on rendering
- Smaller theme ecosystem than Slidev

**Best for:** CI/CD slide generation, VS Code users, lightweight Markdown presentations

---

### remark.js
| Attribute | Detail |
|---|---|
| GitHub | `gnab/remark` |
| Stars | **13k** |
| License | MIT |
| Input | Markdown (in HTML `<textarea>`) |
| Export | HTML only, PDF via print/DeckTape |
| .pptx export | **No** |

**Key Features:**
- Browser-only, single-file (just include a JS file + Markdown in textarea)
- Class-based slide styling (`.center, .middle, .inverse`)
- Presenter mode with speaker notes
- Syntax highlighting
- Slide scaling for resolution independence
- Touch support

**Pros:**
- Dead simple — single HTML file, no build step
- Zero dependencies, tiny footprint
- Great for quick sharing

**Cons:**
- No export at all beyond HTML
- Limited animations
- No active development (last release v0.15.0 in 2020)
- No theming system

**Best for:** Quick throwaway presentations, embedding simple slides in existing pages

---

### impress.js
| Attribute | Detail |
|---|---|
| GitHub | `impress/impress.js` |
| Stars | **38.2k** |
| License | MIT |
| Input | HTML with data attributes |
| Export | HTML only, PDF via print |
| .pptx export | **No** |

**Key Features:**
- CSS3 3D transforms and transitions (Prezi-like zooming/panning)
- Positioning via data attributes (`data-x`, `data-y`, `data-rotate`, `data-scale`)
- Plugin system (substep, progress, autoplay, etc.)
- Supports nested slides

**Pros:**
- Visually stunning 3D/zoom presentations
- Lightweight vanilla JS
- Well-documented plugin API

**Cons:**
- No Markdown support
- No export to PDF/PPTX
- Requires significant manual positioning work
- Accessibility concerns with 3D transforms
- Less maintained in recent years

**Best for:** Artistic, non-linear presentations; visual storytelling

---

### shower.js
| Attribute | Detail |
|---|---|
| GitHub | `shower/shower` |
| Stars | **4.9k** |
| License | MIT |
| Input | HTML with classes |
| Export | **Print to PDF** (explicitly supported) |
| .pptx export | **No** |

**Key Features:**
- HTML/CSS/vanilla JS
- Two built-in themes: Ribbon and Material
- Keyboard accessible
- Print-friendly (designed for PDF export)
- CLI tool (`@shower/cli`)
- Modular: `@shower/core`, `@shower/material`, `@shower/ribbon`

**Pros:**
- Excellent print/PDF support
- Clean Material Design theme
- No framework dependencies

**Cons:**
- No Markdown support
- No PPTX export
- Smaller community
- Less flexible theming

**Best for:** Presentations where PDF output quality matters

---

## 2. HTML-to-PPTX Export Libraries

### PptxGenJS
| Attribute | Detail |
|---|---|
| GitHub | `gitbrent/PptxGenJS` |
| Stars | **5.5k** |
| License | MIT |
| Language | TypeScript |
| Output | **Native .pptx files** ✅ |

**Key Features:**
- Creates OOXML (.pptx) from scratch in JS — **not HTML conversion**
- Supports: text, tables, shapes, images, charts (bar, line, pie, scatter, etc.)
- Slide masters for consistent layouts
- Works in Node.js, React, Angular, Vite, Electron, browsers
- SVG support, animated GIFs, YouTube embeds
- `tableToSlides()` — converts HTML `<table>` to slides (closest to HTML→PPTX)
- Export as file download, base64, Blob, Buffer, or stream
- Full TypeScript definitions
- 75+ demo examples

**Pros:**
- ✅ Best option for programmatic PPTX generation
- True .pptx output (not converted)
- HTML `<table>` → slides feature
- Works everywhere (Node + browser)
- Active development (v4.0.1, June 2025)

**Cons:**
- No HTML/CSS rendering engine — you build slides programmatically
- Can't convert arbitrary HTML layouts
- Charts require data arrays (no visual rendering from HTML)
- Learning curve for complex layouts

**Best for:** Programmatic PPTX generation, data-driven reports, converting tabular data

---

### python-pptx
| Attribute | Detail |
|---|---|
| GitHub | `python-openxml/python-pptx` |
| Stars | ~11k |
| License | MIT |
| Language | Python |
| Output | **Native .pptx files** ✅ |

**Key Features:**
- Python library for creating/modifying .pptx
- Supports: text, images, tables, shapes, charts
- Template-based workflows
- Well-documented, mature

**Pros:**
- Excellent for server-side generation
- Template-based approach is practical
- Large community, good docs

**Cons:**
- Python only (not browser-compatible)
- No HTML rendering — purely programmatic
- Less feature-rich than PptxGenJS for browser use

**Best for:** Backend/server-side PPTX generation

---

### DeckTape
| Attribute | Detail |
|---|---|
| GitHub | `astefanutti/decktape` |
| Stars | ~3.5k |
| License | MIT |
| Input | Any HTML presentation |
| Output | **PDF only** ✅ |

**Key Features:**
- Generic HTML presentation to PDF exporter
- Uses Puppeteer/Headless Chrome
- Built-in adapters for: reveal.js, remark, shower, impress.js, remark.js, Slides, Slidev, Bespoke, Cleaver, Flowtime, d3.js, Ionize, deck.js, fathom.js
- Configurable slide size, margins, output file
- Automatic slide detection via scroll

**Pros:**
- Works with almost any HTML presentation framework
- High-quality PDF output
- Adapters for major frameworks

**Cons:**
- PDF only — not PPTX
- Requires Puppeteer/Chrome headless
- No PPTX conversion from PDF built-in
- Slower (renders full browser)

**Best for:** Converting any HTML presentation to PDF

---

### Other Notable Libraries

| Library | Language | Output | Notes |
|---|---|---|---|
| **officegen** | Node.js | .pptx | Older, less maintained; supports PowerPoint, Word, Excel |
| **docxtemplater** | JS/Node | .pptx | Template-based; good for mail-merge-style generation |
| **html-pptx** | JS | .pptx | Attempts direct HTML→PPTX; limited fidelity |
| **dom-to-pptx** | JS | .pptx | DOM-based conversion; experimental |
| **Puppeteer + pdf-lib** | JS | PDF | PDF manipulation after browser print |

---

## 3. CSS-Based Slide Design Approaches

### How Modern Frameworks Handle Layout

| Approach | Used By | Description |
|---|---|---|
| **CSS Custom Properties** | Slidev, reveal.js, Marp | Theme variables (`--color-primary`, etc.) for consistent theming |
| **Section-based layout** | reveal.js, impress.js | Each `<section>` or `<div>` is a slide; CSS Grid/Flexbox within |
| **Markdown + Directive classes** | Marp, Slidev | Markdown with class annotations (`<!-- _class: lead -->`) |
| **CSS Utility classes** | Slidev (UnoCSS/Tailwind) | Utility-first CSS for rapid slide styling |
| **CSS 3D transforms** | impress.js | `transform: rotateX() rotateY() translateZ()` for 3D effects |
| **CSS Print styles** | shower.js, reveal.js | `@media print` rules for PDF-friendly output |

### Theme Systems

- **reveal.js**: CSS theme files (css/theme/), transition classes, custom CSS
- **Slidev**: npm package themes, UnoCSS presets, `<style>` blocks per slide
- **Marp**: CSS theme files with Marpit directives, built-in themes (default, gaia, uncover)
- **shower.js**: CSS theme packages (@shower/material, @shower/ribbon)
- **impress.js**: Manual CSS per step (no theme system)

### Animation Approaches

| Type | Framework Support |
|---|---|
| Slide transitions | reveal.js (slide/zoom/fade/convex), Slidev (transition directive) |
| Fragment animations | reveal.js (fragment system), Slidev (v-click directive) |
| CSS transitions | All frameworks (vanilla CSS) |
| CSS keyframe animations | impress.js, reveal.js |
| Vue/React transitions | Slidev (Vue transitions), reveal.js (JS API) |

---

## 4. AI-Powered PPT Generation

### Commercial Tools

| Tool | Approach | Technical Details |
|---|---|---|
| **Gamma.app** | AI-generated slides from text prompts | LLM generates structured content → template engine renders slides. Uses proprietary design system. Exports PDF, PPTX. |
| **Beautiful.ai** | AI-assisted slide creation | Rule-based design AI (not deep learning). Auto-layout engine adjusts content. Template-driven with smart formatting. |
| **SlidesAI** | Google Slides add-on | LLM generates outline → API populates Google Slides via Apps Script. |
| **Tome** | AI storytelling | LLM generates narrative → renders in custom presentation format. |
| **Microsoft Copilot in PowerPoint** | PowerPoint integration | Uses GPT-4 + Microsoft Graph. Generates slides from documents/prompts. Direct .pptx output. |
| **Canva Magic Design** | Template + AI fill | AI suggests layouts, fills templates with content. |

### How They Work Technically

```
User Input (text/topic/document)
        ↓
   LLM Processing (GPT-4/Claude/etc.)
        ↓
   Structured Output (JSON/Slide Schema)
        ↓
   Template/Layout Engine
        ↓
   Rendering (HTML → Screenshot or Native OOXML)
        ↓
   Export (.pptx / .pdf / shareable link)
```

**Key technical patterns:**
1. **LLM → Structured JSON → Renderer**: Most common. LLM generates slide content as structured data, which a renderer maps to templates.
2. **LLM → Markdown → Marp/Slidev**: Some tools use Markdown as intermediate format.
3. **LLM → OOXML directly**: Microsoft Copilot approach — directly generates Office XML.
4. **LLM → HTML → Screenshot → PPTX**: Renders HTML in browser, screenshots each slide, embeds images in .pptx.

### Open-Source AI PPT Tools

| Tool | Stars | Approach |
|---|---|---|
| **SlidesGPT** | ~1k | LLM → HTML slides → PDF export |
| **python-pptx + OpenAI** | Various | LLM generates python-pptx code |
| **Marp + AI plugins** | Various | LLM generates Marp Markdown |

---

## 5. Print-to-PDF / Browser-Based Export

### Approach: `window.print()` + CSS `@media print`

**How it works:**
1. Render slides as HTML in browser
2. Apply `@media print` CSS to show one slide per page
3. Trigger `window.print()` → user saves as PDF

**Used by:** reveal.js, shower.js, most HTML frameworks

**Pros:**
- Zero dependencies (browser-native)
- Preserves all CSS/HTML styling exactly
- Works with any framework

**Cons:**
- User must manually save as PDF
- PDF quality depends on browser rendering
- No .pptx output
- Interactive elements lost

### Approach: Puppeteer/Playwright headless export

**How it works:**
1. Launch headless browser
2. Navigate to each slide
3. Screenshot or use `page.pdf()` 
4. Compile into PDF or embed images in .pptx

**Used by:** DeckTape, Slidev export, Marp CLI

**Pros:**
- Automatable (server-side)
- High-fidelity rendering
- Can chain into PPTX (screenshots per slide)

**Cons:**
- Requires Chrome/Chromium
- Heavy (500MB+ for Puppeteer)
- Slide detection can be imperfect
- Slower than native generation

### Approach: Canvas/SVG Screenshot → PPTX

**How it works:**
1. Render each slide in browser (DOM)
2. Use `html2canvas` or `dom-to-image` to screenshot
3. Embed screenshots in .pptx via PptxGenJS or python-pptx

**Pros:**
- Preserves visual fidelity of HTML/CSS
- Works with any HTML slide format
- Images in PPTX look like original slides

**Cons:**
- Loss of editability (images, not native PPTX elements)
- Resolution depends on screenshot DPI
- No text selection in output PPTX
- File size larger (image-based)

---

## 6. Comparison Matrix

| Framework | Stars | Input | PPTX Export | PDF Export | Interactive | Active | License |
|---|---|---|---|---|---|---|---|
| **reveal.js** | ~67k | HTML/MD/MDX | ❌ | ✅ (print) | ✅ | ✅ | MIT |
| **Slidev** | 46.9k | MD + Vue | ✅ | ✅ | ✅ | ✅ | MIT |
| **impress.js** | 38.2k | HTML | ❌ | ✅ (print) | ✅ | ⚠️ | MIT |
| **remark** | 13k | MD | ❌ | ✅ (DeckTape) | ✅ | ❌ | MIT |
| **Marp** | 11.9k | MD | ✅ | ✅ | ⚠️ | ✅ | MIT |
| **PptxGenJS** | 5.5k | JS API | ✅ (native) | ❌ | ❌ | ✅ | MIT |
| **shower** | 4.9k | HTML | ❌ | ✅ (print) | ✅ | ✅ | MIT |
| **DeckTape** | 3.5k | Any HTML | ❌ | ✅ | N/A | ✅ | MIT |

---

## 7. Recommendations for "Create PPT from HTML" Feature

### Option A: Slidev-based (Best for full-featured apps)
- Use Slidev's export API to convert Markdown → PPTX
- Pros: Native PPTX, Vue interactivity, best DX
- Cons: Vue dependency, heavy

### Option B: Marp CLI (Best for server-side generation)
- Use `@marp-team/marp-cli` to convert Markdown → PPTX
- Pros: Lightweight, CLI-friendly, framework-agnostic core
- Cons: Limited interactivity

### Option C: reveal.js + PptxGenJS (Best hybrid)
- Use reveal.js for the presentation builder UI
- Use PptxGenJS to programmatically generate .pptx from slide data
- Pros: Best presentation experience + native PPTX output
- Cons: Two libraries to maintain, manual mapping

### Option D: HTML Screenshot → PPTX (Universal fallback)
- Render slides in headless browser
- Screenshot each slide
- Embed in .pptx via PptxGenJS
- Pros: Works with ANY HTML presentation
- Cons: Image-based output, not editable

### Option E: AI-powered (Fastest for non-technical users)
- LLM generates structured slide content
- Template engine renders slides
- Export via Marp CLI or PptxGenJS
- Pros: Natural language input, fastest creation
- Cons: Less control, requires AI API costs

---

## 8. Key Technical Decision

**The fundamental tension:** HTML presentations are visual/rich but PPTX is structural/limited.

| If you need... | Use... |
|---|---|
| Editable PPTX output | PptxGenJS (programmatic) or Marp CLI |
| Visual fidelity in PPTX | Screenshot-based (Puppeteer → images → PPTX) |
| Best web presentation | reveal.js or Slidev |
| Simplest integration | Marp core library (embed in any app) |
| Server-side generation | Marp CLI or Puppeteer + DeckTape |
| AI-generated slides | LLM → JSON → PptxGenJS or Marp |

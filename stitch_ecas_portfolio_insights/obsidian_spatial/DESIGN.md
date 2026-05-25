---
name: Obsidian Spatial
colors:
  surface: '#131314'
  surface-dim: '#131314'
  surface-bright: '#3a393a'
  surface-container-lowest: '#0e0e0f'
  surface-container-low: '#1c1b1c'
  surface-container: '#201f20'
  surface-container-high: '#2a2a2b'
  surface-container-highest: '#353436'
  on-surface: '#e5e2e3'
  on-surface-variant: '#b9caca'
  inverse-surface: '#e5e2e3'
  inverse-on-surface: '#313031'
  outline: '#849495'
  outline-variant: '#3a494a'
  surface-tint: '#00dce5'
  primary: '#e9feff'
  on-primary: '#003739'
  primary-container: '#00f5ff'
  on-primary-container: '#006c71'
  inverse-primary: '#00696e'
  secondary: '#c8c6c8'
  on-secondary: '#303032'
  secondary-container: '#474649'
  on-secondary-container: '#b7b4b7'
  tertiary: '#fff9f0'
  on-tertiary: '#3a3000'
  tertiary-container: '#ffdb3f'
  on-tertiary-container: '#736000'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#63f7ff'
  primary-fixed-dim: '#00dce5'
  on-primary-fixed: '#002021'
  on-primary-fixed-variant: '#004f53'
  secondary-fixed: '#e5e1e4'
  secondary-fixed-dim: '#c8c6c8'
  on-secondary-fixed: '#1b1b1d'
  on-secondary-fixed-variant: '#474649'
  tertiary-fixed: '#ffe16c'
  tertiary-fixed-dim: '#e7c427'
  on-tertiary-fixed: '#221b00'
  on-tertiary-fixed-variant: '#544600'
  background: '#131314'
  on-background: '#e5e2e3'
  surface-variant: '#353436'
  obsidian-base: '#0A0A0B'
  charcoal-surface: '#141416'
  electric-cyan: '#00F5FF'
  crimson-risk: '#FF3B30'
  titanium-highlight: '#E2E2E2'
  glass-stroke: rgba(255, 255, 255, 0.08)
typography:
  headline-xl:
    fontFamily: Manrope
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Manrope
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Manrope
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Manrope
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Manrope
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  data-tabular:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
  headline-lg-mobile:
    fontFamily: Manrope
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 24px
  margin-page: 40px
  widget-gap: 16px
  table-row-height: 48px
---

## Brand & Style

The design system is engineered for a high-stakes fintech environment where precision meets prestige. The brand personality is **Sovereign and Analytical**, evoking the feeling of a private digital vault. It targets sophisticated investors who require high data density without the aesthetic chaos of traditional terminals.

The visual style is a fusion of **3D Glassmorphism** and **Minimalist Spatial UI**. It utilizes depth as a functional tool—moving non-essential data into a blurred background "recession" while pulling active tasks into sharp, high-contrast foreground panels. The interface should feel physically present, with modular widgets that exhibit "gravitational" behavior when moved or stacked.

## Colors

The palette is anchored in a deep, multi-layered dark mode. **Deep Obsidian** serves as the infinite canvas, while **Charcoal** defines the surface areas of interactive widgets. 

- **Primary (Electric Cyan):** Reserved for growth metrics, positive performance, and active interactive states. It should appear to "glow" against the dark background.
- **Risk (Crimson Red):** Strictly used for volatility, loss, and high-risk alerts.
- **Titanium:** A metallic grayscale used for 3D strokes, icons, and subtle textures that give elements a physical, machined quality.
- **Functional Gradients:** Use "Living" gradients (Cyan to Transparent or Red to Black) to indicate market momentum within charts and news modules.

## Typography

Typography focuses on **tabular clarity** and **sophisticated hierarchy**. We use **Manrope** for all prose and headings to maintain a modern, balanced feel. 

For financial figures, stock tickers, and technical metadata, the system switches to **JetBrains Mono**. This monospaced choice ensures that numbers align perfectly in high-density tables, preventing visual "jumping" when data updates in real-time. Headlines should use tight letter spacing to appear authoritative, while data labels use expanded tracking for legibility at small sizes.

## Layout & Spacing

This design system utilizes a **Fluid Spatial Grid** inspired by VisionOS. The layout is divided into three primary zones:
1.  **Navigation Rail (Left):** A slim, high-blur acrylic bar.
2.  **Modular Canvas (Center):** A fluid area where widgets can expand or contract based on importance.
3.  **Intelligence Engine (Right):** A fixed-width (400px) pane for AI research and deep-dive analysis.

Spacing is tight within components (4px/8px) to maximize data density, but generous between major functional blocks (24px+) to prevent cognitive overload. On mobile, the Intelligence Engine reflows into a bottom-sheet drawer, while the main canvas adopts a single-column stack.

## Elevation & Depth

Hierarchy is achieved through **Z-axis layering** rather than traditional dropshadows.
- **Level 0 (Background):** Solid Deep Obsidian.
- **Level 1 (Panels):** 3D Glassmorphism. Surfaces use a `backdrop-filter: blur(20px)` with a 1px solid Titanium stroke at 8% opacity.
- **Level 2 (Active Widgets):** Elements currently being interacted with gain a subtle "inner glow" from the top-left corner and a soft, diffused ambient shadow (0px 20px 40px rgba(0,0,0,0.5)).
- **Focus Mode:** When a specific module is selected, the rest of the UI dims and increases in blur, physically "receding" into the distance.

## Shapes

The shape language is **Structured & Refined**. We use a 0.5rem (8px) base radius for modular widgets to keep them feeling professional. Buttons and input fields use a slightly higher roundedness (12px) to signify interactability. High-radius "Pill" shapes are reserved exclusively for status chips (e.g., "Market Open") and primary Action buttons.

## Components

### High-Fidelity Data Tables
Inspired by terminal layouts, tables use a strict grid with no vertical borders. Horizontal rows are separated by a 1px Charcoal stroke. Performance columns (Price Change) should use a subtle background tint (10% Cyan or Red) to highlight the direction of movement.

### Interactive Risk Charts
Charts feature "Living" functional gradients. The area under the trend line should be filled with a gradient that reacts to the Y-axis value—shifting from Cyan at the peaks to deep Neutral at the troughs.

### Modular Widgets
Every widget is a glassmorphic container. Header areas of widgets should have a "Brushed Titanium" texture and include a drag-handle affordance.

### Buttons & Inputs
- **Primary Action:** Solid Electric Cyan with black JetBrains Mono text.
- **Ghost Input:** Transparent background with a 1px Titanium stroke. On focus, the stroke becomes Cyan and an inner glow appears.
- **Chips:** Small, pill-shaped labels with a high-contrast border and monospaced text.

### News Modules
News cards use "spatial recession"—the image is blurred and placed behind the text, only coming into sharp focus on hover to minimize visual noise during market analysis.
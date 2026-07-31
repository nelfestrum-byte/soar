---
name: Sentinel Operator Interface
colors:
  surface: '#0b1326'
  surface-dim: '#0b1326'
  surface-bright: '#31394d'
  surface-container-lowest: '#060e20'
  surface-container-low: '#131b2e'
  surface-container: '#171f33'
  surface-container-high: '#222a3d'
  surface-container-highest: '#2d3449'
  on-surface: '#dae2fd'
  on-surface-variant: '#bcc9cd'
  inverse-surface: '#dae2fd'
  inverse-on-surface: '#283044'
  outline: '#869397'
  outline-variant: '#3d494c'
  surface-tint: '#4cd7f6'
  primary: '#4cd7f6'
  on-primary: '#003640'
  primary-container: '#06b6d4'
  on-primary-container: '#00424f'
  inverse-primary: '#00687a'
  secondary: '#adc6ff'
  on-secondary: '#002e6a'
  secondary-container: '#0566d9'
  on-secondary-container: '#e6ecff'
  tertiary: '#ffb873'
  on-tertiary: '#4b2800'
  tertiary-container: '#e89337'
  on-tertiary-container: '#5b3200'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#acedff'
  primary-fixed-dim: '#4cd7f6'
  on-primary-fixed: '#001f26'
  on-primary-fixed-variant: '#004e5c'
  secondary-fixed: '#d8e2ff'
  secondary-fixed-dim: '#adc6ff'
  on-secondary-fixed: '#001a42'
  on-secondary-fixed-variant: '#004395'
  tertiary-fixed: '#ffdcbf'
  tertiary-fixed-dim: '#ffb873'
  on-tertiary-fixed: '#2d1600'
  on-tertiary-fixed-variant: '#6a3b00'
  background: '#0b1326'
  on-background: '#dae2fd'
  surface-variant: '#2d3449'
typography:
  h1:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  h2:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  h3:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  code:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  '4': 4px
  '8': 8px
  '12': 12px
  '16': 16px
  '24': 24px
  '32': 32px
  '48': 48px
  '64': 64px
---

## Brand & Style

The design system is engineered for high-stakes Security Operations Centers (SOC). The brand personality is **operator-focused, precise, and high-performance**. It prioritizes extreme information density and visual scanability over decorative elements, ensuring that analysts can identify threats and orchestrate responses without cognitive friction.

The design style follows a **Modern Corporate/Minimalist** approach with a technical edge. It utilizes a "Utility-First" aesthetic:
- **High-Density Layouts:** Reducing white space in favor of data visualization and log visibility.
- **Precision Engineering:** Sharp lines, subtle borders, and monospaced accents to evoke a sense of technical reliability.
- **Visual Stability:** Avoiding motion or transitions that could distract an operator during an incident response.

## Colors

The palette is optimized for long-duration monitoring. The **Dark Mode** is the primary interface state, using deep slate and charcoal foundations to reduce eye strain. The **Light Mode** variant maintains identical token relationships for environments with high ambient light.

### UI Layers
- **Surface Level 0:** #020617 (Deepest background)
- **Surface Level 1:** #0f172a (Primary container background)
- **Surface Level 2:** #1e293b (Hover/elevated states)

### Status Indicators
Status colors are tuned for colorblind safety and high contrast against dark backgrounds. Use these consistently for badges, progress bars, and log levels.
- **Destructive/Danger:** Reserved exclusively for critical system failures and manual termination actions.

## Typography

Typography is treated as a functional tool for data parsing. 

- **Primary Sans (Inter):** Used for all UI controls, navigation, and structured data.
- **Technical Mono (JetBrains Mono):** Used for IDs, log outputs, JSON payloads, and terminal interactions.
- **Hierarchy:** We use a compact scale. H1 is capped at 24px to preserve vertical space for dashboard widgets. 
- **Labels:** Small, uppercase labels with increased letter spacing are used for table headers and metadata categories.

## Layout & Spacing

The design system utilizes a strict **4px grid system** to achieve high-density layouts without sacrificing alignment.

### Layout Model
- **Fluid Grid:** Dashboards use a 12-column fluid grid.
- **Fixed Sidebar:** A narrow 240px sidebar maximizes the horizontal real estate for data tables and node-based workflow editors.
- **Density:** Padding inside components (like table cells and input fields) should favor 8px (X) and 4px (Y) to compress vertical height.

### Breakpoints
- **Desktop (Default):** > 1440px. Optimized for multi-monitor SOC setups.
- **Compact:** 1024px - 1439px. Sidebars collapse to icons.
- **Mobile:** Not supported for primary operations; read-only view for incident alerts only.

## Elevation & Depth

To maintain a professional and "flat" technical aesthetic, elevation is communicated through **Tonal Layering** and **Low-Contrast Outlines** rather than heavy shadows.

- **Borders:** Use 1px borders (#334155 in dark mode) to define sections.
- **Depth Levels:**
    - **Base:** The main canvas.
    - **Raised:** Cards and panels use a slightly lighter fill than the base.
    - **Overlay:** Modals and dropdowns use a subtle 4px blur backdrop and a sharp 1px border to separate from the background.
- **Shadows:** Only used for floating overlays (modals/tooltips). Use a tight, 8px blur with 40% opacity of the background color.

## Shapes

The shape language is **precise and utilitarian**. 

- **Standard Radius:** 4px for most interactive elements (buttons, inputs, checkboxes).
- **Container Radius:** 8px for cards and primary panels to provide a subtle visual hierarchy.
- **Strict Square:** Data grid cells and header bars use 0px radius to emphasize the "grid" nature of the operations console.

## Components

### Buttons
- **Primary:** Solid Cyan (#06b6d4) with dark text. 
- **Ghost/Secondary:** 1px border with transparent background.
- **States:** Hover adds a 10% white overlay; Active (Pressed) adds a 10% black overlay. Focus-visible uses a 2px Cyan ring with a 2px offset.

### Data Tables
- **High Density:** 32px row height.
- **Striping:** Subtle alternating row backgrounds (#1e293b at 20% opacity).
- **Sort Indicators:** Use Chevron-up/down icons; primary color when active.

### Inputs
- **Default:** Dark background (#0f172a), 1px border (#334155).
- **Focus:** 1px Cyan border with no outer glow.
- **Monospace:** Use JetBrains Mono for inputs containing IDs, IPs, or scripts.

### Status Badges
- Small, pill-shaped (rounded-xl).
- Use a "Dot" indicator of the status color alongside the label for maximum accessibility.
- Backgrounds should be 10-15% opacity of the status color.

### Workflow Nodes
- Used in the SOAR playbook editor.
- Rectangular with 4px radius. 
- Left-side color-coding based on action type (Logic, Integration, Manual).
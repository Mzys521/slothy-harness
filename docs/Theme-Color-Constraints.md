# Slothy Theme Color Constraints

> **Document Type:** Core Brand Color Specification  
> **Version:** v1.0  
> **Status:** Stable  
> **Applies To:** All Slothy / 思洛 series projects, including Harness, Desktop, Mobile, CLI, Docs, Website, Cloud, and future products.

---

## 1. Purpose

This document defines the mandatory theme color system for all **Slothy / 思洛** products.

The following three colors are the permanent core brand colors:

| Token | Name | HEX | Role |
|---|---|---|---|
| `slothy.green` | Slothy Green | `#60DD06` | Primary / Action / Growth |
| `slothy.cream` | Slothy Cream | `#FCEAC9` | Warmth / Friendly Surface |
| `slothy.brown` | Slothy Brown | `#95611F` | Brand Identity / Nature / Stability |

These values MUST NOT be changed by individual projects.

---

## 2. Brand Principle

> **Green is action.**  
> **Cream is warmth.**  
> **Brown is identity.**  
> **Neutral is information.**

中文定义：

- 绿色负责行动
- 奶油色负责温度
- 棕色负责品牌
- 黑白灰负责信息

---

## 3. Constraint Levels

| Keyword | Meaning |
|---|---|
| **MUST** | Mandatory |
| **MUST NOT** | Forbidden |
| **SHOULD** | Recommended unless there is a justified design reason |
| **MAY** | Optional |

---

# 4. Core Brand Colors

## 4.1 Slothy Green

```text
Name: Slothy Green
HEX:  #60DD06
RGB:  96, 221, 6
Role: Primary Brand / Action
```

### MUST be used for

- Primary Button
- Active State
- Selected State
- Agent Running State
- Progress Indicator
- Toggle Active
- Focus Accent
- Primary CTA
- Logo Leaf
- Core Brand Highlight

### Semantic meaning

```text
Action
Growth
Future
Running
Progress
Alive
```

### Restrictions

`#60DD06` MUST NOT be used as a large-area page background.

`#60DD06` MUST NOT be used for long-form body text.

White text MUST NOT be placed on `#60DD06`.

Preferred button combination:

```text
Background: #60DD06
Text:       #111210
```

---

## 4.2 Slothy Cream

```text
Name: Slothy Cream
HEX:  #FCEAC9
RGB:  252, 234, 201
Role: Brand Surface / Warm Surface
```

### Recommended use

- Welcome Page
- Empty State
- Brand Surface
- Selected Sidebar Background
- Agent Tips
- Information Card
- Documentation Highlight
- Soft Notice Area
- Logo Presentation Background

### Semantic meaning

```text
Warmth
Humanity
Calm
Friendly
Equality
```

Preferred combination:

```text
Background: #FCEAC9
Text:       #111210
```

Cream SHOULD NOT be used as the only full-page background across the entire product.

---

## 4.3 Slothy Brown

```text
Name: Slothy Brown
HEX:  #95611F
RGB:  149, 97, 31
Role: Secondary Brand / Natural Identity
```

### Recommended use

- Brand Decoration
- Logo Auxiliary Color
- Secondary Brand Accent
- Illustration
- Badge
- Brand Heading
- Natural Visual Elements

### Semantic meaning

```text
Nature
Trust
Stability
Earth
Foundation
Identity
```

Brown MUST NOT become the main information color of the product UI.

The following pattern is discouraged:

```text
Brown Heading
+
Brown Body Text
+
Brown Border
+
Brown Button
```

Slothy is a developer-tool brand, not a food, café, or lifestyle brand.

---

# 5. Color Priority

```text
                    GREEN
                     │
                   Action
                     │
CREAM ─────────── SLOTHY ─────────── BROWN
Warmth                                Brand
                     │
                  NEUTRAL
                     │
                Information
```

Mandatory semantic mapping:

```text
Primary        = #60DD06
Brand Surface  = #FCEAC9
Secondary      = #95611F
```

Projects MUST NOT swap these semantic roles arbitrarily.

---

# 6. Recommended Visual Weight

Recommended product-level color distribution:

| Color Group | Recommended Weight |
|---|---:|
| Neutral / Black / White / Gray | 65–75% |
| Cream | 10–20% |
| Brown | 5–10% |
| Green | 3–8% |

This is a visual-weight guideline, not a strict pixel quota.

Core rule:

> **The less Green is used, the more meaningful Green becomes.**

---

# 7. Neutral Color System

Neutral colors carry product information and interface hierarchy.

| Token | HEX | Usage |
|---|---|---|
| `neutral.950` | `#111210` | Primary text / Dark background |
| `neutral.900` | `#1E201D` | Dark card |
| `neutral.700` | `#464841` | Strong secondary text |
| `neutral.600` | `#68645D` | Secondary text |
| `neutral.400` | `#AAA99F` | Muted text |
| `neutral.200` | `#E7E3DA` | Border |
| `neutral.100` | `#F2F1ED` | Secondary surface |
| `neutral.50` | `#FAFAF8` | Light background |
| `white` | `#FFFFFF` | Card / Pure surface |

Default text colors:

```text
Primary Text:   #111210
Secondary Text: #68645D
Muted Text:     #AAA99F
Border:         #E7E3DA
```

---

# 8. Green Scale

The brand center MUST remain `#60DD06`.

```css
--slothy-green-50:  #F2FFE8;
--slothy-green-100: #E2FFC9;
--slothy-green-300: #9CEF61;
--slothy-green-500: #60DD06;
--slothy-green-600: #51C000;
--slothy-green-700: #409A00;
--slothy-green-800: #2D7000;
--slothy-green-900: #204D00;
```

Usage guidance:

```text
50–100   Soft backgrounds / selected surfaces
500      Primary action / brand / running state
600–700  Hover / pressed
800–900  Dark green text on light backgrounds
```

---

# 9. Brown Scale

```css
--slothy-brown-500: #95611F;
--slothy-brown-600: #7C5018;
--slothy-brown-700: #6F4512;
--slothy-brown-800: #633D0F;
```

The official brand Brown MUST remain:

```text
#95611F
```

For small text on Cream surfaces, darker Brown variants SHOULD be preferred.

---

# 10. Light Theme

```css
:root {
  --brand-primary: #60DD06;
  --brand-cream: #FCEAC9;
  --brand-brown: #95611F;

  --background-primary: #FAFAF8;
  --background-secondary: #F2F1ED;
  --surface-primary: #FFFFFF;
  --surface-brand: #FCEAC9;

  --text-primary: #111210;
  --text-secondary: #68645D;
  --text-muted: #AAA99F;

  --border-primary: #E7E3DA;

  --action-primary: #60DD06;
  --action-primary-hover: #51C000;
  --action-primary-active: #409A00;
  --action-primary-text: #111210;
}
```

Recommended structure:

```text
Application
├── Main Background   #FAFAF8
├── Card              #FFFFFF
├── Brand Surface     #FCEAC9
├── Primary Action    #60DD06
└── Brand Accent      #95611F
```

---

# 11. Dark Theme

Dark Mode MUST preserve the same brand colors.

```css
[data-theme="dark"] {
  --brand-primary: #60DD06;
  --brand-cream: #FCEAC9;
  --brand-brown: #95611F;

  --background-primary: #111210;
  --background-secondary: #181A17;
  --surface-primary: #1E201D;
  --surface-secondary: #252822;

  --text-primary: #F5F4EF;
  --text-secondary: #AAA99F;
  --text-muted: #777A70;

  --border-primary: #30332D;

  --action-primary: #60DD06;
  --action-primary-hover: #51C000;
  --action-primary-text: #111210;
}
```

---

# 12. Button Rules

## Primary Button

```text
Background: #60DD06
Text:       #111210
Hover:      #51C000
Pressed:    #409A00
```

White text on the Primary Button is forbidden.

## Secondary Button

Recommended:

```text
Background: transparent / neutral
Border:     neutral
Text:       primary text
```

Brown SHOULD NOT be the global default Secondary Button color.

---

# 13. Semantic State Colors

Brand colors and system semantic colors MUST remain separate.

## Running / Success

Slothy Green MAY be used for:

```text
Running
Completed
Connected
Ready
```

Color MUST NOT be the only status indicator. Use text, icon, or shape together with color.

## Error

Error MUST use a dedicated error color.

Brown MUST NOT be used as a replacement for red.

## Warning

Warning SHOULD use a dedicated warning color.

Cream MUST NOT automatically represent every warning state.

## Information

Information states MAY use a dedicated blue.

> Brand colors define identity.  
> Semantic colors define system meaning.

---

# 14. Agent State Mapping

Recommended Agent state mapping:

```text
IDLE               Neutral
THINKING           Neutral / subtle Green
RUNNING            #60DD06
WAITING_TOOL       Neutral
WAITING_APPROVAL   Warning
SUCCESS            #60DD06
FAILED             Error
CANCELLED          Neutral
```

`● Running` SHOULD become one of the most recognizable uses of Slothy Green.

---

# 15. Logo Color Rules

Slothy Logo system includes:

```text
Sloth
+
Leaf
+
Slothy
+
思洛
```

## Full Color

Recommended for:

- Website
- README
- About
- Splash
- Marketing
- Documentation

Leaf MUST use:

```text
#60DD06
```

## Light Surface Wordmark

```text
Text:       #111210
Leaf:       #60DD06
Background: transparent
```

## Dark Surface Wordmark

```text
Text:       #FFFFFF
Leaf:       #60DD06
Background: transparent
```

## Monochrome

Allowed:

```text
100% Black
```

or

```text
100% White
```

Recommended for:

- Engraving
- Embossing
- One-color print
- Watermark
- CLI documentation

---

# 16. Logo Prohibitions

The following are forbidden:

- Changing the official Green value
- Changing the leaf to blue, purple, red, etc.
- Random gradients
- Neon glow
- Arbitrary project-specific recoloring
- Replacing the brand wordmark color outside approved Black / White / Full Color variants
- Modifying brand colors to fit a local page theme

---

# 17. Gradient Rules

Slothy's core visual language is:

```text
Flat
Natural
Clear
```

Gradients MAY be used as secondary decoration only.

The following MUST NOT become the primary brand gradient:

```text
#60DD06 → #95611F
```

Core brand elements SHOULD prefer solid colors.

---

# 18. Shadow Rules

Hierarchy SHOULD primarily rely on:

```text
Surface
Border
Spacing
```

instead of heavy shadows.

The following are discouraged:

- Green glow
- Brown glow
- High-saturation neon shadows

---

# 19. Border Rules

Light Mode:

```text
Default Border: #E7E3DA
Active Border:  #60DD06
```

Dark Mode:

```text
Default Border: #30332D
Active Border:  #60DD06
```

Brown MUST NOT become the global default border color.

---

# 20. Typography Color Rules

## Light Theme

```text
Primary:   #111210
Secondary: #68645D
Muted:     #AAA99F
```

## Dark Theme

```text
Primary:   #F5F4EF
Secondary: #AAA99F
Muted:     #777A70
```

Green and Brown MUST NOT be used for long-form body text.

---

# 21. Accessibility

All formal Slothy products SHOULD target WCAG AA.

General targets:

```text
Normal Text: ≥ 4.5 : 1
Large Text:  ≥ 3 : 1
```

Forbidden:

```text
White Text
on
#60DD06
```

Recommended:

```text
#111210
on
#60DD06
```

Recommended:

```text
#111210
on
#FCEAC9
```

---

# 22. Cross-Project Consistency

The following products MUST share the same core brand system:

```text
Slothy Harness
Slothy Desktop
Slothy Mobile
Slothy CLI
Slothy Cloud
Slothy Docs
Slothy Website
```

Projects MUST NOT use different primary brand colors such as:

```text
Harness = Green
Desktop = Blue
Mobile = Purple
Cloud = Cyan
```

Product differentiation SHOULD come from:

```text
Layout
Iconography
Typography
Interaction
Illustration
Information Architecture
```

not from replacing the core brand colors.

---

# 23. Sub-Brand Rules

Future sub-products MAY introduce auxiliary colors, but:

```text
Primary Brand Color = #60DD06
```

MUST remain unchanged.

Brand hierarchy:

```text
                Slothy
                   │
        ┌──────────┼──────────┐
        │          │          │
     Desktop     Mobile     Harness
        │          │          │
        └──────────┼──────────┘
                   │
              Same Core Colors
```

---

# 24. Official Design Tokens

```css
:root {
  /* ========================================
     Slothy Core Brand Colors
     DO NOT MODIFY
     ======================================== */

  --slothy-green: #60DD06;
  --slothy-cream: #FCEAC9;
  --slothy-brown: #95611F;

  /* Neutral */

  --slothy-black: #111210;
  --slothy-dark: #1E201D;
  --slothy-gray-700: #464841;
  --slothy-gray-600: #68645D;
  --slothy-gray-400: #AAA99F;
  --slothy-gray-200: #E7E3DA;
  --slothy-gray-100: #F2F1ED;
  --slothy-off-white: #FAFAF8;
  --slothy-white: #FFFFFF;

  /* Green Scale */

  --slothy-green-50: #F2FFE8;
  --slothy-green-100: #E2FFC9;
  --slothy-green-300: #9CEF61;
  --slothy-green-500: #60DD06;
  --slothy-green-600: #51C000;
  --slothy-green-700: #409A00;
  --slothy-green-800: #2D7000;
  --slothy-green-900: #204D00;

  /* Brown Scale */

  --slothy-brown-500: #95611F;
  --slothy-brown-600: #7C5018;
  --slothy-brown-700: #6F4512;
  --slothy-brown-800: #633D0F;
}
```

---

# 25. Semantic Token Layer

Projects SHOULD use semantic tokens instead of consuming raw HEX values directly.

```css
:root {
  --color-brand: var(--slothy-green);
  --color-brand-secondary: var(--slothy-brown);
  --color-brand-surface: var(--slothy-cream);

  --color-bg: var(--slothy-off-white);
  --color-surface: var(--slothy-white);

  --color-text: var(--slothy-black);
  --color-text-secondary: var(--slothy-gray-600);

  --color-border: var(--slothy-gray-200);

  --color-action: var(--slothy-green);
  --color-action-text: var(--slothy-black);
}
```

Recommended architecture:

```text
Slothy Brand Tokens
        ↓
Semantic Tokens
        ↓
Component Tokens
        ↓
Components
```

Avoid:

```text
Component
↓
Hard-coded HEX
```

---

# 26. Hard-Coding Rule

Production code SHOULD NOT repeatedly use:

```css
background: #60DD06;
```

Prefer:

```css
background: var(--slothy-green);
```

Equivalent token systems SHOULD be created for:

- React
- Tailwind CSS
- Vue
- Flutter
- Android
- Desktop
- Tauri
- Native applications

---

# 27. Forbidden Practices

The following violate the Slothy Theme Color Specification:

1. Changing `#60DD06`
2. Changing `#FCEAC9`
3. Changing `#95611F`
4. Setting another color as the global Primary Brand Color
5. Using white text on `#60DD06`
6. Overusing Green as a large background
7. Using Green for long body text
8. Using Brown for long body text
9. Giving each Slothy project a new independent brand palette
10. Adding arbitrary gradients or glow effects to the Logo
11. Using color as the only state indicator
12. Scattering hard-coded brand HEX values throughout production code
13. Turning Brown into the main developer-tool UI color
14. Changing the brand Green in Dark Mode
15. Changing the Logo leaf color between products

---

# 28. Release Checklist

Before release, every Slothy UI SHOULD verify:

```text
□ Primary remains #60DD06
□ Cream remains #FCEAC9
□ Brown remains #95611F

□ Primary buttons use dark text
□ Green is not overused

□ Body text primarily uses neutral colors
□ Brown is limited to brand-supporting roles

□ Light and Dark themes preserve brand identity
□ Logo uses an approved color variant

□ No unauthorized new primary brand color exists
□ Brand colors are tokenized instead of scattered as hard-coded HEX values

□ Text contrast meets accessibility targets
□ Status information is not represented by color alone
```

---

# 29. Permanent Brand Constants

Starting from **Slothy Theme Color Constraints v1.0**, the following values are treated as brand constants:

```text
Slothy Green
#60DD06

Slothy Cream
#FCEAC9

Slothy Brown
#95611F
```

These values MUST NOT be modified because of:

- Product type
- Developer preference
- Frontend framework
- Light / Dark Mode
- Individual design mockups
- Local visual preference

Only a formally approved future major version of the Slothy Brand Specification may redefine these constants.

---

## Final Rule

> **Slothy Green defines action.**  
> **Slothy Cream defines warmth.**  
> **Slothy Brown defines identity.**  
> **Neutral colors define information.**

This color system is the shared visual foundation for the entire **Slothy / 思洛** product family.

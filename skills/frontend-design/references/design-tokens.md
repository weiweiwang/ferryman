# Design Token Quick Reference

## OKLCH Color Recipes

### Dark Theme (Dashboard / Dev Tool)
```css
@theme {
  --color-bg:           oklch(0.13 0.01 260);
  --color-surface:      oklch(0.18 0.015 260);
  --color-surface-alt:  oklch(0.22 0.015 260);
  --color-border:       oklch(0.30 0.01 260 / 0.15);
  --color-text:         oklch(0.93 0.01 260);
  --color-text-muted:   oklch(0.55 0.02 260);
  --color-accent:       oklch(0.75 0.18 165);  /* teal */
}
```

### Light Theme (Content / Editorial)
```css
@theme {
  --color-bg:           oklch(0.98 0.005 80);
  --color-surface:      oklch(1.00 0 0);
  --color-surface-alt:  oklch(0.96 0.008 80);
  --color-border:       oklch(0.85 0.01 80 / 0.3);
  --color-text:         oklch(0.18 0.02 260);
  --color-text-muted:   oklch(0.45 0.02 260);
  --color-accent:       oklch(0.55 0.22 270);  /* deep violet */
}
```

### Warm Theme (Luxury / Organic)
```css
@theme {
  --color-bg:           oklch(0.97 0.01 60);
  --color-surface:      oklch(0.99 0.005 60);
  --color-surface-alt:  oklch(0.94 0.015 50);
  --color-border:       oklch(0.80 0.03 50 / 0.2);
  --color-text:         oklch(0.20 0.03 40);
  --color-text-muted:   oklch(0.50 0.04 40);
  --color-accent:       oklch(0.60 0.18 30);   /* terracotta */
}
```

## Font Pairing Recipes

| Style | Display | Body |
|---|---|---|
| Editorial | Instrument Serif | Geist |
| Dashboard | DM Mono | DM Sans |
| Luxury | Cormorant Garamond | Outfit |
| Brutalist | Clash Display | Space Mono |
| Organic | Fraunces | Nunito Sans |
| Tech | Syne | Source Sans 3 |
| Modern | Cabinet Grotesk | General Sans |

## Easing Functions

```css
/* Standard (Material) - most UI interactions */
--ease-standard: cubic-bezier(0.4, 0, 0.2, 1);

/* Decelerate (Enter) - elements appearing */
--ease-enter: cubic-bezier(0, 0, 0.2, 1);

/* Accelerate (Exit) - elements leaving */
--ease-exit: cubic-bezier(0.4, 0, 1, 1);

/* Spring (Apple-like) - playful, organic animations */
--ease-spring: cubic-bezier(0.22, 1, 0.36, 1);

/* Dramatic (Hero animations) */
--ease-dramatic: cubic-bezier(0.16, 1, 0.3, 1);
```

## Noise Texture (Inline SVG for Grain Overlay)

```css
.grain::after {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: 0.03;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
}
```

## Glass Effect (Reusable Class)

```css
.glass {
  background: oklch(0.20 0.01 260 / 0.6);
  backdrop-filter: blur(12px) saturate(180%);
  border: 1px solid oklch(1 0 0 / 0.08);
}
```

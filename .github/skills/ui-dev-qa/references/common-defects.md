# Common small UI defects (the ones QA catches)

These are the defects that make an app feel amateurish even when the design is
good. `qa-ui.mjs` catches the starred ones automatically. Check the rest by
looking at the screenshots and by reading your own diff.

## Spacing and alignment
- Two controls with no gap between them (buttons, badges, header items) *
- Padding differs between cards or rows that should match
- Gaps off the spacing scale (13px, 6px, 10px) *(warning)*
- Icon and text not vertically centered; icon size differs between sibling buttons
- Buttons in one row with different heights or radii
- Labels and their inputs separated by inconsistent gaps
- Content touching a container edge (no inner padding)

## Overflow and sizing
- Page-level horizontal scrollbar *
- Elements extending past the viewport *
- Text cut off with no ellipsis, tooltip, or wrap *
- Long unbroken strings (filenames, URLs, hashes) breaking the layout
- Nested scroll areas producing double scrollbars
- Modals taller than a 768px-high viewport with no internal scroll
- Large empty areas below content at tall viewports; content crammed at short ones
- Images stretched out of their aspect ratio *; broken images *

## States people forget
- Empty, loading, error, and disabled states
- Hover, active, focus-visible (a focus ring clipped by `overflow:hidden` counts)
- Very long titles, 50+ items, zero items, a single item
- Layout shift when data arrives (use skeletons or reserved space)
- Success/failure feedback after an action (toast or inline), and where the UI lands afterward

## Consistency
- One primary button style per context; destructive actions styled and confirmed
- The same thing called the same name everywhere (labels, headers, buttons)
- Raw data shown to users: ids, hashes, enum keys, ISO timestamps, JSON
- Mixed date, number, and unit formats

## Accessibility basics
- Icon-only buttons without aria-label or tooltip *
- Form fields without labels *
- Contrast failures (axe, if installed) *
- Click targets under about 24px *(warning)*
- Tab order that doesn't match the visual order; Esc doesn't close modals

## Layering
- Dropdowns or tooltips clipped by a parent or hidden behind another layer
- Sticky headers covering content or anchors
- Text on images or colored backgrounds without enough contrast

# CaseOps app icons

These icons reuse the three document-outline paths from the existing website
mark in `apps/web/components/marketing/Logo.tsx` and its dark `#0b1220` palette.
No external artwork or new trademark is introduced.

`app-icon.png` is an opaque 1024×1024 iOS/store icon. Android uses the transparent
1024×1024 `app-icon-foreground.png` over the same solid background; the smaller
central glyph leaves room for adaptive masks. The white foreground also serves
as the monochrome layer. Platform launchers apply their own corner masks.

Regenerate from the repository root with its pinned Node runtime and installed
root dependency graph:

```sh
node scripts/mobile/generate-app-icons.mjs
```

The generator validates dimensions and alpha channels before writing the checked-in
SVG/PNG pairs. Store screenshots and signed archive inspection remain separate.

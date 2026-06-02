# VALERI — web

The owner command dashboard (React 19 + TypeScript + Vite + Tailwind v4 + shadcn/ui).

Built to [`docs/ui-design.md`](../../docs/ui-design.md) (tokens/anatomy) and
[`docs/frontend-spec.md`](../../docs/frontend-spec.md) (components/screens/build order).
M0 ships the toolchain shell only; the dashboard screens land in M8.

```bash
npm ci            # install (lockfile)
npm run dev       # dev server, proxies /api → localhost:8000
npm run build     # production bundle
npm run lint      # eslint
```

Conventions: semantic token classes only (`bg-surface`, `text-text-2`, `shadow-card`) —
never raw hex in components; Bosnian strings via the i18n layer (from M8); **no
`localStorage`/`sessionStorage`**.

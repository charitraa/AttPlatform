# ATT Platform — Frontend

React 19 · TypeScript · Vite · Tailwind CSS v4 · shadcn/ui (Base UI) · TanStack Query ·
Zustand · React Router · React Hook Form + Zod · Recharts · Lucide.

```bash
pnpm install
pnpm dev          # http://localhost:5173; proxies /api and /ws to VITE_DEV_PROXY_TARGET (default :8000)
pnpm test         # Vitest + Testing Library + MSW
pnpm typecheck
pnpm lint
pnpm build
```

## Structure

```text
src/
├── app/            router and providers
├── components/
│   ├── ui/         shadcn/ui primitives (generated; add more with `pnpm dlx shadcn@latest add <name>`)
│   ├── layout/     app shell: sidebar, top bar, theme menu
│   └── common/     page header, empty/error states, status indicators
├── config/         navigation (also defines which phase delivers each module)
├── features/       one folder per domain feature (pages, hooks, components)
├── lib/
│   ├── api/        fetch client (backend error envelope → ApiError), query client, typed endpoints
│   └── realtime/   WebSocket hooks
├── pages/          generic pages (not found, route error, unbuilt module)
├── stores/         Zustand stores (theme, UI)
└── test/           test setup, MSW server and fixtures, render helpers
```

## Conventions

- All server data goes through TanStack Query hooks in `lib/api/*` or `features/*/api.ts`.
  Responses are validated with Zod schemas, so a contract mismatch fails loudly.
- Never hardcode metrics or fake data. A module that hasn't shipped yet renders
  `ModulePage`, which says so plainly.
- `VITE_*` variables are public. Never put secrets in them.
- After running `shadcn add`, check the generated imports. The CLI once emitted
  `import { cn } from "cn"` (an unrelated npm package) instead of `@/lib/utils`.

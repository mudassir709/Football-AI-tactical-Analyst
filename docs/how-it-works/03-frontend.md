# How it works: the React frontend

The dashboard is a single-page application: the browser loads one HTML page
once, and React swaps the content as the user moves between pages, without
full reloads.

## Technologies

| Tool | What it does here |
|---|---|
| React | Builds the interface from components (functions that return UI) |
| TypeScript | Catches mistakes such as misspelled fields before the code runs |
| Vite | Development server with instant reload; builds the production bundle |
| Tailwind CSS | Styling through short class names (`p-4`, `text-lg`, `bg-slate-900`) |
| React Router | Maps URLs (`/upload`, `/matches/:id`) to pages |
| Socket.IO client | Receives live progress updates from the API |

## Files

| File | Role |
|---|---|
| `src/main.tsx` | Starts React and wraps the app in the router and login provider |
| `src/App.tsx` | Which page belongs to which URL |
| `src/api.ts` | Every call to the backend, plus upload with progress |
| `src/auth.tsx` | Remembers the logged-in user and offers login/register/logout |
| `src/useMatchUpdates.ts` | Opens the WebSocket and reports match updates |
| `src/types.ts` | The shape of data received from the API |
| `src/components/Layout.tsx` | Header and navigation; redirects visitors who are not logged in |
| `src/components/ui.tsx` | Shared buttons, cards, badges, progress bars |
| `src/pages/*.tsx` | Login/register, match list, upload, match detail |

## Key React ideas used

- **Component**: a function returning what part of the page looks like,
  e.g. `MatchCard` draws one match in the list.
- **State** (`useState`): values that change while the page is open, such as
  form fields or the list of matches. Updating state redraws the component.
- **Effect** (`useEffect`): code that runs after a component appears, e.g.
  loading the match list from the API.
- **Context** (`AuthProvider` / `useAuth`): shares the logged-in user with
  every component without passing it through each level.
- **Hook**: reusable component logic whose name starts with `use`, like
  `useMatchUpdates`.

## How live progress reaches the screen

1. The Python worker reports progress to the queue.
2. The API writes it to the database and emits `match:updated` on the
   WebSocket to that user's private room.
3. `useMatchUpdates` receives it; the match list or match page replaces the
   old match object with the new one, and React redraws the progress bar.

Updates for one match are processed strictly in order on the server, so the
progress bar never jumps backwards.

## Running it

```bash
cd frontend
npm install     # first time only
npm run dev     # http://localhost:5173 (API and WebSocket are proxied to :4000)
```

## Analysis modes

| Mode | Frames | Detection resolution | Pitch model | 3 s test clip |
|---|---|---|---|---|
| Standard | every 2nd | 1280 px | every 3rd analysed frame | ~150-220 s |
| Quick | every 5th | 960 px | every 2nd analysed frame | ~45-75 s |

Running the pitch model on fewer frames and reusing the nearest homography
changed player positions by only 0.16 m on average (95th percentile 0.58 m)
on the 30-second sample clip.

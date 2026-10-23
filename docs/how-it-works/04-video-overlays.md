# How it works: interactive video overlays

The match page draws the analysis directly on top of the playing video:
player markers, movement paths, heatmaps, team shapes and the ball, plus a
2D tactical board that moves in sync.

## Layers

| Layer | What it shows | Drawn from |
|---|---|---|
| Players | Team-coloured ellipse at each player's feet, ID label | Detection boxes (image pixels) |
| Movement paths | Each player's route over the last 4 seconds, fading with age | Pitch positions, projected into the current frame |
| Team shape | Area enclosed by each team's outfield players (compactness) | Players' feet in the current frame |
| Heatmap | Where a team or the ball spent its time, painted on the grass | Heatmap grid in pitch metres, projected into the frame |
| Ball | Marker above the ball plus a short trail | Ball detection and pitch positions |

Clicking a player (on the video or the board) opens a panel with their
personal heatmap, full path, distance covered, time visible and speeds.

## Keeping overlays glued to the grass while the camera moves

Broadcast cameras pan and zoom constantly. A path drawn from where a player
appeared in *earlier* frames would slide across the screen as the camera
moves. Instead:

1. The worker stores every position in **pitch metres** (camera-independent).
2. For every analysed frame it also stores the **pitch → image homography**
   (a 3x3 matrix, field `h` in the results file).
3. When drawing, the dashboard projects pitch positions into the *current*
   frame using that frame's matrix. A path from 4 seconds ago is therefore
   drawn where that patch of grass is *now*.

The exported matrices reproduce the original foot positions to within
0.001 px.

## Frame-accurate synchronisation

- The worker re-encodes every upload to a constant frame rate, so video time
  `t` always corresponds to source frame `t × fps`.
- The browser's `requestVideoFrameCallback` reports the exact media time of
  each frame as it is displayed; the overlay is redrawn for that time.
- Only every 2nd (standard) or 5th (quick) frame was analysed, so positions
  between analysed frames are **linearly interpolated**; markers glide
  instead of jumping. Interpolation never spans gaps longer than three
  analysed frames (e.g. camera cuts).
- Looking up the state for one video frame takes about 0.07 ms, far below the
  40 ms between frames at 25 fps.

## Why canvas, and why custom controls?

The overlay is a transparent `<canvas>` stacked exactly over the `<video>`.
Canvas drawing is fast enough to redraw every layer for every frame without
involving React's rendering, which keeps playback smooth. Because the canvas
covers the video, the page has its own controls, including frame-by-frame
stepping and slow motion, which are useful for analysis.

## Code

| File | Role |
|---|---|
| `frontend/src/analysis/types.ts` | Shape of the results file |
| `frontend/src/analysis/timeline.ts` | State at any time, interpolation, trails |
| `frontend/src/analysis/geometry.ts` | Homography projection, convex hull, letterbox fitting |
| `frontend/src/analysis/draw.ts` | Drawing each layer on the video and the board |
| `frontend/src/components/VideoAnalysis.tsx` | Video, overlay, board, controls, player panel |
| `worker/src/pipeline.py` (`_pitch_to_image_matrices`) | Exports the per-frame matrices |

Matches analysed before the matrices existed show players, team shape and the
board, and can be upgraded with **Re-analyse**.

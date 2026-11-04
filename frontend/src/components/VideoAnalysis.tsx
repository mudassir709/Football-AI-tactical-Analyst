// The main analysis screen. It shows:
//   - the video, with the tactical drawings (players, paths, shapes, heatmaps) on top
//   - our own play/pause/seek controls under the video
//   - buttons to turn each drawing layer on or off
//   - next to the video: the 2D tactical board and the formation each team is playing right now
//   - below: tabs for the match summary, the selected player and the AI report
//
// Speed matters here: the drawings are redrawn for every single video frame.
// So I draw straight onto <canvas> elements instead of going through React,
// and React state only keeps things that change rarely (which layers are on,
// which player is selected, the time shown under the video).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import {
  BOARD_SYMBOL,
  drawBoard,
  drawVideoOverlay,
  personAt,
  personOnBoard,
  REFEREE_COLOUR,
  type HeatmapLayer,
  type Layers,
} from "../analysis/draw";
import { Timeline, type FrameState } from "../analysis/timeline";
import type { AnalysisResults } from "../analysis/types";
import { SectionTitle, Stat } from "./ui";

/**
 * Get a canvas ready for drawing. A canvas has its own pixel size, separate
 * from the size it takes up on the page, so I match the two (times the
 * screen's pixel ratio) to keep the drawings sharp on high-resolution screens.
 * Returns the 2D drawing context plus the size to draw in, or null if the
 * canvas isn't on screen yet.
 */
function prepareCanvas(canvas: HTMLCanvasElement | null) {
  if (!canvas) return null;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return null;
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height };
}

// Turns seconds into "minutes:seconds.tenths", e.g. 83.4 -> "1:23.4".
const formatClock = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${m}:${s}`;
};

const teamName = (id: number) => (id === 0 ? "Team A" : id === 1 ? "Team B" : "No team");

// The tabs under the video.
type Tab = "summary" | "player" | "report";

export function VideoAnalysis({
  videoUrl,
  results,
  summary,
  report,
}: {
  videoUrl: string;
  results: AnalysisResults;
  summary: ReactNode; // content of the "Summary" tab (made by the match page)
  report: ReactNode; // content of the "AI coaching report" tab
}) {
  // The Timeline answers "where is everyone at time t?". Building it takes a
  // moment, so useMemo makes sure it's only built once per results file.
  const timeline = useMemo(() => new Timeline(results), [results]);
  // Direct handles to the video element and the two canvases.
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  // The video, its drawings and the controls together; this is what goes full screen.
  const playerRef = useRef<HTMLDivElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const boardRef = useRef<HTMLCanvasElement>(null);

  // What the user has chosen: visible layers, selected player, playback state, open tab.
  const [layers, setLayers] = useState<Layers>({ players: true, trails: true, shape: false, ball: true, heatmap: "off" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(results.video.durationSeconds);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);

  // Keep "fullscreen" up to date, also when the user leaves full screen with Esc.
  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === playerRef.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  // The full-screen button: enter full screen, or leave it if already there.
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void playerRef.current?.requestFullscreen();
  };
  const [tab, setTab] = useState<Tab>("summary");

  // The drawing loop reads the current layer settings from this ref. That way
  // turning a layer on or off doesn't have to restart the loop.
  const settings = useRef({ layers, selectedId });
  useLayoutEffect(() => {
    settings.current = { layers, selectedId };
  }, [layers, selectedId]);
  // The positions drawn last, kept so a mouse click can be matched to a player.
  const lastState = useRef<FrameState | null>(null);

  // Draws one moment of the video: works out where everyone is at that time,
  // then draws the overlay on the video and the 2D board.
  const draw = useCallback(
    (mediaTime: number) => {
      const state = timeline.stateAt(mediaTime);
      lastState.current = state;
      const { layers: currentLayers, selectedId: selected } = settings.current;
      const overlay = prepareCanvas(overlayRef.current);
      if (overlay) drawVideoOverlay(overlay.ctx, overlay.width, overlay.height, results, timeline, state, currentLayers, selected);
      const board = prepareCanvas(boardRef.current);
      if (board) drawBoard(board.ctx, board.width, board.height, results, timeline, state, currentLayers, selected);
    },
    [results, timeline],
  );

  // Redraw every time the video shows a new frame. requestVideoFrameCallback
  // tells me the exact time of the frame that's on screen, so the drawings
  // never lag behind the players. Browsers that don't have it fall back to
  // requestAnimationFrame (about 60 times a second) and video.currentTime.
  // The function returned at the end stops the loop when the page is closed.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let handle = 0;
    let stopped = false;
    if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
      const onFrame: VideoFrameRequestCallback = (_now, metadata) => {
        if (stopped) return;
        draw(metadata.mediaTime);
        handle = video.requestVideoFrameCallback(onFrame);
      };
      handle = video.requestVideoFrameCallback(onFrame);
      return () => {
        stopped = true;
        video.cancelVideoFrameCallback(handle);
      };
    }
    const onAnimationFrame = () => {
      if (stopped) return;
      draw(video.currentTime);
      handle = requestAnimationFrame(onAnimationFrame);
    };
    handle = requestAnimationFrame(onAnimationFrame);
    return () => {
      stopped = true;
      cancelAnimationFrame(handle);
    };
  }, [draw]);

  // When the video is paused no new frames arrive, so redraw by hand when a
  // layer is switched or a player is selected...
  useEffect(() => {
    if (videoRef.current) draw(videoRef.current.currentTime);
  }, [draw, layers, selectedId]);
  // ...and when the canvases change size (e.g. the browser window is resized).
  useEffect(() => {
    const observer = new ResizeObserver(() => videoRef.current && draw(videoRef.current.currentTime));
    [overlayRef.current, boardRef.current].forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [draw]);

  const video = () => videoRef.current!;
  const fps = results.video.fps;
  // The "1f" buttons: pause and move exactly one frame back (-1) or forward (+1).
  const stepFrame = (delta: number) => {
    video().pause();
    const frame = Math.round(video().currentTime * fps) + delta;
    // Aim slightly inside the frame so rounding never lands on its neighbour.
    video().currentTime = Math.min(Math.max(0, (frame + 0.1) / fps), duration);
  };
  const togglePlay = () => (video().paused ? void video().play() : video().pause());

  // Clicking a player selects them and opens the "Player" tab; clicking the
  // same player again unselects them.
  const toggleSelection = (id: number | null) => {
    setSelectedId((current) => (id === current ? null : id));
    if (id !== null && id !== selectedId) setTab("player");
  };
  // Click on the video: find which player (if any) is under the mouse.
  const onOverlayClick = (event: MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!lastState.current) return;
    const id = personAt(results, lastState.current, rect.width, rect.height, event.clientX - rect.left, event.clientY - rect.top);
    if (id !== null) toggleSelection(id);
    else togglePlay(); // clicking empty space plays/pauses, like most players
  };
  // Click on the 2D board: same idea, but positions there are in pitch metres.
  const onBoardClick = (event: MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!lastState.current) return;
    const id = personOnBoard(results, lastState.current, rect.width, rect.height, event.clientX - rect.left, event.clientY - rect.top);
    toggleSelection(id);
  };

  // Formations are worked out for 5-second windows. Find the window each team
  // is in at the current time, to show "4-4-2" etc. under the board.
  const currentFormations = results.teams.map((team) => ({
    team,
    window: results.formations.windows.find((w) => w.team === team.id && time >= w.start && time < w.end),
  }));
  // Results made by older versions can't draw paths/heatmaps on the video.
  const pitchLayersAvailable = timeline.hasPitchMatrices;

  const tabs: [Tab, string][] = [
    ["summary", "Summary"],
    ["player", selectedName(results, selectedId) ?? "Player"],
    ["report", "AI coaching report"],
  ];

  return (
    <div className="space-y-8">
      {/* Video (about 60 %) and tactical board (about 40 %) side by side on wide screens. */}
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        {/* In full screen this whole block fills the screen on a dark background. */}
        <div ref={playerRef} className={fullscreen ? "flex flex-col justify-center overflow-auto bg-pitch p-6" : ""}>
          <div className="border border-line bg-pitch-2 p-1.5">
            {/* The video and the drawing canvas are stacked exactly on top of each other.
                The video's events keep the controls (time, play button) up to date. */}
            <div
              className="relative mx-auto bg-black"
              style={{
                aspectRatio: `${results.video.width} / ${results.video.height}`,
                // In full screen, as wide as fits while leaving room for the controls below.
                width: fullscreen ? `min(100%, calc((100vh - 170px) * ${results.video.width / results.video.height}))` : undefined,
              }}
            >
              <video
                ref={videoRef}
                src={videoUrl}
                className="absolute inset-0 h-full w-full"
                playsInline
                preload="auto"
                onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                onSeeked={(e) => {
                  setTime(e.currentTarget.currentTime);
                  draw(e.currentTarget.currentTime);
                }}
                onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
              />
              <canvas
                ref={overlayRef}
                className="absolute inset-0 h-full w-full cursor-pointer"
                onClick={onOverlayClick}
                aria-label="Tactical overlay. Click a player to inspect them."
              />
              {/* Full-screen button in the bottom-right corner of the video. */}
              <button
                type="button"
                onClick={toggleFullscreen}
                className="absolute right-2 bottom-2 rounded bg-pitch/80 p-1.5 text-chalk hover:bg-pitch hover:text-accent"
                title={fullscreen ? "Exit full screen (Esc)" : "Full screen"}
                aria-label={fullscreen ? "Exit full screen" : "Full screen"}
              >
                <FullscreenIcon exit={fullscreen} />
              </button>
            </div>
          </div>

          {/* Our own controls, because the canvas on top hides the browser's built-in ones:
              play/pause, one frame back/forward, the seek bar, the time and the speed. */}
          <div className="flex flex-wrap items-center gap-4 px-1 pt-3 font-mono text-sm text-dim">
            <button className="rounded bg-accent px-3 py-1 font-semibold text-pitch hover:brightness-110" onClick={togglePlay}>
              {playing ? "❚❚ pause" : "▶ play"}
            </button>
            <button className="hover:text-chalk" onClick={() => stepFrame(-1)} title="Previous frame" aria-label="Previous frame">
              ◂ 1f
            </button>
            <button className="hover:text-chalk" onClick={() => stepFrame(1)} title="Next frame" aria-label="Next frame">
              1f ▸
            </button>
            <input
              type="range"
              min={0}
              max={duration || 0}
              step={1 / fps}
              value={time}
              onChange={(e) => {
                video().currentTime = Number(e.target.value);
                setTime(Number(e.target.value));
              }}
              className="min-w-40 flex-1 accent-accent"
              aria-label="Seek"
            />
            <span className="tabular-nums">
              {formatClock(time)} / {formatClock(duration)}
            </span>
            <select
              value={rate}
              onChange={(e) => {
                setRate(Number(e.target.value));
                video().playbackRate = Number(e.target.value);
              }}
              className="rounded border border-line bg-pitch px-2 py-1 text-chalk"
              aria-label="Playback speed"
            >
              {[0.25, 0.5, 1].map((r) => (
                <option key={r} value={r}>{r}×</option>
              ))}
            </select>
          </div>

          {/* Layer chips: each one flips one layer on or off (● = on, ○ = off). The heatmap
              menu picks whose heatmap to paint on the pitch (a team, the ball, or none). */}
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
            {(
              [
                ["players", "players"],
                ["trails", "movement paths"],
                ["shape", "team shape"],
                ["ball", "ball"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setLayers((l) => ({ ...l, [key]: !l[key] }))}
                aria-pressed={layers[key]}
                disabled={key === "trails" && !pitchLayersAvailable}
                className={`rounded-full border px-3 py-1 transition-colors disabled:opacity-40 ${
                  layers[key] ? "border-accent text-accent" : "border-line text-dim hover:text-chalk"
                }`}
              >
                {layers[key] ? "●" : "○"} {label}
              </button>
            ))}
            <label className="flex items-center gap-2 rounded-full border border-line py-1 pr-1 pl-3 text-dim">
              heatmap
              <select
                value={layers.heatmap}
                onChange={(e) => setLayers((l) => ({ ...l, heatmap: e.target.value as HeatmapLayer }))}
                className="rounded-full bg-pitch-3 px-2 py-0.5 text-chalk"
              >
                <option value="off">off</option>
                {results.teams.map((t) => (
                  <option key={t.id} value={String(t.id)}>{teamName(t.id)}</option>
                ))}
                <option value="ball">ball</option>
              </select>
            </label>
            {!pitchLayersAvailable && (
              <p className="w-full text-xs text-accent">
                Paths and heatmaps on the video need a newer analysis of this match. Use “Re-analyse” above to enable them.
              </p>
            )}
          </div>
        </div>

        {/* The tactical board with the current formations and the legend. */}
        <div className="h-fit space-y-4 border border-line bg-pitch-2 p-4">
          <SectionTitle>Tactical board · synced to video</SectionTitle>
          <canvas
            ref={boardRef}
            className="aspect-[111/74] w-full cursor-pointer"
            onClick={onBoardClick}
            aria-label="2D tactical board. Click a player to inspect them."
          />
          <div className="grid grid-cols-2 gap-4">
            {currentFormations.map(({ team, window }) => (
              <div key={team.id} className={`border-l-[3px] pl-3 ${team.id === 0 ? "border-chalk" : "border-accent"}`}>
                <div className="text-xs text-dim">
                  {teamName(team.id)} ({BOARD_SYMBOL[team.id] ?? "•"})
                </div>
                <div className="font-mono text-3xl font-medium">{window?.formation ?? "—"}</div>
                {window?.runnerUp && <div className="text-xs text-dim">runner-up {window.runnerUp}</div>}
              </div>
            ))}
          </div>
          <Legend results={results} />
        </div>
      </div>

      {/* Tabs under the video: the summary, the selected player and the AI report. */}
      <div>
        <div className="flex gap-8 border-b border-dashed border-line" role="tablist">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`-mb-px border-b-2 py-2.5 text-sm transition-colors ${
                tab === key ? "border-accent text-chalk" : "border-transparent text-dim hover:text-chalk"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="pt-6" role="tabpanel">
          {tab === "summary" && (summary ?? <p className="text-sm text-dim">No summary available.</p>)}
          {tab === "player" && (
            <PlayerPanel results={results} timeline={timeline} selectedId={selectedId} onClose={() => setSelectedId(null)} />
          )}
          {tab === "report" && report}
        </div>
      </div>
    </div>
  );
}

// Small key under the board: which symbol and kit colour is which team, and the referees.
function Legend({ results }: { results: AnalysisResults }) {
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-dashed border-line pt-3 text-xs text-dim">
      {results.teams.map((t) => (
        <span key={t.id} className="flex items-center gap-1.5">
          <span className={t.id === 0 ? "text-chalk" : "text-accent"}>{BOARD_SYMBOL[t.id] ?? "•"}</span>
          {teamName(t.id)}
          <span className="h-2.5 w-1.5" style={{ backgroundColor: t.colour }} title="kit colour" />
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2" style={{ backgroundColor: REFEREE_COLOUR }} /> referees
      </span>
    </div>
  );
}

// The "Player" tab: a mini pitch with the selected player's heatmap and full
// path, plus distance, time on screen, average speed and top speed.
function PlayerPanel({
  results,
  timeline,
  selectedId,
  onClose,
}: {
  results: AnalysisResults;
  timeline: Timeline;
  selectedId: number | null;
  onClose: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const player = results.players.find((p) => p.id === selectedId);

  // Draw the mini pitch whenever a different player is selected. It reuses the
  // board drawing code, but shows only this player's heatmap and path.
  useEffect(() => {
    if (!player) return;
    const canvas = prepareCanvas(canvasRef.current);
    if (!canvas) return;
    drawBoard(
      canvas.ctx, canvas.width, canvas.height, results, timeline, null,
      { players: false, trails: false, shape: false, ball: false, heatmap: "off" }, null,
      { heatmapGrid: player.heatmap, staticPath: timeline.fullPath(player.id), showPeople: false },
    );
  }, [player, results, timeline]);

  if (!player) {
    return (
      <p className="font-hand text-xl text-accent">
        Click a player on the video or the board to see their movement, heatmap and physical stats.
      </p>
    );
  }

  // Missing numbers (e.g. a player who was only seen for a moment) show as "—".
  // From results v3 a "player" is a position, so the title says e.g. "LB".
  const roleLabel = player.label ?? (player.role === "goalkeeper" ? "Goalkeeper" : player.role === "referee" ? "Referee" : "Player");
  const value = (v: number | null, unit: string) => (v === null ? "—" : `${v} ${unit}`);
  return (
    <div className="grid gap-8 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div>
        <canvas ref={canvasRef} className="aspect-[111/74] w-full" aria-label="Player heatmap and path" />
        <p className="mt-2 font-mono text-[11px] text-dim">
          {player.label
            ? "heatmap and path of whoever played this position, over the analysed clip"
            : "heatmap and full path over the analysed clip"}
        </p>
      </div>
      <div className="space-y-6">
        <div className="flex items-baseline gap-3">
          <h3 className="text-xl font-semibold">
            {player.label ? roleLabel : `${roleLabel} #${player.id}`}
          </h3>
          <span className="text-sm text-dim">{player.role !== "referee" && teamName(player.team)}</span>
          <button className="ml-auto text-xs text-dim hover:text-chalk" onClick={onClose}>
            clear selection ✕
          </button>
        </div>
        <div className="grid grid-cols-2 gap-6">
          <Stat label="Distance" value={value(player.distanceM, "m")} />
          <Stat label="Time visible" value={value(player.secondsVisible, "s")} />
          <Stat label="Avg speed" value={value(player.avgSpeedKmh, "km/h")} />
          <Stat label="Top speed" value={value(player.maxSpeedKmh, "km/h")} hint="best one-second average" />
        </div>
      </div>
    </div>
  );
}

// Name of the selected player for the tab title: the position ("Team A · LB")
// in newer results, the track number ("Player #12") in older ones.
function selectedName(results: AnalysisResults, selectedId: number | null): string | null {
  if (selectedId === null) return null;
  const player = results.players.find((p) => p.id === selectedId);
  if (player?.label) return `${teamName(player.team)} · ${player.label}`;
  return `Player #${selectedId}`;
}

// The four-corners icon on the full-screen button; the corners point inwards
// when pressing it will leave full screen.
function FullscreenIcon({ exit }: { exit: boolean }) {
  const corners = exit
    ? "M6 1v5H1M10 1v5h5M6 15v-5H1M10 15v-5h5"
    : "M1 6V1h5M15 6V1h-5M1 10v5h5M15 10v5h-5";
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d={corners} />
    </svg>
  );
}

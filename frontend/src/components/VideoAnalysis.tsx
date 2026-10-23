// The interactive analysis view: video with tactical overlays, a synchronised
// 2D board, layer toggles, current formations and a player detail panel.
//
// Performance note: overlays are redrawn for every video frame directly on
// <canvas> elements, outside React's render cycle. React state only holds
// slow-changing things (toggles, selection, the time shown in the controls).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  drawBoard,
  drawVideoOverlay,
  personAt,
  personColour,
  personOnBoard,
  REFEREE_COLOUR,
  type HeatmapLayer,
  type Layers,
} from "../analysis/draw";
import { Timeline, type FrameState } from "../analysis/timeline";
import type { AnalysisResults } from "../analysis/types";
import { Card, Stat } from "./ui";

/** Size a canvas's pixel buffer to its on-screen size (sharp on high-DPI screens). */
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

const formatClock = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${m}:${s}`;
};

const teamName = (id: number) => (id === 0 ? "Team A" : id === 1 ? "Team B" : "No team");

export function VideoAnalysis({ videoUrl, results }: { videoUrl: string; results: AnalysisResults }) {
  const timeline = useMemo(() => new Timeline(results), [results]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const boardRef = useRef<HTMLCanvasElement>(null);

  const [layers, setLayers] = useState<Layers>({ players: true, trails: true, shape: false, ball: true, heatmap: "off" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(results.video.durationSeconds);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);

  // The drawing loop reads the latest toggles through refs, so it never has
  // to be restarted when they change.
  const settings = useRef({ layers, selectedId });
  useLayoutEffect(() => {
    settings.current = { layers, selectedId };
  }, [layers, selectedId]);
  const lastState = useRef<FrameState | null>(null);

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

  // Redraw on every displayed video frame. requestVideoFrameCallback reports
  // the exact media time of the frame on screen; older browsers fall back to
  // animation frames and the video's currentTime.
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

  // Redraw immediately when toggles change or the canvases are resized while paused.
  useEffect(() => {
    if (videoRef.current) draw(videoRef.current.currentTime);
  }, [draw, layers, selectedId]);
  useEffect(() => {
    const observer = new ResizeObserver(() => videoRef.current && draw(videoRef.current.currentTime));
    [overlayRef.current, boardRef.current].forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [draw]);

  const video = () => videoRef.current!;
  const fps = results.video.fps;
  const stepFrame = (delta: number) => {
    video().pause();
    const frame = Math.round(video().currentTime * fps) + delta;
    // Aim slightly inside the frame so rounding never lands on its neighbour.
    video().currentTime = Math.min(Math.max(0, (frame + 0.1) / fps), duration);
  };
  const togglePlay = () => (video().paused ? void video().play() : video().pause());

  const toggleSelection = (id: number | null) => setSelectedId((current) => (id === current ? null : id));
  const onOverlayClick = (event: MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!lastState.current) return;
    const id = personAt(results, lastState.current, rect.width, rect.height, event.clientX - rect.left, event.clientY - rect.top);
    if (id !== null) toggleSelection(id);
    else togglePlay(); // clicking empty space plays/pauses, like most players
  };
  const onBoardClick = (event: MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!lastState.current) return;
    const id = personOnBoard(results, lastState.current, rect.width, rect.height, event.clientX - rect.left, event.clientY - rect.top);
    toggleSelection(id);
  };

  const currentFormations = results.teams.map((team) => ({
    team,
    window: results.formations.windows.find((w) => w.team === team.id && time >= w.start && time < w.end),
  }));
  const pitchLayersAvailable = timeline.hasPitchMatrices;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      {/* Left: video with overlay and controls */}
      <div className="space-y-3">
        <Card className="overflow-hidden p-0">
          <div className="relative bg-black" style={{ aspectRatio: `${results.video.width} / ${results.video.height}` }}>
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
          </div>
          {/* Custom controls (the overlay covers the browser's own controls) */}
          <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 px-4 py-3 text-sm">
            <button className="rounded-md bg-emerald-500 px-3 py-1 font-semibold text-slate-950 hover:bg-emerald-400" onClick={togglePlay}>
              {playing ? "Pause" : "Play"}
            </button>
            <button className="rounded-md bg-slate-800 px-2 py-1 hover:bg-slate-700" onClick={() => stepFrame(-1)} title="Previous frame" aria-label="Previous frame">
              ◀︎ 1f
            </button>
            <button className="rounded-md bg-slate-800 px-2 py-1 hover:bg-slate-700" onClick={() => stepFrame(1)} title="Next frame" aria-label="Next frame">
              1f ▶︎
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
              className="min-w-40 flex-1 accent-emerald-400"
              aria-label="Seek"
            />
            <span className="tabular-nums text-slate-400">
              {formatClock(time)} / {formatClock(duration)}
            </span>
            <select
              value={rate}
              onChange={(e) => {
                setRate(Number(e.target.value));
                video().playbackRate = Number(e.target.value);
              }}
              className="rounded-md bg-slate-800 px-2 py-1"
              aria-label="Playback speed"
            >
              {[0.25, 0.5, 1].map((r) => (
                <option key={r} value={r}>{r}×</option>
              ))}
            </select>
          </div>
        </Card>

        {/* Layer toggles */}
        <Card className="flex flex-wrap items-center gap-2 py-3 text-sm">
          <span className="mr-1 text-slate-400">Layers</span>
          {(
            [
              ["players", "Players"],
              ["trails", "Movement paths"],
              ["shape", "Team shape"],
              ["ball", "Ball"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setLayers((l) => ({ ...l, [key]: !l[key] }))}
              aria-pressed={layers[key]}
              disabled={key === "trails" && !pitchLayersAvailable}
              className={`rounded-full px-3 py-1 font-medium transition-colors disabled:opacity-40 ${
                layers[key] ? "bg-emerald-500/20 text-emerald-200 ring-1 ring-emerald-400/60" : "bg-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              {label}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-2">
            <span className="text-slate-400">Heatmap</span>
            <select
              value={layers.heatmap}
              onChange={(e) => setLayers((l) => ({ ...l, heatmap: e.target.value as HeatmapLayer }))}
              className="rounded-md bg-slate-800 px-2 py-1"
            >
              <option value="off">Off</option>
              {results.teams.map((t) => (
                <option key={t.id} value={String(t.id)}>{teamName(t.id)}</option>
              ))}
              <option value="ball">Ball</option>
            </select>
          </label>
          {!pitchLayersAvailable && (
            <p className="w-full text-xs text-amber-300">
              Paths and heatmaps on the video need a newer analysis of this match. Use “Re-analyse” above to enable them.
            </p>
          )}
        </Card>
      </div>

      {/* Right: 2D board, formations, player panel */}
      <div className="space-y-4">
        <Card className="space-y-3 p-3">
          <div className="flex items-center justify-between text-sm">
            <h3 className="font-semibold">Tactical board</h3>
            <span className="text-xs text-slate-500">synced to video</span>
          </div>
          <canvas
            ref={boardRef}
            className="aspect-[111/74] w-full cursor-pointer rounded-md"
            onClick={onBoardClick}
            aria-label="2D tactical board. Click a player to inspect them."
          />
          <div className="grid grid-cols-2 gap-2">
            {currentFormations.map(({ team, window }) => (
              <div key={team.id} className="rounded-lg bg-slate-800/70 px-3 py-2">
                <div className="flex items-center gap-1.5 text-xs text-slate-400">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: team.colour }} />
                  {teamName(team.id)}
                </div>
                <div className="text-lg font-semibold">{window?.formation ?? "—"}</div>
                {window?.runnerUp && (
                  <div className="text-[11px] text-slate-500">runner-up {window.runnerUp}</div>
                )}
              </div>
            ))}
          </div>
          <Legend results={results} />
        </Card>
        <PlayerPanel results={results} timeline={timeline} selectedId={selectedId} onClose={() => setSelectedId(null)} />
      </div>
    </div>
  );
}

function Legend({ results }: { results: AnalysisResults }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
      {results.teams.map((t) => (
        <span key={t.id} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: t.colour }} /> {teamName(t.id)}
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: REFEREE_COLOUR }} /> Referees
      </span>
    </div>
  );
}

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
      <Card className="text-sm text-slate-400">
        Click a player on the video or the board to see their movement, heatmap and physical stats.
      </Card>
    );
  }

  const roleLabel = player.role === "goalkeeper" ? "Goalkeeper" : player.role === "referee" ? "Referee" : "Player";
  const value = (v: number | null, unit: string) => (v === null ? "—" : `${v} ${unit}`);
  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2">
        <span
          className="h-4 w-4 rounded-full ring-2 ring-slate-700"
          style={{ backgroundColor: personColour(results, player.team, player.role === "referee" ? 2 : 0) }}
        />
        <h3 className="font-semibold">
          {roleLabel} #{player.id}
        </h3>
        <span className="text-xs text-slate-500">{player.role !== "referee" && teamName(player.team)}</span>
        <button className="ml-auto text-xs text-slate-400 hover:text-white" onClick={onClose}>
          Close
        </button>
      </div>
      <canvas ref={canvasRef} className="aspect-[111/74] w-full rounded-md" aria-label="Player heatmap and path" />
      <p className="text-[11px] text-slate-500">Heatmap and full path over the analysed clip.</p>
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Distance" value={value(player.distanceM, "m")} />
        <Stat label="Time visible" value={value(player.secondsVisible, "s")} />
        <Stat label="Avg speed" value={value(player.avgSpeedKmh, "km/h")} />
        <Stat label="Top speed" value={value(player.maxSpeedKmh, "km/h")} />
      </div>
    </Card>
  );
}

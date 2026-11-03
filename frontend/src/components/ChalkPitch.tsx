// A decorative chalk drawing of half a pitch with a little tactic on it
// (○ = our players, × = opponents, arrows = runs). Shown next to the login form.
export function ChalkPitch({ className = "" }: { className?: string }) {
  const chalk = "#e9ece4";
  const amber = "#f2b33d";
  // Our players (○) and the opponents (×), in pitch-like coordinates.
  const ours = [[18, 50], [30, 22], [30, 78], [44, 40], [46, 64], [62, 30], [64, 70]];
  const theirs = [[36, 50], [52, 18], [55, 52], [72, 46], [76, 80]];
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden>
      <defs>
        <marker id="chalk-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto">
          <path d="M0 0L6 3L0 6z" fill={chalk} />
        </marker>
      </defs>
      {/* Pitch lines, dashed like chalk. */}
      <g fill="none" stroke={chalk} strokeOpacity="0.55" strokeWidth="0.5" strokeDasharray="1.6 1">
        <rect x="4" y="4" width="92" height="92" />
        <path d="M96 30 H80 V70 H96 M96 41 H90 V59 H96" />
        <path d="M4 50 A 12 12 0 0 0 4 50" />
        <circle cx="4" cy="50" r="12" />
      </g>
      {ours.map(([x, y]) => (
        <circle key={`o${x}${y}`} cx={x} cy={y} r="2.6" fill="none" stroke={chalk} strokeWidth="0.8" />
      ))}
      {theirs.map(([x, y]) => (
        <path key={`x${x}${y}`} d={`M${x - 2} ${y - 2}l4 4M${x + 2} ${y - 2}l-4 4`} stroke={amber} strokeWidth="0.9" />
      ))}
      {/* Two runs and a pass, drawn as curved arrows. */}
      <g fill="none" stroke={chalk} strokeWidth="0.6" markerEnd="url(#chalk-arrow)">
        <path d="M46 64 C 56 62, 62 58, 70 56" />
        <path d="M62 30 C 70 30, 78 34, 84 40" />
        <path d="M44 40 Q 52 46, 60 34" strokeDasharray="1.4 1" />
      </g>
    </svg>
  );
}

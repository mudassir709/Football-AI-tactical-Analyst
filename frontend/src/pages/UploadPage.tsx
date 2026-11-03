// The upload page. The user picks a video (by clicking or dragging it in),
// gives it a title, chooses Standard or Quick analysis and uploads it.
// After the upload the page jumps to the new match, where the progress shows.
import { useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { uploadMatch } from "../api";
import { Button, ErrorMessage, inputClasses, ProgressBar } from "../components/ui";
import { formatBytes } from "../format";
import type { AnalysisMode } from "../types";

// File types offered in the file picker (the server checks them again anyway).
const ACCEPTED = ".mp4,.mov,.m4v,.mkv,.webm,.avi";

// The two analysis modes shown as cards. The real settings behind them
// (which frames, what resolution) live in the worker's config.py.
const MODES: { value: AnalysisMode; title: string; description: string }[] = [
  {
    value: "standard",
    title: "Standard",
    description: "Every 2nd frame at full resolution. Best accuracy; about 4-5 s of processing per second of video.",
  },
  {
    value: "quick",
    title: "Quick",
    description: "Every 5th frame at lower resolution. Several times faster; ideal for short clips and demos.",
  },
];

export function UploadPage() {
  const navigate = useNavigate();
  // The real file input is hidden; the big drop zone button clicks it for us.
  const fileInput = useRef<HTMLInputElement>(null);
  // Form values. uploadProgress is null when nothing is uploading, otherwise 0 to 1.
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<AnalysisMode>("standard");
  const [dragging, setDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Called when a file is picked, whether by clicking or by dropping it.
  function chooseFile(chosen: File | undefined) {
    if (!chosen) return;
    setFile(chosen);
    setError(null);
    // Suggest a title from the file name if the user has not typed one.
    if (!title) setTitle(chosen.name.replace(/\.[^.]+$/, ""));
  }

  // A file was dropped on the drop zone. preventDefault stops the browser from
  // simply opening the video in the tab.
  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0]);
  }

  // "Upload and analyse": send the file while updating the progress bar. When it's
  // done the server has already queued the analysis, so we open the match page.
  // If something goes wrong, the server's message is shown under the form.
  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setError(null);
    setUploadProgress(0);
    try {
      const match = await uploadMatch(file, title, mode, setUploadProgress);
      navigate(`/matches/${match.id}`);
    } catch (err) {
      setError((err as Error).message);
      setUploadProgress(null);
    }
  }

  const uploading = uploadProgress !== null;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold">Upload a match</h1>
        <p className="mt-1 text-sm text-dim">
          The analysis runs in the background; you can leave this page and come back.
        </p>
      </div>

      {/* Two columns on wide screens: the form, and tips on the right. */}
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Step 1. Drop zone: a big area you can click to open the file picker, or
            drop a file on. It turns amber while a file is being dragged over it. */}
        <Step number={1} title="Choose the video">
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          disabled={uploading}
          className={`flex w-full flex-col items-center justify-center gap-2 border border-dashed px-6 py-14 text-center transition-colors ${
            dragging ? "border-accent bg-accent/5" : "border-chalk/40 bg-pitch-2 hover:border-chalk/70"
          }`}
        >
          {file ? (
            <>
              <span className="font-medium">{file.name}</span>
              <span className="font-mono text-xs text-dim">{formatBytes(file.size)} · click to choose another</span>
            </>
          ) : (
            <>
              <span className="font-hand text-2xl text-accent">Drop a video here</span>
              <span className="text-sm text-dim">or click to choose · MP4, MOV, MKV, WebM or AVI · up to 500 MB</span>
            </>
          )}
        </button>
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => chooseFile(e.target.files?.[0])}
        />
        </Step>

        {/* Step 2. The title shown in the match list. */}
        <Step number={2} title="Give it a name">
          <input
            className={inputClasses}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={120}
            placeholder="e.g. Stuttgart vs Köln, first half"
            disabled={uploading}
            aria-label="Title"
          />
        </Step>

        {/* Step 3. The two mode cards. They are really radio buttons with the round
            button hidden, so the whole card can be clicked and the chosen one is highlighted. */}
        <Step number={3} title="Pick the analysis mode">
        <fieldset>
          <legend className="sr-only">Analysis mode</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {MODES.map((option) => (
              <label
                key={option.value}
                className={`cursor-pointer border p-4 transition-colors ${
                  mode === option.value ? "border-accent bg-accent/5" : "border-line bg-pitch-2 hover:border-chalk/50"
                }`}
              >
                <input
                  type="radio"
                  name="mode"
                  value={option.value}
                  checked={mode === option.value}
                  onChange={() => setMode(option.value)}
                  className="sr-only"
                  disabled={uploading}
                />
                <span className="flex items-center gap-2 font-semibold">
                  <span className={mode === option.value ? "text-accent" : "text-dim"}>{mode === option.value ? "●" : "○"}</span>
                  {option.title}
                </span>
                <span className="mt-1 block text-xs text-dim">{option.description}</span>
              </label>
            ))}
          </div>
        </fieldset>
        </Step>

        {/* At 100 % the file has arrived, but the server still checks and saves it. */}
        {error && <ErrorMessage>{error}</ErrorMessage>}
        {uploading && (
          <ProgressBar value={uploadProgress * 100} label={uploadProgress < 1 ? "uploading" : "saving"} />
        )}

        <Button type="submit" disabled={!file || uploading} className="w-full sm:w-auto">
          {uploading ? "Uploading…" : "Upload and analyse →"}
        </Button>
      </form>

      {/* Tips, written like notes on the side of a tactics board. */}
      <aside className="h-fit border border-dashed border-line p-6">
        <p className="font-hand text-2xl text-accent">Tips for good results</p>
        <ul className="mt-4 space-y-3 text-sm text-dim">
          <li>○ Use the main, <span className="text-chalk">wide camera view</span>, the one that shows most of the pitch.</li>
          <li>○ Replays and close-ups are skipped; a clip made only of them can't be analysed.</li>
          <li>○ Try <span className="text-chalk">Quick</span> first for long videos, then re-analyse in Standard.</li>
          <li>○ Kits that are clearly different colours make team detection easier.</li>
        </ul>
      </aside>
      </div>
    </div>
  );
}

// One numbered step of the form, with a chalk-style number in front of the title.
function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="flex items-baseline gap-3 font-medium">
        <span className="font-hand text-2xl leading-none text-accent">{number}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

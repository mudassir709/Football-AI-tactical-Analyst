// Upload a match video and choose how thoroughly to analyse it.
import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { uploadMatch } from "../api";
import { Button, Card, ErrorMessage, ProgressBar } from "../components/ui";
import { formatBytes } from "../format";
import type { AnalysisMode } from "../types";

const ACCEPTED = ".mp4,.mov,.m4v,.mkv,.webm,.avi";

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
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<AnalysisMode>("standard");
  const [dragging, setDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  function chooseFile(chosen: File | undefined) {
    if (!chosen) return;
    setFile(chosen);
    setError(null);
    // Suggest a title from the file name if the user has not typed one.
    if (!title) setTitle(chosen.name.replace(/\.[^.]+$/, ""));
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files[0]);
  }

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
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Upload a match</h1>
        <p className="text-sm text-slate-400">
          A broadcast clip with the main (wide) camera view works best. The analysis runs in the
          background; you can leave this page and come back.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Drop zone: a big clickable area that also accepts dragged files. */}
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
          className={`flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
            dragging ? "border-emerald-400 bg-emerald-400/5" : "border-slate-700 hover:border-slate-500"
          }`}
        >
          {file ? (
            <>
              <span className="font-medium">{file.name}</span>
              <span className="text-sm text-slate-400">{formatBytes(file.size)} · click to choose another</span>
            </>
          ) : (
            <>
              <span className="font-medium">Drop a video here, or click to choose</span>
              <span className="text-sm text-slate-400">MP4, MOV, MKV, WebM or AVI · up to 500 MB</span>
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

        <label className="block space-y-1 text-sm">
          <span className="text-slate-300">Title</span>
          <input
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 outline-none focus:border-emerald-400"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={120}
            placeholder="e.g. Stuttgart vs Köln, first half"
            disabled={uploading}
          />
        </label>

        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm text-slate-300">Analysis mode</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {MODES.map((option) => (
              <label
                key={option.value}
                className={`cursor-pointer rounded-xl border p-4 transition-colors ${
                  mode === option.value ? "border-emerald-400 bg-emerald-400/5" : "border-slate-700 hover:border-slate-500"
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
                <span className="block font-semibold">{option.title}</span>
                <span className="mt-1 block text-xs text-slate-400">{option.description}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {error && <ErrorMessage>{error}</ErrorMessage>}
        {uploading && (
          <Card>
            <ProgressBar value={uploadProgress * 100} label={uploadProgress < 1 ? "Uploading" : "Saving"} />
          </Card>
        )}

        <Button type="submit" disabled={!file || uploading} className="w-full sm:w-auto">
          {uploading ? "Uploading…" : "Upload and analyse"}
        </Button>
      </form>
    </div>
  );
}

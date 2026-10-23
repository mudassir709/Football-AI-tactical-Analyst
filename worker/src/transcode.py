"""Create a browser-playable copy of an uploaded video.

Browsers only play a few codecs reliably (H.264 in MP4 is the safe choice), but
uploads can be anything: HEVC from phones, MPEG-4 Part 2, AVI... The worker
therefore re-encodes every upload to H.264 for the dashboard's video player.

Frames are re-timed to a constant frame rate with one output frame per input
frame, so frame ``i`` in the copy is exactly frame ``i`` of the original and
the analysis overlays stay in sync. Audio is dropped; it is not analysed.
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import av

# Constant Rate Factor: 18 = visually lossless ... 28 = small files. 23 is x264's default.
CRF = 23
PRESET = "veryfast"  # fast encoding; slightly larger files than slower presets


def make_web_video(
    source: str | Path,
    target: str | Path,
    on_frame: Callable[[int, int], None] | None = None,
) -> Path:
    """Re-encode ``source`` to an H.264 MP4 at ``target``.

    Args:
        on_frame: Called with ``(frames_done, total_frames)`` while encoding.
    """
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".tmp" + target.suffix)

    with av.open(str(source)) as inp:
        in_stream = inp.streams.video[0]
        in_stream.thread_type = "AUTO"  # decode with several threads
        fps = in_stream.average_rate or in_stream.guessed_rate or Fraction(25)
        total = in_stream.frames or 0
        # H.264 with 4:2:0 colour needs even dimensions.
        width, height = in_stream.width // 2 * 2, in_stream.height // 2 * 2

        # "faststart" moves the index to the front of the file, so the browser
        # can start playing before the whole file has been downloaded.
        with av.open(str(tmp), "w", format="mp4", options={"movflags": "+faststart"}) as out:
            out_stream = out.add_stream("libx264", rate=fps)
            out_stream.width, out_stream.height = width, height
            out_stream.pix_fmt = "yuv420p"  # the colour format all browsers decode
            out_stream.codec_context.time_base = Fraction(1, 1) / fps
            out_stream.options = {"crf": str(CRF), "preset": PRESET}

            for index, frame in enumerate(inp.decode(in_stream)):
                frame = frame.reformat(width=width, height=height, format="yuv420p")
                frame.pts = index  # constant frame rate: one tick per frame
                frame.time_base = out_stream.codec_context.time_base
                for packet in out_stream.encode(frame):
                    out.mux(packet)
                if on_frame:
                    on_frame(index + 1, total)
            for packet in out_stream.encode():  # flush frames buffered in the encoder
                out.mux(packet)

    tmp.replace(target)
    return target

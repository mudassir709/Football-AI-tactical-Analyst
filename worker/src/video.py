"""Shared helpers for reading video frames in strided batches."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import supervision as sv


def get_video_info(video_path: str | Path) -> sv.VideoInfo:
    """Return resolution, fps and frame count, failing clearly if the file is missing."""
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    return sv.VideoInfo.from_video_path(str(video_path))


def iter_frame_batches(
    video_path: str | Path,
    stride: int = 1,
    start: int = 0,
    max_frames: int | None = None,
    batch_size: int = 4,
) -> Iterator[tuple[tuple[int, ...], tuple[np.ndarray, ...]]]:
    """Yield ``(frame_indices, frames)`` batches without loading the whole video.

    Args:
        video_path: Path to the input video.
        stride: Read every ``stride``-th frame.
        start: Index of the first frame to read.
        max_frames: Stop after this many frames have been read.
        batch_size: Frames per yielded batch (the last batch may be smaller).
    """
    if stride < 1 or batch_size < 1:
        raise ValueError("stride and batch_size must be >= 1")
    video_info = get_video_info(video_path)

    end = video_info.total_frames
    if max_frames is not None:
        end = min(end, start + max_frames * stride)
    frames = sv.get_video_frames_generator(str(video_path), stride=stride, start=start, end=end)

    indexed = zip(itertools.count(start, stride), frames)
    # Equivalent to itertools.batched (Python 3.12+), kept compatible with the
    # Python 3.11 images used on cloud GPU machines.
    while batch := list(itertools.islice(indexed, batch_size)):
        frame_indices, images = zip(*batch)
        yield frame_indices, images

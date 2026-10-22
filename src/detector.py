"""YOLOv8 inference wrapper that returns detections in the canonical football class scheme."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import supervision as sv
from ultralytics import YOLO

from src import config


class FootballDetector:
    """Detect players, goalkeepers, referees and the ball in video frames.

    Works with any Ultralytics detection model: model labels are mapped onto
    ``config.CLASS_NAMES`` via ``config.CLASS_ALIASES`` and anything else is dropped.
    """

    def __init__(
        self,
        weights_path: str | Path = config.DEFAULT_WEIGHTS,
        imgsz: int = config.DEFAULT_IMGSZ,
        class_confidence: dict[int, float] | None = None,
        iou: float = config.NMS_IOU,
        device: str | None = None,
    ) -> None:
        """
        Args:
            weights_path: Local ``.pt`` file, or a bare official name such as
                ``"yolov8n.pt"`` which Ultralytics downloads automatically.
            imgsz: Inference resolution (longest side, pixels).
            class_confidence: Per-class overrides for ``config.CLASS_CONFIDENCE``.
            iou: IoU threshold for YOLO's non-maximum suppression.
            device: ``"cpu"``, ``"cuda:0"`` etc. ``None`` lets Ultralytics choose.
        """
        weights_path = Path(weights_path)
        # Bare names (no directory) may be official weights that YOLO downloads itself.
        if not weights_path.exists() and weights_path.parent != Path("."):
            raise FileNotFoundError(f"Model weights not found: {weights_path}")
        try:
            self.model = YOLO(str(weights_path))
        except Exception as exc:
            raise RuntimeError(f"Could not load YOLO weights from {weights_path}: {exc}") from exc

        self.imgsz = imgsz
        self.iou = iou
        self.device = device
        self.class_confidence = {**config.CLASS_CONFIDENCE, **(class_confidence or {})}

        self._class_map = self._build_class_map(self.model.names)
        if (self._class_map < 0).all():
            raise ValueError(
                f"None of the model's classes {list(self.model.names.values())} "
                f"map to a football class; extend config.CLASS_ALIASES."
            )
        # YOLO filters at the lowest threshold; stricter per-class bars are applied after.
        self._min_conf = min(self.class_confidence.values())
        self._conf_lookup = np.array(
            [self.class_confidence[class_id] for class_id in sorted(config.CLASS_NAMES)]
        )

    @staticmethod
    def _build_class_map(model_names: dict[int, str]) -> np.ndarray:
        """Return an array mapping model class index -> canonical ID (-1 = discard)."""
        mapping = np.full(max(model_names) + 1, -1, dtype=int)
        for index, name in model_names.items():
            mapping[index] = config.CLASS_ALIASES.get(name.lower(), -1)
        return mapping

    def detect(self, frame: np.ndarray) -> sv.Detections:
        """Run detection on a single BGR frame."""
        return self.detect_batch([frame])[0]

    def detect_batch(self, frames: Sequence[np.ndarray]) -> list[sv.Detections]:
        """Run detection on several BGR frames in one forward pass."""
        if len(frames) == 0:
            return []
        results = self.model.predict(
            list(frames),
            imgsz=self.imgsz,
            conf=self._min_conf,
            iou=self.iou,
            device=self.device,
            verbose=False,
        )
        return [self._postprocess(result) for result in results]

    def _postprocess(self, result) -> sv.Detections:
        """Convert an Ultralytics result to canonical-class ``sv.Detections``."""
        detections = sv.Detections.from_ultralytics(result)
        detections.class_id = self._class_map[detections.class_id]
        detections = detections[detections.class_id >= 0]
        detections = detections[detections.confidence >= self._conf_lookup[detections.class_id]]
        detections.data["class_name"] = np.array(
            [config.CLASS_NAMES[class_id] for class_id in detections.class_id], dtype=str
        )
        return detections

"""Homography fitting and projection between image pixels and pitch metres."""
import numpy as np
import pandas as pd

from src.homography import Homography, PitchDimensions, project_tracks
from src.pipeline import _pitch_to_image_matrices

# A plausible broadcast-camera mapping: pitch metres -> image pixels.
PITCH_TO_IMAGE = np.array([[14.0, -6.0, 300.0], [0.5, -9.0, 900.0], [0.0004, -0.006, 1.0]])


def to_image(points: np.ndarray) -> np.ndarray:
    homogeneous = np.c_[points, np.ones(len(points))] @ PITCH_TO_IMAGE.T
    return homogeneous[:, :2] / homogeneous[:, 2:]


def test_pitch_keypoints_match_standard_dimensions():
    keypoints = PitchDimensions().keypoints
    assert keypoints.shape == (32, 2)
    assert keypoints[:, 0].min() == 0 and keypoints[:, 0].max() == 105
    assert keypoints[:, 1].min() == 0 and keypoints[:, 1].max() == 68


def test_fit_recovers_the_true_mapping():
    pitch_points = PitchDimensions().keypoints[[0, 5, 13, 16, 9, 12, 30, 31]]
    homography = Homography.fit(to_image(pitch_points), pitch_points)
    assert homography is not None
    assert homography.n_inliers == len(pitch_points)
    assert homography.reprojection_error < 1e-3
    probe = np.array([[30.0, 20.0], [70.0, 50.0]])
    assert np.allclose(homography.image_to_pitch(to_image(probe)), probe, atol=1e-3)


def test_fit_ignores_a_wrong_keypoint():
    pitch_points = PitchDimensions().keypoints[[0, 5, 13, 16, 9, 12, 30, 31]]
    image_points = to_image(pitch_points)
    image_points[3] += [400, -250]  # one badly detected landmark
    homography = Homography.fit(image_points, pitch_points)
    assert homography is not None and homography.n_inliers == len(pitch_points) - 1


def test_collinear_keypoints_are_rejected():
    # Only the halfway line visible: no stable homography exists.
    pitch_points = PitchDimensions().keypoints[[13, 14, 15, 16]]
    assert Homography.fit(to_image(pitch_points), pitch_points) is None


def test_project_tracks_puts_feet_on_the_pitch():
    image_to_pitch = np.linalg.inv(PITCH_TO_IMAGE).ravel()
    homographies = pd.DataFrame([{"frame_idx": 0, **{f"h{i}": v for i, v in enumerate(image_to_pitch)}}])
    feet = to_image(np.array([[52.5, 34.0]]))
    tracks = pd.DataFrame({"frame_idx": [0], "foot_x": feet[:, 0], "foot_y": feet[:, 1]})
    projected = project_tracks(tracks, homographies)
    assert np.allclose(projected[["pitch_x", "pitch_y"]].to_numpy(), [[52.5, 34.0]], atol=1e-3)


def test_exported_matrices_are_finite_when_last_entry_is_zero():
    # Regression test: dividing by the last entry produced NaN and failed analyses.
    degenerate = np.array([[1.0, 0.0, 5.0], [0.0, 1.0, 0.0], [0.01, 0.01, 0.0]])
    homographies = pd.DataFrame([{"frame_idx": 0, **{f"h{i}": v for i, v in enumerate(np.linalg.inv(degenerate).ravel())}}])
    matrices = _pitch_to_image_matrices(np.array([0]), homographies, max_frame_gap=0)
    assert np.all(np.isfinite(matrices[0]))
    # Sign convention: points on the pitch have positive depth.
    h = np.array(matrices[0]).reshape(3, 3)
    assert h[2] @ [52.5, 34.0, 1.0] > 0

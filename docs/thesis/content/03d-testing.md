## Testing

### Test strategy

Testing was carried out on several levels, each catching a different class of errors:

1. **Static checks** catch type errors and suspicious code before anything runs: the TypeScript compiler for the API and the dashboard, and the oxlint linter for the dashboard.
2. **Automated unit tests** (white-box) check the algorithms of the worker in isolation with synthetic data whose correct result is known: homography fitting and projection, shirt colour measurement, formation matching, trajectory processing and the safety of the results export.
3. **System tests** (black-box) exercise the running platform through its public interfaces, the browser and the REST API, exactly as a user would, including invalid input and wrong usage.
4. **High-volume runs** analyse the complete test dataset and check the correctness and plausibility of the results.
5. **Performance measurements** compare the processing time of the analysis modes and of CPU and GPU hardware.

Levels 1 and 2 run automatically in the CI pipeline on every push (Section 3.3.3), so a change that breaks them cannot be published as an image.

### Automated unit tests

The worker's unit tests are in `worker/tests/` and run with `python -m pytest`. They need neither videos nor model files, because they test the algorithms on constructed inputs: for example, a known camera matrix is used to project pitch landmarks into a synthetic image, and the test checks that the fitted homography recovers it. Parametrised tests run the same check for every kit colour or every formation. All 30 tests pass (Table 3.19); the run takes about 30 seconds.

Table: Unit tests of the worker {widths=34,8,58}
| Test | Cases | What is verified |
|---|---|---|
| `test_pitch_keypoints_match_standard_dimensions` | 1 | The 32 landmarks span exactly 0–105 m and 0–68 m. |
| `test_fit_recovers_the_true_mapping` | 1 | From 8 exact correspondences the fit uses all as inliers, the reprojection error is below 1 mm, and new points are projected correctly. |
| `test_fit_ignores_a_wrong_keypoint` | 1 | One landmark displaced by 470 px is rejected by RANSAC; the other 7 remain inliers. |
| `test_collinear_keypoints_are_rejected` | 1 | Four points on the halfway line give no homography (degeneracy check). |
| `test_project_tracks_puts_feet_on_the_pitch` | 1 | A foot point at the image of the centre spot is projected to (52.5, 34.0) m. |
| `test_exported_matrices_are_finite_when_last_entry_is_zero` | 1 | Regression test: a matrix whose last entry is 0 is exported without NaN, and pitch points have positive depth. |
| `test_shirt_colour_is_measured_with_local_grass` | 2 | A red and a lime-green shirt on grass are measured within 5 Lab units of their true colour. |
| `test_fixed_green_range_loses_green_kits` | 1 | Documents the old defect: a fixed green range removes the lime shirt entirely. |
| `test_formation_templates_have_ten_outfield_players` | 9 | Every template has exactly 10 slots. |
| `test_noisy_formation_is_recognised` | 9 | Each formation, scaled to a realistic 35 × 50 m team shape with 1.5 m random noise per player, is matched to the correct template. |
| `test_non_finite_numbers_become_null` | 1 | NaN and infinity become `null`, are counted, and the atomic write succeeds. |
| `test_short_ball_gaps_are_interpolated` | 1 | A ball seen in frames 0 and 6 is filled in at frames 2 and 4 at the correct positions and marked as interpolated. |
| `test_smoothing_keeps_raw_positions_and_reduces_jitter` | 1 | Smoothing keeps the raw values and reduces a ±1 m zig-zag to an average step below 0.5 m. |

Listing: A unit test of the RANSAC homography fit (from worker/tests/test_homography.py)
```
def test_fit_ignores_a_wrong_keypoint():
    pitch_points = PitchDimensions().keypoints[[0, 5, 13, 16, 9, 12, 30, 31]]
    image_points = to_image(pitch_points)
    image_points[3] += [400, -250]  # one badly detected landmark
    homography = Homography.fit(image_points, pitch_points)
    assert homography is not None and homography.n_inliers == len(pitch_points) - 1
```

### System tests

The system tests were run against the complete containerised platform through nginx on port 8080, using the dashboard in the Edge browser and, for exact status codes, the REST API with `curl`. The browser tests were scripted with Playwright (`docs/thesis/capture_screenshots.py`), which also produced the screenshots of Chapter 2. Table 3.20 lists the test cases; all of them passed.

Table: System test cases and results {widths=5,30,35,22,8}
| # | Test case | Input / action | Expected result | Result |
|---|---|---|---|---|
| 1 | Health check | GET `/api/health` | 200, database and Redis up, 1 worker | passed |
| 2 | Access without login | GET `/api/matches` without cookie | 401 "Not logged in" | passed |
| 3 | Registration, short password | password "short" | 400, message names the password field | passed |
| 4 | Registration, invalid e-mail | e-mail "not-an-email" | 400 "Invalid email address" | passed |
| 5 | Registration, existing e-mail | "DEMO@example.com" (different case) | 409, e-mail already exists | passed |
| 6 | Registration, valid | new e-mail, 11-character password | 201, logged in | passed |
| 7 | Isolation of users | second user opens the demo user's match | 404 "Match not found" | passed |
| 8 | Isolation of users | second user lists matches | empty list | passed |
| 9 | Login, wrong password | correct e-mail, wrong password | 401 "Invalid email or password" | passed |
| 10 | Upload without file | form without `video` | 400, list of accepted formats | passed |
| 11 | Upload of a non-video | `note.txt` | 400, list of accepted formats | passed |
| 12 | Upload of a disguised file | text file named `.mp4` with type `video/mp4` | 400 "The file is not a valid video" | passed |
| 13 | Upload too large | 501 MB file | 413 "File is larger than 500 MB" | passed |
| 14 | Invalid analysis mode | `mode=turbo` | 400, expected "standard" or "quick" | passed |
| 15 | Valid upload, Quick mode | 3-second clip | 201; Queued → Analysing → Ready with live progress | passed |
| 16 | Valid uploads, Standard mode | five 30-second clips | all Ready, results for both teams | passed |
| 17 | Video seeking | GET video with `Range: bytes=0-999` | 206 Partial Content | passed |
| 18 | Results download | GET results of a finished match | 200, results JSON (562 KB) | passed |
| 19 | Unknown API path | GET `/api/nothing` | 404 "Not found" | passed |
| 20 | Logout | POST logout, then GET `/auth/me` | 204, then 401 | passed |
| 21 | Re-analyse | POST re-analyse on a finished match | 200, status Queued, then Ready again | passed |
| 22 | Re-analyse twice | second request while queued | 409 "already being analysed" | passed |
| 23 | Report before completion | POST report while queued | 409 "Analysis has not finished yet" | passed |
| 24 | Delete during analysis | DELETE while processing | 409, delete when it finishes | passed |
| 25 | Old results during re-analysis | GET results while processing | 200, previous results still served | passed |
| 26 | Video without players | 2-second plain green video | attempt 1 fails, retried, then Failed: "No players were detected in this video" | passed |
| 27 | Delete with confirmation | Delete → Yes on a failed match | card disappears, files removed | passed |
| 28 | Overlays in the browser | play, pause, step frames, toggle all layers and heatmaps | overlays stay on the players in every frame | passed |
| 29 | Player selection | click a player on the video and on the board | player highlighted, panel with heatmap and stats | passed |
| 30 | AI report not configured | GET report without Azure settings | `enabled: false`, dashboard explains why | passed |
| 31 | AI report | Generate report on a finished match | 200 after 12–28 s, Markdown with all sections | passed |
| 32 | Remote GPU | GPU service configured | analysis runs on the GPU, "processed on GPU (NVIDIA L4)" | passed |
| 33 | GPU unreachable | GPU address with no service | `RemoteUnavailable` raised, worker analyses locally | passed |
| 34 | Deep link | open `/matches/<id>` directly in the browser | nginx serves the app, page loads | passed |

### High-volume runs and correctness of the results

The complete test dataset, five 30-second Bundesliga clips (25 fps, 1920 × 1080) from the DFL Bundesliga Data Shootout [3], was analysed in Standard mode, 1,872 analysed frames in total. There is no ground-truth tracking data for these clips, so correctness was assessed through internal quality measures, consistency checks and visual inspection of the overlays (Table 3.21).

Table: Results of the five test clips (Standard mode, NVIDIA L4) {widths=9,9,12,11,15,11,11,22}
| Clip | Frames | Valid homography | Reproj. error | Tracks A / B (unassigned) | Formation windows | Ball detected | Formations A / B |
|---|---|---|---|---|---|---|---|
| 1 | 374 | 100 % | 0.23 m | 10 / 12 (0) | 12 / 12 | 64 % | 3-4-3 / 5-3-2 |
| 2 | 374 | 100 % | 0.24 m | 11 / 11 (0) | 12 / 12 | 73 % | 4-4-2 / 3-4-3 |
| 3 | 375 | 100 % | 0.27 m | 11 / 10 (0) | 12 / 12 | 53 % | 4-3-3 / 4-4-2 |
| 4 | 374 | 100 % | 0.22 m | 11 / 10 (0) | 12 / 12 | 74 % | 4-2-3-1 / 4-1-4-1 |
| 5 | 375 | 100 % | 0.19 m | 17 / 11 (0) | 12 / 12 | 53 % | 3-5-2 / 4-2-3-1 |

The observations from these runs:

- **Camera geometry.** In every clip a homography was available for all analysed frames, and the mean reprojection error of the landmarks was 0.19–0.27 m. A position error of a quarter of a metre is small compared with the distances that matter tactically (the spacing between players is typically 5–15 m).
- **Team assignment.** No player track remained without a team in any clip. Visual inspection confirmed that the colours on the overlay match the kits, including the lime-green kit that had failed before the local grass measurement was introduced. The track counts above 11 (for example 17 in clip 5) are not extra players: a player who is occluded or leaves the picture for more than 2 seconds receives a new ID when they reappear.
- **Formations.** All 60 windows (12 per clip, both teams) contained enough visible players to be classified. The confidence margins between best match and runner-up were small, between 0.0003 and 0.039, with most below 0.03; this confirms that neighbouring templates are often close and justifies the hysteresis margin of 0.03, which kept the number of reported formation changes to 1–4 per clip.
- **Plausibility of physical data.** Team distances of 0.55–0.83 km per 30 seconds for about ten visible outfield players correspond to roughly 1.8–2.8 m/s per player, a realistic pace for professional football. The median of the players' top speeds was 17–28 km/h per clip, and the fastest players reached 24–30 km/h, typical sprint speeds. The single highest value, 39.6 km/h in clip 3, is above what professional players reach (about 36 km/h); it shows that residual projection noise can still inflate an individual step, and a lower plausibility limit or smoothing of the speed itself would reduce such outliers.
- **Ball.** The ball was detected in 53–74 % of the analysed frames; the interpolation of short gaps increases the coverage of the ball trajectory to 88–98 %. Missed detections occur mainly when the ball is in the air, occluded or blurred.
- **Reproducibility.** Clip 1 was analysed both on the laptop CPU and on the cloud GPU and both runs reported the same formations (3-4-3 and 5-3-2); the results do not depend on the hardware. K-Means uses a fixed seed, so repeated runs on the same machine give identical team assignments.

### Efficiency

Table 3.22 and Figure 3.16 compare the processing times. The analysis is dominated by the two neural networks, so the GPU gives a large speed-up: a 30-second clip in Standard mode takes about 25 minutes on the development laptop's CPU and 36.6–41.3 seconds (mean 38.7 s) on an NVIDIA L4. Including the upload of the video to the GPU service and the download of the results, the total is about 53 seconds, still a 28-fold speed-up. The advantage grows with the length of the clip because the fixed costs (upload, model start-up) matter less.

Table: Processing times {widths=34,22,22,22}
| Job | Laptop CPU (i7-1255U) | Docker on the laptop (CPU) | Cloud GPU (NVIDIA L4) |
|---|---|---|---|
| 3 s clip, Quick mode | 44–75 s | 93 s (207 s on the first job) | 5.1 s |
| 30 s clip, Standard mode | about 25 min | not measured | 36.6–41.3 s |

![Processing time on the laptop CPU and on the cloud GPU (logarithmic scale)](figures/performance.png){w=14}

Three observations shaped the implementation:

- The first job after a worker starts takes longer because the models are loaded and initialised; caching the models per process (Section 3.5.9) means later jobs do not pay this cost again.
- Inside Docker on Windows the analysis was slower than natively, because the containers run in a virtual machine (WSL 2) with a limited share of the processor and memory. On a Linux server this overhead does not exist.
- The laptop's own GPU, a GeForce MX550 with 2 GB of memory, was about twice as **slow** as its CPU for these large models, so the worker defaults to the CPU and the GPU acceleration was moved to a dedicated cloud service.

Memory use does not grow with the video length for the video itself, because frames are streamed in batches of four. The tracking table grows linearly (about 9,000 rows for 30 seconds), which for a full match amounts to roughly 1.6 million rows, well within the memory of a normal server.

### Scalability

- **More workers.** Workers share nothing but the queue and the storage, and the queue hands each job to exactly one worker, so throughput scales with the number of workers. Additional workers can be started with `docker compose --profile app up -d --scale worker=N` or on other machines; on a single CPU-bound machine extra workers only help if spare cores exist. Workers on other machines need access to the same storage, for example a network file system or, in a future version, object storage.
- **GPU capacity.** The GPU service is stateless apart from running jobs and can be run on several GPU machines; each worker can be pointed at a different service.
- **API.** The API is stateless except for the Socket.IO rooms. Running several API instances behind a load balancer would require the Socket.IO Redis adapter so that events reach users connected to another instance; the database load (a few small queries per request) is negligible.
- **Longer videos.** Processing time grows linearly with the number of frames. The results file also grows linearly (0.55 MB per 30 seconds, roughly 100 MB for a full match); for full matches the dashboard should load the results in time segments instead of as one file, which is listed as future work.
- **Faster analysis without new hardware.** Quick mode analyses 2.5 times fewer frames at a lower resolution; the stride, resolution and pitch-model frequency are configuration values, so further trade-offs need no code changes.

### Lessons learnt during testing

Testing revealed several defects and weaknesses, which led to changes in the implementation and in some cases in the design. Table 3.23 summarises them. Each defect in the algorithms received a regression test, so it cannot silently return.

Table: Problems found during testing and the resulting changes {widths=34,66}
| Problem found | Change |
|---|---|
| Uploaded clips did not play in the browser: the dataset's videos use a codec that browsers do not support. | New pipeline stage: an H.264 playback copy with a constant frame rate, which also guarantees frame-exact overlays. |
| Two of the five clips failed with "out of range float values: nan": for some camera angles the last element of the exported matrix was nearly zero, and dividing by it produced NaN. | Matrices are normalised by their norm with a fixed sign; a safety net replaces any non-finite number; the dashboard blends matrices element-wise; regression test added. |
| In one clip a team in a lime-green kit was not recognised: the fixed "green = grass" colour range removed the shirts too. | The grass colour is measured in a ring around each player and compared in Lab space; two regression tests added. |
| Goalkeepers were often labelled "player" by the detector and joined an outfield team. | Roles are decided per track; a track with at least 25 % goalkeeper detections is a goalkeeper; goalkeepers are assigned by position. |
| The reported formation flickered between similar templates every window. | Hysteresis: a formation changes only if the new one is better by 0.03, a value derived from the measured margins. |
| The progress bar sometimes jumped backwards. | Database updates of each match are chained so they complete in arrival order. |
| A re-analysis request was accepted but nothing happened: BullMQ ignores a new job whose ID still exists from the previous run. | The finished previous job is removed before the new one is added. |
| The health check showed 0 workers while the Python worker was running. | Workers are counted from Redis's client list, accepting both naming schemes. |
| Movement paths ended slightly behind the player markers during sprints, because the paths use smoothed positions. | Paths end at the detected feet of the current frame. |
| The laptop GPU was slower than the CPU. | CPU by default; optional cloud GPU service with fallback. |
| The code failed on the cloud machine's Python 3.11 because of a function introduced in Python 3.12. | Replaced with a compatible equivalent; the CI pipeline pins Python 3.12 for the worker. |
| The tracking library used originally (ByteTrack in supervision 0.31) had been removed in that version. | Switched to the `trackers` package, which provides ByteTrack with timestamp support for strided frames. |

The most important general lesson was that every real clip exposed problems that synthetic tests had not: the codec, the camera angles and the kit colours were all specific to real footage. Testing on the full dataset early and turning each discovered defect into a unit test proved to be the most effective approach.

## Limitations and future work

The current version has the following known limitations, each with a possible extension:

- **Single camera.** Only players visible in the broadcast view are analysed. Combining several camera angles or tactical-camera footage would cover the whole pitch.
- **No event detection.** Passes, shots, tackles and possession are not detected. Ball-to-player proximity over time could be used to estimate possession and passes.
- **Identities.** Players are identified by tracker ID. Re-identification by appearance and recognition of shirt numbers would keep one identity per player for the whole match and allow named statistics.
- **Long videos in the dashboard.** The results of a full match should be loaded in segments, and the analysis could process a long match in parallel chunks on several workers.
- **Scaling out.** Object storage instead of a shared folder, the Socket.IO Redis adapter and an orchestrator such as Kubernetes would allow the platform to run on several machines.
- **Monitoring.** The health endpoint reports the state of the database, the queue and the workers. Exporting metrics (queue length, processing times, error rates) to a monitoring system such as Prometheus and Grafana would allow long-term observation and alerting.
- **Ground truth.** A quantitative evaluation against manually annotated or sensor-based tracking data would measure the accuracy of positions and formations more precisely than the internal measures used here.

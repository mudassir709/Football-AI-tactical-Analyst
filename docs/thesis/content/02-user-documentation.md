# User Documentation

This chapter is written for the people who use Tactical Eye: coaches and analysts who upload and study matches, and the operator who installs and runs the platform. It explains what the software does, what is needed to run it, how to install and start it, and how to use every function of the dashboard. The last sections list every message the system can show and what to do about it.

## What is Tactical Eye for?

Tactical Eye turns football match footage into tactical information without any manual annotation. The user uploads a video recorded by a broadcast-style camera (a wide view of the pitch that pans to follow play). The platform then automatically:

- finds every player, goalkeeper, referee and the ball in the video and follows each of them through the clip;
- converts their positions from the camera image into real pitch coordinates in metres;
- works out which players belong to which team from the colour of their shirts;
- recognises the formation of each team (for example 4-4-2 or 5-3-2) and how it changes over time;
- measures how compact, wide and deep each team is, how far and how fast every player runs, and where on the pitch each team and the ball spent their time.

The results are shown on top of the original video, so the user can watch the match and see the tactical structure at the same time. A 2D tactical board shows the same moment from above, and an AI-generated coaching report summarises the findings in plain language.

## Target audience and user levels

Tactical Eye is intended for coaches, video analysts and scouts of amateur and youth clubs, for students of the game, and for anyone who has match video but no access to commercial tracking data. Using the dashboard requires no technical knowledge; it runs in an ordinary web browser. Table 2.1 lists the user levels.

Table: User levels and what each can do {widths=22,78}
| User level | Functions |
|---|---|
| Visitor (not logged in) | Open the login page, create an account, log in. Every other page redirects to the login page. |
| Registered user | Upload matches, follow the analysis live, list own matches, watch the interactive analysis, inspect players, read the summary, generate the AI coaching report, re-analyse and delete own matches, log out. A user only ever sees their own matches. |
| Operator | Installs and runs the platform (Section 2.4), configures the optional cloud GPU and AI report service, and monitors the system through the health endpoint. The operator works with the server, not through the dashboard. |

There is no separate administrator role inside the dashboard: every registered user manages their own data, and the system has no shared content that would need moderation.

## System requirements

The platform has two sides. **Users** only need a browser. The **server** (which can be the same computer, for example a laptop used for a demonstration) runs the services.

Table: Requirements for users (client side) {widths=28,36,36}
| | Minimum | Recommended |
|---|---|---|
| Browser | Current Chrome, Edge, Firefox or Safari with HTML5 video and WebSocket support | Latest Chrome or Edge (supports frame-exact overlay synchronisation, see Section 3.8.4) |
| Screen | 1280 × 720; the layout also adapts to tablets and phones | 1920 × 1080 or larger |
| Network | Access to the server; upload speed matters for large videos | Wired or fast Wi-Fi connection |

Table: Requirements for the server {widths=22,39,39}
| | Minimum | Recommended |
|---|---|---|
| Operating system | Windows 10/11, macOS or Linux that runs Docker | Linux server or Windows 11 with WSL 2 |
| Software | Docker Desktop (or Docker Engine with Compose v2) | Same; Git to download and update the code |
| Processor | 4-core x86-64 CPU | 8 or more cores, or an NVIDIA GPU (locally or as the cloud GPU service) |
| Memory | 8 GB RAM | 16 GB RAM or more |
| Disk | 10 GB free (Docker images about 4 GB, AI models 270 MB, plus videos) | 50 GB or more for a library of matches |
| Network | Internet access while building the images | Internet access for the optional cloud GPU and AI report |

The analysis is computationally heavy. On the development laptop (Intel Core i7-1255U, 8 GB RAM) a 30-second clip takes about 25 minutes in Standard mode; on a cloud NVIDIA L4 GPU it takes about 40 seconds (Section 3.11.5). The platform works on modest hardware, it is simply slower.

## Installation and start-up

The whole platform is started with a single Docker command. Docker downloads and builds everything else, so no programming tools have to be installed.

### Getting the software

1. Install **Docker Desktop** from docker.com and start it. On Windows, accept the installation of WSL 2 when asked.
2. Download the source code, either as a ZIP file from the GitHub repository or with Git:
```
git clone https://github.com/mudassir709/Football-AI-tactical-Analyst.git
cd Football-AI-tactical-Analyst
```
3. Download the two pretrained AI models and save them in the folder `worker/models/` under exactly these names: `football-player-detection.pt` (player, goalkeeper, referee and ball detector) and `football-pitch-detection.pt` (pitch landmark detector). The download links are listed in `worker/gpu/setup.sh`. The models are not part of the repository because of their size (270 MB together).

### Configuration

Settings are kept in a file called `.env` in the main folder. Copy the provided template `.env.example` to `.env` and edit the values in a text editor. Table 2.4 explains each setting. The `.env` file contains passwords and keys: it must never be shared or uploaded, and the repository is configured to ignore it.

Table: Settings in the .env file {widths=30,15,55}
| Setting | Required | Meaning |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | yes | Name, password and database name for the PostgreSQL database. |
| `DATABASE_URL` | yes | Connection address of the database (used when the API runs outside Docker). |
| `JWT_SECRET` | yes | Long random secret (at least 32 characters) used to sign login sessions. Generate one with the command given in the template. |
| `REDIS_URL`, `API_PORT`, `STORAGE_DIR`, `FRONTEND_URL` | no | Addresses and folders; the defaults work. |
| `GPU_SERVER_URL`, `GPU_SERVER_TOKEN` | no | Address and shared secret of the optional cloud GPU service (Section 2.4.6). Leave the address empty to analyse on the server itself. |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` | no | Enable the AI coaching report (Section 2.4.7). Without them the report card says that reports are not configured. |

### Starting the platform

Open a terminal in the main folder and run:

```
docker compose --profile app up -d --build
```

The first start takes several minutes because Docker downloads the base images and installs the AI libraries. Later starts take a few seconds. When the command finishes, open **http://localhost:8080** in a browser. The database tables are created automatically on the first start.

Docker starts five containers (Table 2.5). They restart automatically if they crash or when the computer restarts while Docker is running.

Table: The containers of the platform {widths=18,82}
| Container | Purpose |
|---|---|
| `frontend` | Serves the dashboard on port 8080 and forwards API and WebSocket traffic to the backend. |
| `backend` | The API: accounts, uploads, match records, job queue, live updates, AI reports. |
| `worker` | The AI worker that analyses the videos. |
| `postgres` | The database (users and matches). Data is kept in a Docker volume. |
| `redis` | The job queue between the API and the worker. |

### Checking that everything works

Open **http://localhost:8080/api/health**. A healthy system answers with `"status":"ok"`, `"database":"up"`, `"redis":"up"` and `"workers":1`, followed by the number of jobs in each state. If `workers` is `0`, the worker container is not running or is still starting; `docker compose ps` lists the state of every container and `docker compose logs worker` shows its log.

### Stopping and updating

- `docker compose --profile app stop` stops the platform; `docker compose --profile app up -d` starts it again. Stored matches and accounts are kept.
- To update to a new version, download the new code (`git pull`) and run the start command with `--build` again. The CI/CD pipeline also publishes ready-made images to the GitHub Container Registry (Section 3.3.3).
- Uploaded videos and results are stored in the `storage/` folder; copying this folder and the database volume backs up all data.

### Optional: analysing on a cloud GPU

Analysis on a CPU is slow. The worker can send videos to a GPU analysis service running on a rented cloud machine and receive the results back, which is about 37 times faster. The service is set up once on a machine with an NVIDIA GPU (the project used RunPod, about USD 0.40 per hour for an NVIDIA L4):

1. Create a GPU machine with a PyTorch image and expose port 8000.
2. Upload `tactical-eye-gpu.zip` (created with `python worker/gpu/make_bundle.py`), unpack it and run `bash gpu/setup.sh`, which installs the libraries and downloads the models.
3. Start the service with the same token as in `.env`: `GPU_SERVER_TOKEN=... bash gpu/start.sh`.
4. Put the service address in `GPU_SERVER_URL` in `.env` and restart the worker with `docker compose --profile app up -d worker`.

If the GPU service is switched off or unreachable, the worker automatically analyses the video on the server instead, so no job is lost. The dashboard shows where each match was processed, for example "on GPU (NVIDIA L4)". Remember to delete the cloud machine when it is no longer needed, because it is billed while it runs.

### Optional: enabling the AI coaching report

The coaching report is written by a large language model deployed on Microsoft Azure OpenAI. Create an Azure OpenAI resource, deploy a chat model (the project uses `gpt-5-mini`), and copy the resource's endpoint, key and deployment name into the three `AZURE_OPENAI_...` settings. Restart the backend with `docker compose --profile app up -d backend`. Only the computed statistics are sent to Azure, never the video.

## Getting started

### Creating an account and logging in

Opening the dashboard without being logged in shows the **Log in** page (Figure 2.1). New users click **Create an account** and fill in their name, e-mail address and a password of at least 8 characters (Figure 2.2). After registering, the user is logged in immediately and taken to the list of matches.

![The log in page](figures/ss_01_login.png){w=7.2}

![Registration page](figures/ss_03_register.png){w=7.2}

If the e-mail address or password is wrong, the page shows **Invalid email or password** (Figure 2.3). The message does not reveal whether the e-mail address is registered, which protects users' privacy. The session lasts seven days; after that, or after **Log out**, the user has to log in again.

![A failed login attempt](figures/ss_02_login_error.png){w=7.2}

### Navigation

After logging in, every page has the same header (visible in Figure 2.4): the **Tactical Eye** logo (links to the match list), the **Matches** and **Upload** menu items, the user's name, and **Log out**. The current page is highlighted in the menu. The dashboard is a single-page application: moving between pages does not reload the browser window, and the browser's back and forward buttons work as usual.

## The match list

The **Matches** page (Figure 2.4) lists the user's uploads, newest first, as cards. Each card shows the title, the upload date, the file size and, for Quick-mode analyses, the label "Quick mode". A coloured badge shows the state of the analysis (Table 2.6). For finished matches, the card shows each team's kit colour and its most frequent formation. The **Upload a match** button opens the upload page; **Open analysis** opens the results.

![The match list with five analysed Bundesliga clips](figures/ss_04_matches.png){w=15.5}

Table: Status badges {widths=18,82}
| Badge | Meaning |
|---|---|
| Queued | The video is stored and waiting for a free worker. Videos are analysed one at a time, in upload order. |
| Analysing | A worker is processing the video. The card shows a progress bar and the current step. |
| Ready | The analysis is finished and can be opened. |
| Failed | The analysis could not be completed. The card shows the reason (Section 2.11). |

The list updates itself: progress bars move, badges change and new matches appear without reloading the page, because the server pushes every change to the browser.

## Uploading a match

1. Click **Upload** in the header or **Upload a match** on the match list (Figure 2.5).
2. Drag a video file onto the dashed area, or click it to choose a file. Accepted formats are MP4, MOV, M4V, MKV, WebM and AVI, up to 500 MB. The chosen file's name and size are shown in the area (Figure 2.6).
3. Optionally change the **Title**. It is filled in from the file name and can be up to 120 characters long.
4. Choose the **Analysis mode** (Table 2.7).
5. Click **Upload and analyse**. A progress bar shows the upload. When it completes, the dashboard opens the new match's page, where the analysis progress is shown.

![The upload page before a file is chosen](figures/ss_05_upload_empty.png){w=11}

![A file is chosen and Quick mode is selected](figures/ss_07_upload_ready.png){w=11}

Table: Analysis modes {widths=16,42,42}
| Mode | What it does | When to use it |
|---|---|---|
| Standard | Analyses every 2nd frame at the full 1280-pixel detection resolution. | Best accuracy; the default. About 4–5 seconds of processing per second of video on a strong machine, much longer on a laptop CPU. |
| Quick | Analyses every 5th frame at 960 pixels. | Several times faster; ideal for short clips, previews and live demonstrations. The ball is detected less often. |

Footage from the main, wide broadcast camera gives the best results. Close-ups, replays and crowd shots contain no usable pitch view; the analysis skips over such parts, but a clip consisting mostly of them cannot be analysed (Section 2.11).

The server checks every upload. If the file is not a real video, for example a text file renamed to `.mp4`, it is rejected with **The file is not a valid video** and nothing is stored (Figure 2.7).

![An invalid file is rejected](figures/ss_06_upload_invalid_file.png){w=11}

## Following the analysis

While a video is being analysed, its page shows a progress bar with the current step (Figure 2.8). The page updates live; the user can leave it, close the browser or upload further matches, and the analysis continues on the server. The match list shows the same progress on the match's card (Figure 2.9). Table 2.8 lists the steps.

![Analysis in progress](figures/ss_08_match_in_progress.png){w=15.5}

![Live progress on the match list](figures/ss_09_matches_live_progress.png){w=15.5}

Table: Steps of the analysis as shown in the progress bar {widths=36,12,52}
| Step | Progress | What happens |
|---|---|---|
| Preparing video for playback | 0–5 % | A browser-compatible copy of the video is made. |
| Detecting and tracking players | 5–60 % | Every person and the ball are found in each analysed frame and followed through the clip. |
| Mapping positions to the pitch | 60–88 % | Pitch markings are recognised and positions are converted to metres. |
| Assigning teams | 88–93 % | Players are split into two teams by shirt colour. |
| Analysing tactics | 93–98 % | Positions are smoothed, formations and metrics are computed. |
| Saving results | 98–100 % | The results are stored; the page switches to the analysis view. |

When a GPU service is configured, the steps additionally show "Uploading video to GPU" and the GPU's name. If a step fails, the worker retries the whole analysis once after 10 seconds; during that time the bar shows "Retrying after an error".

## The analysis page

When the analysis is finished, the match page shows the interactive analysis (Figure 2.10). Its parts are described in the following sections:

- the **video player** with tactical overlays and playback controls (left);
- the **layer controls** below the video;
- the **tactical board**, the **current formations** and the legend (top right);
- the **player panel** (bottom right);
- the **summary** with headline numbers per team, and the **AI coaching report** (further down).

The **Re-analyse** button in the top right corner and the **← All matches** link are described in Section 2.10.

![The analysis page of a finished match](figures/ss_10_match_page.png){w=15.5}

### Video player and controls

The video plays inside the page. The browser's own controls are replaced by the controls below the video, because the overlay covers the video surface (Table 2.9).

Table: Video controls {widths=26,74}
| Control | Action |
|---|---|
| Play / Pause | Starts or pauses playback. Clicking an empty spot of the video does the same. |
| ◀ 1f / 1f ▶ | Pauses and steps exactly one frame backwards or forwards, for studying a situation in detail. |
| Seek bar | Jumps to any moment of the clip; the time is shown as minutes:seconds.tenths. |
| Speed (1×, 0.5×, 0.25×) | Slows playback down; the overlays stay synchronised at every speed. |

All overlays follow the video frame by frame, including while the camera pans and zooms, because they are re-projected through the camera geometry of each frame (Section 3.8.4).

### Overlay layers

The layer buttons (Figure 2.11) switch the drawings on the video and on the tactical board on and off. A highlighted button means the layer is visible.

![Layer controls](figures/ss_15_layer_controls.png){w=15.5}

Table: Overlay layers {widths=22,78}
| Layer | What is drawn |
|---|---|
| Players | An ellipse at each person's feet in the team colour, with a label: the tracker ID for players, "GK" and the ID for goalkeepers, "REF" for referees (yellow). |
| Movement paths | Each player's path over the last 4 seconds, drawn on the grass and fading out with age (Figure 2.12). |
| Team shape | The area enclosed by each team's outfield players, filled with the team colour (Figure 2.13). A small area means a compact team. |
| Ball | A marker on the ball and its recent path. |
| Heatmap (menu) | Off, Team A, Team B or Ball: shows where that team's players, or the ball, spent the most time during the whole clip, from blue-green (rarely) to red (most often), painted on the pitch (Figures 2.14 and 2.15). |

![Players and movement paths drawn on the video](figures/ss_11_overlay_players_paths.png){w=14}

![The team shape layer](figures/ss_12_overlay_team_shape.png){w=14}

![Heatmap of Team A painted onto the pitch in the video](figures/ss_13_overlay_heatmap_team_a.png){w=14}

![Heatmap of the ball](figures/ss_14_overlay_heatmap_ball.png){w=14}

If a match was analysed with an older version of the software, paths and heatmaps on the video are unavailable and a note asks the user to re-analyse the match.

### Tactical board and formations

The **tactical board** (Figure 2.16, top) shows the same moment as the video from above, on a to-scale 105 × 68 m pitch. Each dot is a person in team colours; the ball is shown as a small marker. The board uses the same layers as the video, so paths, team shapes and heatmaps can also be seen on it. Unlike the video, the board shows the positions in true metric proportions, which makes distances and spacing easy to judge.

Below the board, two cards show the **formation** each team is playing at the current moment, for example 3-4-3 and 5-3-2, together with the "runner-up": the second most likely formation. A close runner-up means the team's shape is between two formations. The formation is determined in 5-second windows and updates as the video plays. The legend explains the colours: Team A (the lighter kit), Team B and the referees.

![Tactical board, current formations and the player panel](figures/ss_17_board_and_player_panel.png){w=8.5}

### Inspecting a player

Clicking a person on the video or on the board selects them: their marker is highlighted and the **player panel** (Figure 2.16, bottom) shows:

- the role and tracker ID (for example "Player #2, Team A");
- a small pitch with the player's **heatmap** and **complete path** over the whole clip;
- **Distance** covered in metres, **Time visible** in seconds, **Avg speed** and **Top speed** in km/h.

Clicking the same person again, or **Close**, removes the selection. Statistics are only measured while the player is visible to the camera; a player who leaves the picture is not followed.

### Summary

Below the video, the summary (Figure 2.17) shows headline numbers. The first row describes the clip: its length, the number of frames analysed, the share of analysed frames in which the ball was found, and how long the analysis took and on what hardware. Then each team has a card with its kit colour, its most frequent formation and the metrics in Table 2.11.

![The summary of a match](figures/ss_18_summary.png){w=15.5}

Table: Team metrics in the summary {widths=24,76}
| Metric | Meaning |
|---|---|
| Compactness | Average area (m²) of the shape enclosed by the team's outfield players. Smaller values mean the team stays close together, typical of defending. |
| Distance covered | Total distance run by the team's outfield players while visible, in kilometres. |
| Width | Average distance (m) between the team's outermost players across the pitch. |
| Depth | Average distance (m) between the team's deepest and most advanced players. |

### AI coaching report

At the bottom of the page, the **AI coaching report** card (Figure 2.18) turns the statistics into a short written analysis. Click **Generate report**; after about 10–30 seconds the report appears with the sections Overview, Team A, Team B, Shape over time, Recommendations and Data limitations. The report is stored with the match, so it is shown immediately the next time the page is opened. **Regenerate** writes a new version.

The report is based only on the measured numbers: formations over time, compactness, width and depth in each third of the clip, and the most active players. It is instructed not to invent events that are not measured, such as passes or goals, and to point out the limits of a short clip. It is a starting point for the coach's own analysis, not a replacement for it.

![The AI coaching report](figures/ss_19_coaching_report.png){w=13}

## Re-analysing and deleting matches

**Re-analyse** (top right of the match page) queues the analysis of the stored video again, in the same mode. This is useful after a software update or when an earlier analysis failed. The previous results stay visible until the new analysis has finished.

**Delete** (on the match card) removes the match, its video and all results permanently. To prevent accidents, the card asks **Delete?** with **Yes** and **No** buttons (Figure 2.19). A match cannot be deleted while it is being analysed; the button is disabled with the tooltip "Cannot delete while analysing". A match waiting in the queue can be deleted, and its job is removed from the queue.

![A failed analysis and the delete confirmation](figures/ss_21_matches_failed_and_delete_confirm.png){w=15.5}

## Messages and troubleshooting

### Error messages

Errors are shown in red boxes next to the action that caused them, or on the card and page of the affected match (Figure 2.20). Table 2.12 lists every error message and what to do.

![The page of a match whose analysis failed](figures/ss_20_match_failed.png){w=15.5}

Table: Error messages {widths=36,30,34}
| Message | Cause | What to do |
|---|---|---|
| Invalid email or password | Wrong e-mail address or password at login. | Check both and try again. |
| An account with this email already exists | Registration with an e-mail address that is already used. | Log in instead, or use another address. |
| Password must be at least 8 characters | The registration password is too short. | Choose a longer password. |
| Upload a video file (.mp4, .mov, .m4v, .mkv, .webm, .avi) | No file was sent, or its extension or type is not a video. | Choose a file in one of the listed formats. |
| The file is not a valid video | The file's content is not a video, even if its name ends in a video extension. | Export or download the video again. |
| File is larger than 500 MB | The upload exceeds the size limit. | Shorten or compress the video, or ask the operator to raise `MAX_UPLOAD_MB`. |
| Network error during upload | The connection to the server was lost during the upload. | Check the connection and upload again. |
| Could not queue the analysis job | The video was stored but the queue (Redis) was unreachable; the match is marked Failed. | Operator: check the health endpoint; then use Re-analyse. |
| No players were detected in this video | The analysis found no people, e.g. the video shows no football or only close-ups. | Use footage from the main broadcast camera. |
| Error, retrying: … / Retrying after an error | An analysis attempt failed; it is retried once automatically. | Wait. If the second attempt fails too, the match becomes Failed. |
| Match not found | The match was deleted, or the link belongs to another user's match. | Return to the match list. |
| This match is already being analysed | Re-analyse was requested while the match is queued or being analysed. | Wait until the current analysis has finished. |
| This match is being analysed; delete it when it finishes | Deletion during analysis. | Wait until the analysis has finished or failed. |
| Analysis has not finished yet | Results or a report were requested before the analysis completed. | Wait for the Ready badge. |
| The report service is busy; try again in a minute | The AI service limits how many requests it accepts. | Try again after a minute. |
| Could not reach the report service | No connection to Azure OpenAI. | Check the server's internet connection. |
| The Azure OpenAI key is invalid / Azure OpenAI deployment not found | The AI report is configured incorrectly. | Operator: correct the `AZURE_OPENAI_...` settings and restart the backend. |
| The report was blocked by the Azure content filter / The report came back empty / The report was cut off | The AI service did not return a usable report. | Click Regenerate. |
| Internal server error | An unexpected error on the server; details are written to the server log. | Try again; operator: inspect `docker compose logs backend`. |

### Information and warning messages

Table: Information and warning messages {widths=45,55}
| Message | Meaning |
|---|---|
| No matches yet. Upload a broadcast clip to get started. | The user has not uploaded anything. |
| This page updates live. You can leave it; the analysis keeps running on the server. | Shown during the analysis. |
| Click a player on the video or the board to see their movement, heatmap and physical stats. | No player is selected. |
| Paths and heatmaps on the video need a newer analysis of this match. Use "Re-analyse" above to enable them. | Warning: the match was analysed by an older version without per-frame camera geometry. |
| Coaching reports are not configured on this server (Azure OpenAI settings are needed). | The operator has not enabled the AI report. |
| Analysing the statistics (about 10-30 seconds) | A report is being written. |
| Cannot delete while analysing | Tooltip of the disabled Delete button. |

### Frequently asked questions

**The analysis is very slow.** Analysis on a CPU takes several times the length of the video. Use Quick mode for previews, analyse shorter clips, or configure the cloud GPU service (Section 2.4.6).

**The match stays "Queued".** No worker is running. Open `/api/health`: if `workers` is `0`, start the worker with `docker compose --profile app up -d worker`. Matches are analysed one at a time, so a queued match may simply be waiting for an earlier one.

**Some players are missing or have no team.** Only players visible to the camera can be analysed. Players who are hidden for a long time may receive a new tracker ID when they reappear.

**The formation looks wrong.** A formation needs at least 8 outfield players of the team to be visible in a 5-second window; otherwise no formation is shown for that window. When the runner-up formation is close, the team's shape is genuinely between two formations.

**The video does not play.** The platform converts every upload into a browser-compatible format. If the browser still cannot play it, update the browser; Chrome and Edge are recommended.

### Security and privacy

- Passwords are never stored, only a salted bcrypt hash of them. Sessions are kept in a cookie that page scripts cannot read.
- Users can only see, change and delete their own matches; links to other users' matches answer "Match not found".
- Uploaded files are checked for real video content and stored under random names.
- The AI report service receives only the computed statistics, never the video or personal data.
- In a deployment reachable from the internet, the operator should serve the platform over HTTPS (for example behind a reverse proxy with a certificate) and keep `COOKIE_SECURE` at its default.

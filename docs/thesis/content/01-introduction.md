# Introduction

## Motivation

Football is increasingly analysed with data. Professional clubs employ analysts who measure how compact a team is when it defends, which formation it adopts, how far each player runs and where on the pitch the play happens. These numbers inform training, scouting and match preparation. The data behind them, however, usually comes from expensive sources: multi-camera optical tracking systems installed in stadiums, wearable GPS vests, or commercial data providers whose operators annotate every match by hand. Amateur clubs, academies, small coaching teams and students of the game have none of these, but they do have something else: video. Matches are filmed and broadcast footage is widely available.

The question behind this thesis is how much of the professional tactical picture can be recovered *automatically* from ordinary broadcast-style video, and how that information can be presented so that a coach can actually use it. Modern computer vision makes the first part feasible. Object detectors such as YOLO [1] find players and the ball in a frame in milliseconds, multi-object trackers such as ByteTrack [2] follow them over time, and classical projective geometry can map the camera image onto a flat model of the pitch. The second part is a software engineering problem: the analysis is slow and resource-hungry, so it cannot run inside a web request, and the results are only valuable if they are shown in context, on top of the video they came from.

## Objectives

The aim of the project was to build **Tactical Eye**, a complete web platform for automated video analytics and tactical visualisation of football matches. Concretely, the system had to:

- let users create an account and upload match footage through a responsive web dashboard;
- analyse the footage in the background with computer vision: detect and track every player, goalkeeper, referee and the ball, map them onto real pitch coordinates in metres, assign players to teams and recognise each team's formation over time;
- compute tactical and physical metrics such as team compactness, width and depth, distance covered, speeds and heatmaps;
- show the results as **interactive overlays drawn directly on the video player** (movement paths, heatmaps, team shapes), together with a synchronised 2D tactical board and per-player statistics;
- turn the computed statistics into a written coaching report using a large language model (LLM);
- be built as a **distributed system**: a web API that accepts jobs, a queue, and separate AI workers that process them, with live progress pushed to the browser;
- be easy to deploy, update and monitor: every service is containerised with Docker, and an automated CI/CD pipeline tests the code and publishes the images.

## Overview of the solution

Tactical Eye consists of four cooperating services (Figure 1.1). The **React dashboard** runs in the browser. It handles uploads, shows live progress and renders the interactive analysis. The **Node.js API** authenticates users, stores uploaded videos, records matches in a **PostgreSQL** database and places analysis jobs on a **Redis** queue. A **Python AI worker** takes jobs from the queue, runs the computer vision pipeline and reports progress back through the queue; the API forwards every update to the user's browser over a WebSocket. Heavy analysis can optionally be offloaded to a rented **cloud GPU**, which reduces the processing time of a 30-second clip from about 25 minutes on a laptop CPU to about 40 seconds. Finally, the API can ask a large language model on **Azure OpenAI** to write a coaching report from the computed numbers.

![High-level architecture of Tactical Eye](figures/architecture.png){w=12}

Figure 1.2 shows the result from the user's point of view: an analysed Bundesliga clip with player markers, movement paths and team colours drawn on the video, the 2D tactical board with both formations on the right, and the statistics of a selected player.

![The analysis page: video overlays, tactical board, current formations and a selected player](figures/ss_16_player_selected.png){w=16}

## Scope and limitations

The platform works with a single broadcast camera. It therefore sees only the part of the pitch that the camera shows, and it measures positions, movement and shape rather than events: passes, shots and possession are not detected. Players are identified by tracker ID, not by name or shirt number. The analysis was tested on 30-second clips from the public DFL Bundesliga Data Shootout dataset [3]; full 90-minute matches are supported by the design (the worker streams the video and never holds it in memory) but take proportionally longer to process. These limitations are discussed in Section 3.12.

## Structure of the thesis

**Chapter 2** is the user documentation. It describes what the software is for and who it is for, the hardware and software requirements, the installation process, and every function of the dashboard step by step with screenshots, including all messages the system can show. **Chapter 3** is the developer documentation. It specifies the requirements, presents the architecture, the database and the data formats, explains the computer vision algorithms in detail, describes the modules of each service and the most important implementation decisions, and reports on testing: automated unit tests, system tests, runs on the full dataset, correctness and efficiency measurements, scalability, and the lessons learnt during testing. **Chapter 4** concludes the thesis and outlines possible future work.

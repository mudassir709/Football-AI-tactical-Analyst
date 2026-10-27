# Conclusion

The goal of this thesis was to build a complete platform that turns ordinary football footage into tactical information and presents it where it is most useful: on top of the video itself. Tactical Eye achieves this goal. A user uploads a broadcast clip through a web dashboard, follows the analysis live, and receives an interactive view in which every player, their movement paths, the shape of both teams and heatmaps are drawn onto the video, frame by frame, while a 2D tactical board, formation recognition, physical statistics and an AI-written coaching report complete the picture.

On the analysis side, the project combines deep-learning models with classical algorithms. YOLOv8 detects players, goalkeepers, referees and the ball, and ByteTrack follows them through the clip. A per-frame homography, estimated with RANSAC from 32 detected pitch landmarks, converts their positions into metres. Teams are separated by K-Means clustering of shirt colours measured against the local grass in Lab colour space, and formations are recognised by optimal template matching with the Hungarian algorithm, stabilised by hysteresis. On the five test clips, the camera geometry was available in every analysed frame with a reprojection error of about a quarter of a metre, every player track was assigned to a team, and every formation window was classified.

On the engineering side, Tactical Eye is a distributed system. A TypeScript API accepts uploads and queues jobs; Python workers process them independently and report progress, which reaches the browser instantly over WebSockets; the heavy computation can be moved to a cloud GPU, reducing the analysis of a 30-second clip from about 25 minutes to about 40 seconds, with automatic fallback when the GPU is unavailable. Every service runs in a Docker container, the whole platform starts with one command, and a CI/CD pipeline checks, tests, builds and publishes the images on every change.

The work also showed where the difficulties of such a system lie. Most of the defects found during testing came from properties of real footage: video codecs browsers cannot play, camera angles that make a matrix nearly singular, kits that share the colour of the grass. Testing early on the full dataset and turning every discovered defect into an automated regression test was therefore essential, and the resulting design choices, such as the playback transcoding, the norm-based matrix normalisation and the local grass measurement, make the platform considerably more robust than the first prototype.

Tactical Eye shows that a substantial part of the tactical analysis that professional clubs obtain from expensive tracking systems can be recovered automatically from a single broadcast camera, and delivered through a responsive, deployable web platform. The extensions outlined in Section 3.12, in particular event detection, persistent player identities and support for full-length matches in the dashboard, would bring it closer still to the tools used in professional football.

# *Bibliography

[1] G. Jocher, A. Chaurasia and J. Qiu. *Ultralytics YOLOv8*. 2023. https://github.com/ultralytics/ultralytics (accessed 27 October 2026).

[2] Y. Zhang, P. Sun, Y. Jiang, D. Yu, F. Weng, Z. Yuan, P. Luo, W. Liu and X. Wang. "ByteTrack: Multi-Object Tracking by Associating Every Detection Box". In: *European Conference on Computer Vision (ECCV)*, 2022, pp. 1–21.

[3] Deutsche Fußball Liga (DFL). *DFL – Bundesliga Data Shootout*. Kaggle competition dataset, 2022. https://www.kaggle.com/competitions/dfl-bundesliga-data-shootout

[4] Roboflow. *sports: Computer vision tools and models for sports analytics* (football player detection and pitch keypoint models). https://github.com/roboflow/sports (accessed 27 October 2026).

[5] R. Hartley and A. Zisserman. *Multiple View Geometry in Computer Vision*. 2nd edition. Cambridge University Press, 2004.

[6] M. A. Fischler and R. C. Bolles. "Random Sample Consensus: A Paradigm for Model Fitting with Applications to Image Analysis and Automated Cartography". *Communications of the ACM*, 24(6), 1981, pp. 381–395.

[7] H. W. Kuhn. "The Hungarian Method for the Assignment Problem". *Naval Research Logistics Quarterly*, 2(1–2), 1955, pp. 83–97.

[8] S. P. Lloyd. "Least Squares Quantization in PCM". *IEEE Transactions on Information Theory*, 28(2), 1982, pp. 129–137.

[9] OpenCV. *Color conversions* (CIE Lab colour space). OpenCV documentation. https://docs.opencv.org

[10] Meta Open Source. *React documentation*. https://react.dev

[11] OpenJS Foundation. *Express 5 documentation*. https://expressjs.com

[12] Prisma Data, Inc. *Prisma ORM documentation*. https://www.prisma.io/docs

[13] Taskforce.sh. *BullMQ documentation*. https://docs.bullmq.io

[14] Socket.IO. *Socket.IO documentation*. https://socket.io/docs/v4

[15] The PostgreSQL Global Development Group. *PostgreSQL 17 documentation*. https://www.postgresql.org/docs/17

[16] Redis Ltd. *Redis documentation*. https://redis.io/docs

[17] Docker Inc. *Docker and Docker Compose documentation*. https://docs.docker.com

[18] GitHub, Inc. *GitHub Actions documentation*. https://docs.github.com/actions

[19] OWASP Foundation. *Password Storage Cheat Sheet*. https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

[20] Microsoft. *Azure OpenAI in Azure AI Foundry Models documentation*. https://learn.microsoft.com/azure/ai-foundry/openai

[21] M. Jones, J. Bradley and N. Sakimura. *JSON Web Token (JWT)*. RFC 7519, IETF, 2015.

[22] G. Bradski. "The OpenCV Library". *Dr. Dobb's Journal of Software Tools*, 2000.

[23] F. Pedregosa et al. "Scikit-learn: Machine Learning in Python". *Journal of Machine Learning Research*, 12, 2011, pp. 2825–2830.

[24] Roboflow. *supervision* and *trackers* Python libraries. https://github.com/roboflow/supervision, https://github.com/roboflow/trackers

[25] W3C Web Incubator Community Group. *HTMLVideoElement.requestVideoFrameCallback()*. https://wicg.github.io/video-rvfc

[26] Tailwind Labs. *Tailwind CSS documentation*. https://tailwindcss.com/docs

[27] VoidZero Inc. *Vite documentation*. https://vite.dev

[28] PyAV contributors. *PyAV: Pythonic bindings for FFmpeg* (with the x264 H.264 encoder). https://pyav.basswood-io.com

[29] A. Paszke et al. "PyTorch: An Imperative Style, High-Performance Deep Learning Library". In: *Advances in Neural Information Processing Systems 32*, 2019.

[30] T.-Y. Lin et al. "Microsoft COCO: Common Objects in Context". In: *European Conference on Computer Vision (ECCV)*, 2014, pp. 740–755.

[31] C. B. Barber, D. P. Dobkin and H. Huhdanpaa. "The Quickhull Algorithm for Convex Hulls". *ACM Transactions on Mathematical Software*, 22(4), 1996, pp. 469–483.

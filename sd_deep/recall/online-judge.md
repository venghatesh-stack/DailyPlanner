# online coding judge (LeetCode): recall card

> **Hook:** Persist PENDING → Per-language priority queue → Lease to worker → Fresh sandbox per test → Stop at first failure → Push verdict

**P · Problem:** It's really a hostile-code batch compute problem with fairness rules, wrapped in an ordinary web app.

**N · Numbers:**
1. About 5 core-seconds per Submit (compile plus 100 tests), so every request is expensive CPU, not I/O.
2. A contest peaks at 50 submissions/s x 5 s = 250 busy cores, about 600 reserved, so pre-scale before the start, do not wait for autoscaling.
3. 150 GB of test bundles, so cache them on each worker's local SSD.

**H · Hard part:** Running untrusted code with zero escapes, and giving fair, reproducible timing during a 30k-person contest spike.

**B · Boxes:** `Browser → API gateway → Submission service → Job broker → Judge worker sandbox → Result service`

Side path: `Results topic → Contest service → Redis ZSET leaderboard`.

**D · Decisions:**
1. Pre-scaling over reactive autoscaling, because boot times would build queues at the start gun.
2. Stop at first failure over running all tests, because most submissions fail, so it saves CPU and gives faster feedback.
3. nsjail-style isolation for compiled languages over gVisor everywhere, because it starts fast with exact accounting; gVisor covers high-risk runtimes.

**F · Failures:**
1. Worker crashes mid-job → the lease expires, the job re-queues with attempt+1, and the late verdict write is ignored.
2. Contest queue backlog → show queue position, pause practice and Run for free users; ranking still uses submitted_at.

**C · Close:** "An online judge is a normal web app around a very abnormal compute plane. The API stores a pending submission and queues a job by language and priority. Stateless workers, one job per pinned core, compile with a cache, then run each test in a fresh sandbox of namespaces, seccomp and cgroups, with no network. They stop at the first failure and write a versioned verdict that we push to the browser. Contest start is known, so we pre-scale about 600 cores."

**Quiz yourself:**
1. How is TLE measured fairly? → CPU time from cgroups on pinned cores, plus a wall limit.
2. How does one ZSET rank ICPC? → score = solved x 10^9 - penalty.
3. What stops a fork bomb? → cgroups pids.max 64.

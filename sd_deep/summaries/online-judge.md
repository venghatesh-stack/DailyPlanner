# Design an online coding judge (LeetCode): the 5-page summary

An online judge runs untrusted code from strangers against hidden tests and returns a fair, reproducible verdict in seconds. The single most important idea: the web tier is ordinary; the design lives in the execution plane, which must be hostile-code safe, pre-provisioned for a predictable contest spike, and fair to the millisecond.

## Page 1. The problem, scope and numbers

**Pitch:** accept code, run it safely against hidden test cases, and return AC, WA, TLE, MLE, RE, CE or OLE quickly and identically on any worker, including during a 30k-person contest.

**Who uses it:** students practising for placements (instant feedback on slow mobile links), competitive programmers (weekly contests, precise TLE/MLE), problem setters (upload tests, rejudge after a fix).

**In scope:**
- **Run:** execute against user input with the same limits; return stdout and stderr.
- **Submit:** compile once, run hidden tests cheapest first, stop at the first failure.
- **Checkers:** float tolerance, any valid permutation, interactive problems via a referee.
- **Contests:** timed start and end, ICPC penalty or points scoring, leaderboard with freeze.
- **Rejudge** by problem or submission; plagiarism detection after a contest.
- **Rate limits:** 1 submit per 5 s and 1 Run per 2 s per user.

**Out of scope:** forums, editorial authoring, payments, GPU or network problems, IDE debugging, proctoring.

**Non-functional targets:**
- **Latency:** Run p95 under 3 s; Submit p95 under 5 s normally, under 15 s at contest peak.
- **Security:** no network, allowlisted syscalls, no host filesystem, fresh sandbox per run; zero escapes.
- **Fairness:** CPU time (not wall time) on dedicated cores, under 5% variance across workers, pinned toolchains.
- **Availability:** 99.9% overall, 99.95% during contests; queued submissions never lost.
- **Durability:** submissions and verdicts persisted before ack; test data versioned and replicated.

**Capacity math (5M MAU, 500k submissions/day, 1.5M Runs/day):**
- **Practice:** 500k / 86,400 = about 6/s, 20/s at peak; Runs about 17/s. Request volume is tiny, so the web tier is not the problem.
- **Cost per Submit:** compile about 1 s (30% cache hits on resubmits) + 100 tests x 40 ms = about 5 core-seconds. So every request is expensive CPU, not I/O.
- **Practice cores:** 20/s x 5 s = 100 busy cores, about 150 with 50% headroom.
- **Contest:** 30k users x 4 problems x 3 tries = 120k submissions in 90 minutes, peak 3,000/min = 50/s. By Little's law, 50/s x 5 s = 250 busy cores; at 60% target utilisation about 420; plus practice, about 600 cores reserved. So pre-scale before the start; do not wait for autoscaling.
- **Storage:** 500k x 2 KB = 1 GB/day of code; tests 3,000 problems x 50 MB = 150 GB. So cache test bundles on each worker's local SSD.
- **Leaderboard:** 30k users polling every 10 s = 3k reads/s. Trivial for a Redis sorted set.

## Page 2. The architecture

```
 Browser --HTTPS/WSS--> API gateway (auth, rate limit, code <= 64 KB)
     |          |                |                    |
     v          v                v                    v
 Problem svc  Submission svc   Contest svc         Result svc (WS/SSE)
 (CDN cache)    | insert PENDING   | Redis ZSET          ^
     |          | enqueue          | leaderboard         |
     |          v                  ^                     |
     |    Job broker: q.contest.<lang>  q.practice.*  q.run.*
     |          | pull with lease (visibility timeout), DLQ
     |          v
     |    Judge workers (isolated VPC, no credentials)
     |      compile cache -> fresh sandbox per test -> checker
     |      namespaces + seccomp + cgroups v2, or gVisor/microVM
     v          | fetch tests             | verdict
 Object storage <+  (local SSD cache)     v
 (tests, versioned)          Results topic -> Submission DB, Contest svc
```

- **API gateway:** auth, per-user rate limits, request size limits, routing.
- **Problem service:** statements, limits, test set versions; statements cached at the CDN.
- **Submission service:** validates, persists PENDING, enqueues by priority, handles rejudge.
- **Job broker:** queues per language and priority, leases, dead-letter queue after 3 attempts.
- **Judge worker:** stateless; leases a job, compiles, runs tests, checks output, emits verdict.
- **Sandbox runtime:** namespaces, seccomp allowlist, cgroups, read-only rootfs, tmpfs scratch.
- **Test store and cache:** immutable, checksummed bundles; workers cache by (problem, version).
- **Contest service:** start and end gates, scoring, Redis leaderboard, freeze.
- **Result service:** pushes verdicts over WebSocket or SSE, with polling fallback.

**Flow A: submit during a contest**
1. POST /submissions; gateway checks rate limit and contest window.
2. Insert row PENDING with server submitted_at; enqueue to q.contest.<lang>; return 202 and an id.
3. Worker leases the job, checks the test bundle SHA-256 in its cache, compiles (10 s, 512 MB limits).
4. Tests run small to large, each in a fresh sandbox; stop at the first failure.
5. Verdict goes to the results topic; DB updated conditionally; leaderboard and browser updated.

**Flow B: rejudge after a test fix**
1. Setter uploads bundle v2; the reference solution must pass all tests.
2. Affected submissions are enqueued at low priority with judge_version v2.
3. New verdict rows keyed by (submission_id, judge_version); scores recomputed; users notified.

## Page 3. The core deep dives

### 1. The sandbox: defence in depth
Treat every submission as hostile. Namespaces (pid, net, mount, user, ipc) hide the host; the network namespace has no interfaces at all. A seccomp allowlist blocks syscalls such as socket. Cgroups v2 cap CPU, memory and pids (pids.max 64 stops a fork bomb). The root filesystem is read-only and holds no secrets; scratch space is tmpfs. Runtimes with a large syscall surface run in gVisor or a Firecracker microVM, a second kernel boundary. Workers sit in an isolated VPC with no credentials, so even an escape exposes only test bundles on that node.

### 2. Fair, deterministic timing
One job per pinned core, hyperthread siblings disabled or reserved, fixed CPU frequency, homogeneous hardware. TLE uses CPU time from cgroup accounting, plus a wall limit (2x CPU limit + 1 s) so a program that sleeps still times out. Java gets about 2x and Python 3-5x the C++ limit, set per problem from reference solutions. A calibration program on each worker flags drifting machines.

### 3. Queues, leases and safe retries
A worker leases a job with a visibility timeout of about 2x the worst-case judge time. If Sethu's job lands on a worker that dies, the lease expires and the job returns with attempt+1. The verdict write is conditional on attempt, so a late result from the dead worker is ignored. After 3 attempts the job goes to the DLQ as System Error, with no penalty for the user.

### 4. Leaderboard in one sorted set
ICPC ranks by problems solved, then penalty (minutes to each AC + 20 per earlier wrong try). Encode both as score = solved x 10^9 - penalty in a Redis ZSET. Example: Shreya solves 3 with 95 penalty minutes, so 3,000,000,000 - 95. Only the first AC counts, and score uses submitted_at, so a submission at 89:59 judged at 91:00 still counts. Postgres is the source of truth; Redis is rebuilt from it.

**Data model:**
- **Submission** (Postgres sharded by user_id): PK snowflake submission_id; status, verdict, failed_test, judge_version, attempt; code over 16 KB in object storage.
- **Problem / TestBundle:** PK (problem_id, version); limits, language multipliers, checker, bundle SHA-256. Immutable.
- **ContestScore:** Redis key contest:{id}:lb over Postgres per-problem attempts and accepted_at.
- **JudgeJob** (broker): queue per (priority, language); carries test_version and deadline.

**Key APIs:**
- `POST /v1/submissions`: rate limited; idempotency key returns the first id on a double click.
- `GET /v1/submissions/{id}`: polling fallback with ETag.
- `POST /v1/runs`: waits up to 5 s synchronously, then async; output kept 24 h.
- `GET /v1/contests/{id}/leaderboard?page=1`: from the ZSET, cached 5 s at the edge.
- `POST /v1/admin/problems/{id}/rejudge`: low-priority queue, versioned verdicts.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Contest compute:** a predictable step function, so scheduled pre-scaling of about 600 cores (6,000 at 10x), with autoscaling only as a safety net.
- **Wasted CPU:** stop at first failure with tests sorted by size; compile cache keyed by hash of (language, toolchain version, code).
- **Test data fetch:** pre-warm contest problems on every worker's local SSD before the start.
- **Cost:** contests on on-demand nodes; practice and rejudge on spot, saving about 60-70%.
- **Parallel tests:** spread one submission across idle cores only when utilisation is low.

**Failure modes:**
- **Worker crash or node loss:** leases expire, jobs re-queue; one timeout of delay, nothing lost.
- **Contest queue backlog:** show queue position; pause practice and Run for free users; ranking still uses submitted_at.
- **Object storage outage:** workers use cached bundles; misses fail over to a replica bucket.
- **Redis leaderboard lost:** rebuilt from Postgres; briefly stale, scores unaffected.
- **Bad test data mid-contest:** hold that problem's jobs, fix and validate, rejudge, announce.
- **Suspected kernel exploit:** quarantine the pool, rotate to patched images, review audit logs.

**Trade-offs chosen:**
- **nsjail-style isolation for compiled languages, gVisor for complex runtimes:** fast start and exact accounting, plus a second kernel boundary where risk is high.
- **Stop at first failure over running all tests:** most submissions fail, so this saves CPU and gives faster feedback.
- **Fresh process per test in a warm template over one sandbox per submission:** no state carries between tests, at tens of ms.
- **WebSocket with polling fallback over pure polling:** instant verdicts without poll storms.
- **Pre-scaling over reactive autoscaling:** boot times would build queues at the start gun.

**What to measure:** queue age per (priority, language), alert if contest queue age exceeds 30 s; verdict latency p50/p95/p99; sandbox start time and compile and test cache hit rates; verdict mix per problem (an RE or TLE spike means bad tests or bad nodes); calibration drift per node; seccomp kills; DLQ and System Error rate near 0.

## Page 5. Say it in the interview

> "An online judge is a normal web app wrapped around a very abnormal compute plane, so I will spend most of my time on execution. Assume half a million submissions a day and weekly contests where thirty thousand people submit in bursts. Code is hostile, and verdicts must be fair and reproducible. The API stores a pending submission and pushes a job onto a per-language priority queue. Stateless judge workers, one job per pinned core, compile with a cache, then run each test in a fresh sandbox built from namespaces, seccomp and cgroups, or a microVM, with no network. They stop at the first failure and write a versioned verdict, which we push to the browser. A contest needs about 600 cores, and since the start time is known, we pre-scale rather than autoscale."

**Key points to land:**
- The web tier is ordinary; the execution plane is the design.
- Treat code as hostile: namespaces, seccomp, cgroups, read-only fs, no network, plus gVisor or microVM.
- Async submit: persist PENDING, enqueue, push the verdict over WebSocket.
- Queues per language and priority, with leases, visibility timeouts and a DLQ.
- Little's law: 50 submissions/s x 5 core-s = 250 cores, about 600 with headroom.
- Fairness: CPU time on pinned cores, homogeneous hardware, calibration.
- Stop at the first failing test, smallest first, with a compile cache.
- Conditional, versioned verdict writes make retries and rejudges safe.
- The leaderboard is a Redis ZSET over durable state; ranking uses submit time.

**Likely follow-ups:**
1. **The queue is 5 minutes long at contest start. Now what?** Shift weight to contest queues, pause practice and Run for free users, add on-demand capacity, show queue position; fix the forecast afterwards.
2. **How do you stop users extracting hidden tests?** Never return hidden inputs or outputs, truncate stderr, return only the failing test index, rate limit per problem and detect probing.
3. **How do you add a new language?** A pinned toolchain image, compile and run commands, a seccomp profile and a time multiplier, validated with reference solutions first.
4. **Interactive problems?** A trusted referee and the solution in separate sandboxes joined by pipes; the referee decides the verdict.
5. **How do you catch cheating?** After the contest, winnowing fingerprints and Jaccard similarity per problem, plus account age and IP signals, then manual review.

**Director layer:**
- **Cost drivers:** about 600 reserved cores per contest window; spot capacity for practice and rejudge; compile and early-exit savings. Track cost per 1,000 submissions, target 15% lower each year.
- **Phasing:** start with async submit, one sandbox type and polling; add contests, WebSocket push, gVisor and plagiarism detection next.
- **Team ownership:** web and contest platform, judge execution and sandbox security, problem tooling, SRE capacity planning.
- **Top risks:** sandbox escape, contest overload making rankings unfair, test data leaks, and plagiarism.

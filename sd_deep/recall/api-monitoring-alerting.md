# Monitoring and alerting for a critical API: recall card

> **Hook:** Define SLOs → Scrape RED metrics → Compute burn rates → Page on fast burn → Probe from outside → Watch the watcher

**P · Problem:** It's really a signal-versus-noise problem: deciding what deserves to wake a human.

**N · Numbers:**
1. 99.95% over 28 days is about 20 minutes of downtime, so paging must catch fast burns quickly.
2. About 0.6M series against a 2M budget, so cardinality, not volume, is the limit.
3. 7 GB/day of samples per replica, so metrics are cheap and never sampled.

**H · Hard part:** Paging only on real user pain, and keeping the alert path alive during the outage it reports.

**B · Boxes:** `Checkout API pods → Prometheus HA pair → Alertmanager cluster → Pager → On-call`

Side path: `Synthetic prober and Watchdog heartbeat → external dead-man's switch → SMS`.

**D · Decisions:**
1. Symptom pages over cause pages, because pages should match user pain; CPU goes to dashboards and tickets.
2. Duplicates over misses on the alert path, because a missed page is far worse than a double page.
3. Tail over head sampling, because incidents are rare bad requests that head sampling throws away.

**F · Failures:**
1. Monitoring cluster or region down → the dead-man's switch pages by SMS within 3 minutes.
2. Alertmanager partitioned → each side notifies; on-call may get a duplicate page, never a missed one.

**C · Close:** "My principle is alert on symptoms, investigate with causes. I define availability and latency SLOs, scrape RED metrics every 15 seconds with bounded labels, and page only on multiwindow burn rates, like 14.4x over an hour and five minutes. Probes from four locations catch zero traffic and edge failures. Alertmanager dedups and routes with a runbook, and a dead-man's switch makes sure the monitoring survives the outage."

**Quiz yourself:**
1. Why a short window with the long one? → So the alert resets quickly once the problem is fixed.
2. Why not average p99 across pods? → It is mathematically wrong; count requests under the 400 ms bucket over the total.
3. What catches a total outage with zero traffic? → Black-box probes, backed by a traffic-drop alert.

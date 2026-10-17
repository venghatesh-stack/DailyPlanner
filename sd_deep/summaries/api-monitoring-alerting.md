# Design monitoring and alerting for a critical API: the 5-page summary

This is monitoring for a revenue-critical checkout API at 20k requests/s peak. The single most important idea: collecting metrics is easy; deciding what deserves to wake a human is hard, so page only on SLO burn and black-box failure, and make the alert path survive the outage it reports.

## Page 1. The problem, scope and numbers

**Pitch:** detect real user pain on checkout within minutes, route it to the right person with a runbook, and stop paging people for noise.

**Why now:** at 20k RPS one minute of total failure is about a million requests. Today customers report incidents first, alerts are CPU thresholds, and on-call ignores half the pages.

**Who uses it:** on-call engineers (few, accurate pages), leadership (error budget reports), business teams (order drops in sales), partner teams (SLA views).

**In scope:**
- **Metrics:** RED (rate, errors, duration) per route, status class, region and AZ, with latency histograms; dependency and saturation metrics.
- **SLO alerting:** recording rules compute SLIs and burn rates over 5m, 30m, 1h, 6h and 3d; multiwindow burn-rate alerts.
- **Black-box probes:** from 4 locations every 30 s against the public endpoint.
- **Routing:** group, dedup, inhibit, silence; escalate unacked pages after 5 minutes.
- **Diagnosis and meta-monitoring:** dashboards with deploy markers, drill-down by trace_id; a heartbeat to an external dead-man's switch.

**Out of scope:** a platform for every team, incident and postmortem tooling, SIEM, FinOps, a custom TSDB, auto-remediation beyond rollback hooks.

**Non-functional targets:**
- **Detection:** hard outage paged within 3 minutes; MTTD under 5 minutes for SEV1/SEV2.
- **Alert path:** 99.99% available, independent of the monitored cluster; rule fire to phone p99 under 60 s.
- **Freshness:** scrape every 15 s, rules every 30 s, dashboards lag under 30 s.
- **Quality:** over 80% of pages actionable; under 2 pages per shift on average.
- **Retention and overhead:** raw metrics 15 d, downsampled 13 months; under 2% CPU and 1 ms p99 added to the API.

**Capacity math (200 pods, 2 regions, 5k RPS average):**
- **Series:** 200 x 1,500 = 300k, about 0.6M with dependencies. Under the 2M budget, so cardinality, not volume, is the limit.
- **Samples:** 600k / 15 s = 40k/s = 3.5B/day x 2 B = 7 GB/day per replica, 105 GB for 15 days. So metrics are cheap and never sampled.
- **Logs:** 5k x 600 B = 3 MB/s = 260 GB/day, 600 GB on peak days. So keep all errors and 10% of 2xx.
- **Traces:** 5k x 5% x 20 spans x 300 B = 130 GB/day. So tail-sample: keep every error and slow trace.
- **Error budget:** 99.95% over 28 days = 0.05% x 28 x 24 x 60 = about 20 minutes of downtime. So paging must be aggressive enough to catch fast burns.

## Page 2. The architecture

```
 Clients -> Edge/LB --access logs--> Kafka -> Log index (7d) + S3 (30d)
               |
               v
 Checkout API pods x200 --OTel spans--> Trace store (tail sampled)
      ^ scrape /metrics every 15 s
      |
 Prometheus HA pair --remote_write--> Long-term TSDB (Mimir, RF=3)
      | recording rules (SLI, burn rates), alert rules every 30 s
      v
 Alertmanager cluster (3 nodes, gossip): dedup, group, inhibit
      |              |            |
      v              v            v
 Pager (on-call)   Chat        Ticket    -> runbook + dashboard links

 Synthetic prober (4 locations, 30 s) -> public endpoint -> probe metrics
 Watchdog heartbeat every 1 min -> external dead-man's switch -> SMS
```

- **Instrumentation:** OpenTelemetry plus Prometheus client; bounded labels; trace_id injected into logs.
- **Prometheus HA pair:** two identical scrapers per cluster; evaluate rules; no single point.
- **Long-term TSDB:** replicated, downsampled, global view across regions for dashboards.
- **Alertmanager cluster:** dedups both replicas, groups to one page, mutes downstream symptoms.
- **Pager service:** push, SMS, voice; rotations; escalates after 5 minutes.
- **Synthetic prober:** health, product, cart and sandbox checkout, like a customer.
- **Log and trace pipeline:** redact PII, sample successes, keep failures.
- **Dead-man's switch:** external SaaS pages via a separate channel if heartbeats stop.

**Flow A: fast-burn page on a bad deploy**
1. A 14:00 deploy makes 3% of checkouts return 500: burn rate 60x against a 0.05% budget.
2. Rules check burn over 1h and 5m above 14.4x, for 2 minutes.
3. Both replicas fire; Alertmanager dedups, groups for 30 s, pages Shreya.
4. The page shows impact, dashboard, runbook and the 14:00 deploy marker; she rolls back.

**Flow B: the monitoring itself fails**
1. The monitoring cluster loses network; the Watchdog heartbeat stops.
2. After 3 missed minutes, the external service pages on-call by SMS through another vendor.

## Page 3. The core deep dives

### 1. SLOs, error budgets and burn rate
Checkout has two SLOs over 28 days: 99.95% availability and 99% of requests under 400 ms. The SLI is a ratio of good to valid requests, so it adds up across pods and regions. Burn rate = error ratio / (1 - SLO); burn 1 spends the budget exactly by day 28. A page needs a long window (significant) and a short window, 1/12 of the long one, so it resets quickly once fixed. Three rule pairs: 14.4x over 1h and 5m pages (about 2% of the budget), 6x over 6h and 30m pages (5%), 1x over 3d and 6h opens a ticket (10%). Example: at 3% errors the 1h ratio crosses 0.72% after about 15 minutes; at a full outage it crosses in about 1 minute. A slow 0.06% leak (1.2x) never pages but opens a ticket. A low-traffic guard stops 2 errors in 20 requests at 3 am from paging.

### 2. Latency SLI from histograms
Averaging p99 across pods is mathematically wrong. Instead count requests in the bucket at le=0.4 (400 ms) over the total. That ratio adds up across pods and regions, so bucket boundaries must include the SLO threshold exactly.

### 3. Cardinality control
Every unique label combination is a series. Labels are limited to route template, method, status_class, region, AZ and pod; ids like order_id go to logs and traces, and exemplars link a histogram bucket to a trace. sample_limit of 5,000 per target fails the scrape, not the TSDB, and a CI linter blocks forbidden labels.

### 4. Blind spots: zero traffic and edge failures
In a total outage nothing reaches the service, so the error ratio is 0/0 and looks healthy. An expired TLS certificate on the load balancer shows only falling traffic. Black-box probes catch both: page when success is under 50% in at least 2 locations for 2 minutes, so one flaky vantage point cannot page. A traffic-drop alert (below 40% of the same time last week) backs it up and is inhibited when the probe alert fires.

**Data model:**
- **Time series** (TSDB): name plus sorted labels; series id = hash of labels; 2 h blocks; about 1.3-2 bytes/sample.
- **SLO definition** (Git YAML): service, SLI type, good and valid queries, objective, windows, owner, runbook; a generator emits all rules.
- **Alert instance** (Alertmanager): keyed by label fingerprint; a gossiped notification log stops duplicate sends.
- **Log event** (Kafka, index): ts, route, status, latency, trace_id, error_code; partitioned by service.
- **Trace span:** keyed by trace_id; sampling decided after the full trace arrives.

**Key APIs:**
- `GET /metrics`: scraped every 15 s on a separate port; sample_limit 5,000.
- `POST /api/v2/alerts`: both replicas send; deduped on fingerprint.
- `POST /v1/incidents`: pager dedup_key = group key, so repeats update one incident.
- `POST /api/v2/silences`: max 24 h, needs a ticket id.
- `POST /heartbeat/{token}`: the dead-man's switch pages after 3 silent minutes.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Cardinality:** the real limit; bounded labels, per-scrape limits, alert on series growth over 20% a day.
- **Writes:** shard scrape targets by hash across Prometheus pairs; the long-term TSDB ingests via distributors with RF=3 and per-tenant limits.
- **Reads:** dashboards and alerts read pre-aggregated recording rules; long ranges hit downsampled data with query caching and splitting.
- **Sales:** burn rates are ratios so they scale with traffic; pre-scale the stack and raise series limits in advance.

**Failure modes:**
- **Prometheus replica crashes:** the other keeps alerting; restart replays the WAL.
- **Alertmanager partitioned:** each side notifies; on-call may get a duplicate page, never a missed one.
- **Monitoring cluster or region down:** the dead-man's switch pages by SMS within 3 minutes; the other region's prober continues.
- **Long-term TSDB overloaded in a sale:** local Prometheus still evaluates alerts; dashboards may lag.
- **Pager vendor outage:** second SMS provider and chat fallback, drilled quarterly.
- **Bad alert rule:** rules are unit-tested with promtool in CI; probes give an independent page path.
- **Alert storm (300 alerts):** region-down inhibits service alerts; one grouped incident.

**Trade-offs chosen:**
- **Symptom pages over cause pages:** pages match user pain; CPU and pool usage go to dashboards and tickets.
- **Self-hosted core, bought paging:** SaaS at 500 GB/day of logs is expensive, but paging must not share fate with our infra.
- **15 s scrape:** 5 s triples cost for little gain; 60 s delays detection.
- **Tail over head sampling:** incidents are rare bad requests that head sampling throws away.
- **Duplicates over misses (AP alert path):** a missed page is far worse than a double page.
- **SLI at the load balancer:** it counts requests that never reached a healthy pod; app metrics for diagnosis, client data as a secondary view.

**What to measure:** SLI ratios per window, budget remaining, RPS against last week, p99 per route, dependency errors and pool use, orders per minute and payment success, probe success per location, monitoring health (scrape success, rule lag, remote_write lag, series count), and alert quality (pages per shift, actionable ratio, MTTD, time to ack).

## Page 5. Say it in the interview

> "Let me assume a checkout API at about 5k requests a second, peaking near 20k in sales, with an SLO of 99.95% success and p99 under 400 ms over 28 days. My principle: alert on symptoms users feel, investigate with causes. I define two SLIs, availability and latency, instrument RED metrics per route with bounded labels, and add synthetic probes from four locations to catch what the server cannot see. Prometheus pairs scrape every 15 seconds, recording rules compute burn rates, and multiwindow burn-rate alerts page only when we spend budget fast enough to matter, about 2% in an hour. Alertmanager dedups and routes with a runbook link. Cardinality is the real bottleneck, and a dead-man's switch makes sure the monitoring survives the outage it reports."

**Key points to land:**
- Alerts derive from SLOs and the error budget; 99.95% over 28 days is about 20 minutes.
- Page on symptoms; causes go to dashboards and tickets.
- Burn-rate pairs: 14.4x over 1h with 5m, 6x over 6h with 30m, 1x over 3d as a ticket.
- Black-box probes catch zero traffic, DNS, TLS and edge failures.
- Cardinality is the scaling limit; ids go to logs and traces.
- Histograms and good/total ratios, never averaged percentiles.
- The alert path does not share fate: HA pairs, clustered Alertmanager, external dead-man's switch.
- Every page carries impact, dashboard and runbook; unacked pages escalate in 5 minutes.
- Measure the monitoring: MTTD, actionable ratio, pages per shift.

**Likely follow-ups:**
1. **No SLO exists yet. How do you set one?** Use 3-6 months of real performance, set it slightly below what users get, validate with product, start internal, revisit quarterly.
2. **The team gets 15 pages a week. Fix it.** Label last month's pages actionable or not, demote cause alerts to tickets, convert thresholds to burn rate, add inhibition; track actionable ratio.
3. **Metrics system slow during the incident?** Alerts evaluate on local Prometheus, dashboards use recording rules, and probes plus the dead-man's switch are independent paths.
4. **Tie deploys to alerts?** Deploy annotations and a deploy_info metric; canary analysis compares SLIs and auto-rolls back before the global SLO burns.
5. **Use ML anomaly detection?** For seasonal business signals like orders per minute, as tickets; not for primary paging, because burn rate is explainable and opaque models erode trust.

**Director layer:**
- **Cost drivers:** logs and traces dominate, not metrics; keep observability around 5-8% of the service's infra spend by sampling successes.
- **Phasing:** first SLOs, burn-rate pages, probes and the dead-man's switch; then tail sampling, per-partner SLOs, reuse for other APIs.
- **Team ownership:** the service team owns SLOs, alerts and runbooks; a platform or SRE team owns the stack and alert path.
- **Top risks:** alert fatigue, a cardinality explosion during a sale, monitoring sharing fate with production, a wrong SLI hiding pain, rotting runbooks.

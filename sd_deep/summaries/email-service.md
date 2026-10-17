# Design an email service (Gmail): the 5-page summary

Email is two systems glued together: an SMTP edge that must talk to millions of hostile or sloppy mail servers, and a per-user mailbox store that must keep mail for decades, search it in milliseconds and sync it to every device. The single most important idea: the SMTP "250 OK" is the durability boundary, so acknowledge only after a zone-replicated write, then make everything downstream at-least-once and idempotent, partitioned by user.

## Page 1. The problem, scope and numbers

**Pitch:** a free, reliable, secure way to exchange mail with anyone on the internet, keep it for years and find any message in seconds, while blocking the spam, phishing and malware that make up most inbound traffic.

**Who uses it:** consumers (clean inbox, fast push, 15 GB free), Workspace users (threads, labels, large attachments), IMAP clients (Outlook, Thunderbird), domain admins (retention, legal hold, audit), trust and safety, and other mail providers.

**In scope:**
- **Send:** compose, reply, forward, CC/BCC, attachments up to 25 MB, scheduled send, undo send.
- **Receive:** accept SMTP for our domains, authenticate, classify into inbox, spam or category.
- **Organise:** labels (many-to-many, not folders), archive, star, snooze, filters at delivery.
- **Threading** by In-Reply-To/References headers, subject as fallback.
- **Search** over headers, body and attachments with operators (from:, has:attachment, before:).
- **Sync:** delta sync by history id for web, mobile and IMAP, plus push; bounces and quotas.

**Out of scope:** calendar, contacts and chat; ads; default end-to-end encryption (it breaks server-side search and spam filtering); our own DNS or CA.

**Non-functional targets:**
- **Durability:** no loss after 250 OK; bodies 11 nines; metadata 3 replicas across zones.
- **Availability:** 99.99% for read and send; MX keeps accepting mail even if mailboxes are degraded.
- **Latency:** inbox list p99 200 ms, open 300 ms, search 500 ms, intra-domain delivery 1 s.
- **Consistency:** read-your-writes per user across devices; search and counters lag by seconds.
- **Abuse:** spam in inbox under 0.1%, legit mail in spam under 0.05%.

**Capacity math (1.8B accounts, 500M DAU):**
- **Deliveries:** 500M x 40 = 20B/day = 230k/s, 700k/s peak. So deliver asynchronously from a queue.
- **SMTP connections:** 100B/day = 1.15M/s, about 70% spam. So reject cheaply at the edge, before DATA.
- **Ingest:** 20B x 75 KB = 1.5 PB/day, plus 1 PB/day of attachments. So dedupe and tier from day one.
- **Stored:** 1.8B x 2 GB = 3.6 EB logical, 2.2 EB after 40% dedupe and compression, 3.3 EB physical with 1.5x erasure coding. Storage cost, not QPS, dominates.
- **Metadata:** 20B rows x 1 KB = 20 TB/day, 60 TB with 3 replicas. So a wide-column store.
- **Reads:** 500M x 15 opens = 87k list calls/s, 250k/s peak; searches 6k/s. Push: 230k/s.

## Page 2. The architecture

```
 Internet MTAs (SMTP :25)              Web / Mobile / IMAP clients
      |                                         | HTTPS / IMAP
      v                                         v
 MX gateways: IP reputation, rate      Mail API / IMAP adapters ----> Search
 limit, SPF/DKIM/DMARC, TLS               |  send          | read     svc
      |                                   v                v          ^
      +--> Delivery queue (Kafka RF=3, acks=all) <---+   Mailbox      |
                 |                                    |   store       |
                 v                                    |   (by user)   |
 Delivery workers: spam ML, AV, filters, threading    |      |        |
      |  body (if new)          | metadata + history  |      v        |
      v                         +-------------------> Change stream --+
 Blob store (SHA-256 CAS, hot replicated,          |
  cold EC)                                         +-> Notifier (FCM/APNs)
 Outbound: API -> undo delay -> outbound queue -> spam score -> DKIM sign
           -> per-domain relays (retry 4xx with backoff, bounce on 5xx)
```

- **MX gateways:** SMTP plus TLS; reputation and recipient checks; reply 250 only after the queue write.
- **Delivery queue:** zone-replicated log; separates accepting mail from writing mailboxes.
- **Delivery workers:** spam, phishing and AV; filters, threading, blob and metadata writes; idempotent.
- **Blob store:** immutable, content-addressed bodies and attachments; deduped by SHA-256.
- **Mailbox store:** per-user messages, labels, threads and history; wide-column, by user_id.
- **Search service:** per-user inverted indexes, fed from the change stream within 5 s.
- **Mail API / IMAP adapters:** list, read, modify, send; delta sync by history id.
- **Notifier:** coalesced "mailbox changed" pushes to devices.
- **Outbound pipeline:** send limits, DKIM signing, per-domain queues, retries, bounces, IP pools.

**Flow A: receive external mail**
1. Gateway rejects known-bad IPs (554) and unknown users (550) before DATA.
2. After DATA, check SPF, DKIM, DMARC; write to the queue with acks=all; reply 250 OK.
3. Worker classifies, stores the blob if new, writes metadata and history id +1 in one per-user transaction.
4. Change stream triggers indexing and a push.

**Flow B: send to an external address**
1. API stores it in Sent at once; after the undo delay it enters the outbound queue.
2. Spam-score, DKIM-sign, group by domain, look up MX, connect over TLS; retry 4xx up to 5 days, bounce 5xx.

## Page 3. The core deep dives

### 1. Store-and-forward and the 250 OK
Each hop takes full responsibility once it says 250 OK, and the previous hop deletes its copy. So the gateway acks only after the queue confirms writes on 2 of 3 zone replicas. If the queue cannot reach that, the gateway answers 451 (try later) and the remote server retries for up to 5 days. Nothing is lost and nothing is ours until we said yes.

### 2. Idempotent delivery with a per-user history id
The queue is at-least-once: a worker can crash after writing but before committing its offset. The insert is conditional on (user_id, rfc822 message id + envelope hash) not existing, and the history id is assigned in the same row transaction, so a retry is a no-op. Example: Shreya's phone holds history id 1041; a push says "changed"; it calls GET history since 1041 and gets only the new message and label changes. If 1041 is older than the 30-day window, the API returns 410 and the client resyncs.

### 3. Content-addressed storage and dedupe
A blob is named by the SHA-256 of its bytes, so a newsletter sent to a million users is stored once with a million references. Hash the body separately from per-recipient headers, or dedupe fails. Garbage collection uses refcounts plus a grace period and reachability scan. Enterprise tenants dedupe only within their own key domain, so nobody can learn what others stored. Recent mail is replicated; mail older than 30 days moves to Reed-Solomon 6+3 erasure coding, cutting overhead from 3x to about 1.5x.

### 4. Spam: authenticate, then judge reputation
SPF checks the sending IP against the domain's DNS list; DKIM verifies a signature with a public key from DNS; DMARC ties both to the visible From domain and publishes a policy (none, quarantine, reject). Authentication proves who sent it, not that it is wanted, so reputation per IP, domain and signer drives throttling, greylisting and thresholds. Reject the obvious at SMTP; send borderline mail to the spam folder.

**Data model:**
- **MessageMeta** (Bigtable/Cassandra): partition user_id; clustering message_id (time-sortable).
- **LabelIndex:** partition (user_id, label_id); clustering reverse_ts: inbox is one range scan.
- **History:** partition user_id; clustering history_id; kept 30 days.
- **Blob:** key SHA-256 of content; immutable, refcounted.
- **UserQuota** (Spanner-like): user_id; updated in the same transaction as inserts and deletes.
- **OutboundJob:** partitioned by recipient domain hash; expires after 5 days with a bounce.

**Key APIs:**
- `GET /v1/users/me/messages?label=INBOX`: range scan on (user, label, -ts).
- `POST /v1/users/me/messages/send`: idempotency key kept 24 h; undo cancels while scheduled.
- `POST /v1/users/me/messages/{id}/modify`: labels and flags; bumps the history id.
- `GET /v1/users/me/history?startHistoryId=H`: delta sync; 410 if H expired.
- `SMTP MAIL FROM / RCPT TO / DATA`: 250 only after a durable enqueue.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Spam floods:** reputation checks before DATA, tarpitting and greylisting keep the expensive pipeline for plausible mail.
- **Storage growth:** dedupe, compression and cold erasure coding are the main cost levers.
- **Hot mailboxes (support addresses, celebrities):** bucket the partition by time, give it its own search shard, cache first pages, rate limit senders per mailbox.
- **Search:** pack many users per shard routed by user id; most users search rarely, so their index can sit on cheaper storage.
- **Outbound:** per-domain concurrency limits protect remote servers and our IP reputation.

**Failure modes:**
- **Mailbox shard down:** workers back off, queue lag grows, SMTP keeps accepting; affected users see a stale-inbox banner; no loss.
- **Queue zone lost:** 2 in-sync replicas remain; below 2, MX returns 451 and remote servers retry.
- **Spam ML down:** fall back to rules, reputation and auth results; quarantine borderline mail.
- **Search degraded:** partial results plus a recent-mail scan; delivery is unaffected.
- **Our IPs blocklisted:** switch IP pools, throttle the source, use feedback loops; queued mail retries for 5 days.
- **Region lost:** users fail over to the replica region (RPO seconds for metadata); MX DNS lists other regions.

**Trade-offs chosen:**
- **Replicated log over local spool before 250:** survives host loss and decouples MX from mailboxes.
- **Wide-column by user over sharded SQL:** per-user range scans and huge write rates; no cross-user transactions needed.
- **Hot replication, cold erasure coding:** fast reads where they happen, about half the cost elsewhere.
- **Labels over folders:** more flexible, mapped to folders for IMAP; costs one index row per label.
- **Async search indexing (under 5 s):** keeps delivery fast and isolates search outages.

**What to measure:** SMTP accept, temp-fail and reject rates by reason; queue lag (alert over 60 s); delivery latency p99 to mailbox and to push; spam-in-inbox and false-positive rates; search lag and p99; history 410 rate; outbound bounces and blocklist status; dedupe ratio and blob audit failures (must be 0).

## Page 5. Say it in the interview

> "I treat email as two systems: an SMTP edge that talks to the rest of the internet, and a mailbox platform for our users. Scope is send, receive, labels, threads, search and attachments, for about two billion accounts and twenty billion deliveries a day, with zero tolerance for losing accepted mail. Inbound mail hits MX gateways that check reputation, SPF, DKIM and DMARC, then write to a zone-replicated queue before saying 250 OK. Delivery workers classify spam, store bodies once in a content-addressed blob store, and write per-user metadata plus a history id into a wide-column store partitioned by user. Search and push hang off a change stream; clients sync by asking for changes since their last history id. Storage cost and spam, not request rate, are the real scale problems."

**Key points to land:**
- Two systems: a hostile-internet SMTP edge and a per-user mailbox platform.
- 250 OK is the durability boundary; ack after a zone-replicated write.
- After the queue, at-least-once delivery with idempotent per-user writes.
- Partition by user_id; inbox is a single-partition range scan.
- Bodies immutable, content-addressed, deduped; metadata small and mutable.
- Storage dominates: dedupe, compression, hot replication, cold erasure coding.
- Spam is the real scale problem: reject cheaply, then auth, reputation and ML.
- Clients sync by history id; push just says "pull since H".
- Search and notifications are derived and rebuildable.

**Likely follow-ups:**
1. **How do you never lose an email?** Ack only after a cross-zone replicated write; idempotent downstream; checksummed, audited blobs; backups for logical corruption.
2. **How does undo send work?** The job stays scheduled for 5-30 s and can be cancelled by id; internal mail is delayed too.
3. **What is the hardest part in practice?** Abuse: spam outnumbers real mail, attackers adapt daily, and both false positives and negatives cost trust.
4. **How do IMAP clients fit?** An adapter maps labels to folders, assigns UIDs, maps history ids to CONDSTORE modseq, and supports IDLE.
5. **How do you move a mailbox between regions?** Copy a snapshot, tail the history log, briefly freeze writes, switch the home pointer in the directory, drain.

**Director layer:**
- **Cost drivers:** exabyte storage (dedupe and erasure coding cut it most) and the anti-abuse pipeline, which takes most of the compute.
- **Constraints:** SMTP, MIME, SPF, DKIM, DMARC compliance; GDPR deletion and data residency; free-tier economics.
- **Team ownership:** SMTP edge and outbound, mailbox storage, search, sync and clients, trust and safety.
- **Top risks:** our IPs blocklisted after account compromise, phishing slipping past filters, attachment storage cost, and recent mail lost in a region outage.

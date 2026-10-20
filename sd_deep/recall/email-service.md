# Email service (Gmail): recall card

> **Hook:** Reject spam at the edge → Queue durably, then 250 OK → Classify and dedupe → Write per-user mailbox → Sync by history id

**P · Problem:** It's really two systems: a hostile-internet SMTP edge and a per-user mailbox store kept for decades.

**N · Numbers:**
1. 1.15M SMTP connections/s, about 70% spam, so reject cheaply at the edge before DATA.
2. 230k deliveries/s, 700k/s peak, so deliver asynchronously from a queue.
3. 3.6 EB logical becomes 3.3 EB physical after dedupe and erasure coding, so storage cost, not QPS, dominates.

**H · Hard part:** Never losing mail after 250 OK while spam outnumbers real mail and storage grows by petabytes a day.

**B · Boxes:** `Internet MTA → MX gateway → Delivery queue (Kafka) → Delivery workers → Mailbox store`

Side path: `Change stream → Search service and Notifier` for search and push.

**D · Decisions:**
1. Replicated log over local spool before 250 OK, because it survives host loss and decouples MX from mailboxes.
2. Wide-column by user over sharded SQL, because inbox is a per-user range scan at huge write rates.
3. Hot replication over erasure coding for recent mail, because reads happen there, while cold mail uses erasure coding at about half the cost.

**F · Failures:**
1. Mailbox shard down → workers back off, queue lag grows, SMTP keeps accepting; no loss.
2. Queue below 2 in-sync replicas → MX returns 451 and remote servers retry for up to 5 days.

**C · Close:** "So email is two systems. MX gateways check reputation, SPF, DKIM and DMARC, then write to a zone-replicated queue before saying 250 OK. Workers classify spam, store bodies once in a content-addressed blob store, and write per-user metadata plus a history id into a wide-column store. Search and push hang off a change stream, and clients sync by asking for changes since their last history id. Next I would cover IMAP adapters."

**Quiz yourself:**
1. Where is the durability boundary? → The 250 OK, sent only after a zone-replicated queue write.
2. How is a redelivered message not duplicated? → A conditional insert on user and message id, with the history id in the same transaction.
3. How is one newsletter stored for a million users? → Once, named by its SHA-256, with a million references.

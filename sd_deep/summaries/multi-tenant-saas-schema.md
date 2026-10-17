# Design a multi-tenant SaaS schema (pool, bridge and silo tenancy): the 5-page summary

One B2B product must serve 50,000 small tenants cheaply and a few giant enterprise tenants safely, from one codebase. The single most important idea: pool everyone by default with tenant_id leading every key and isolation enforced twice (data access layer plus row-level security), and use a tenant directory so any tenant can be moved to its own shard, schema or database without code changes.

## Page 1. The problem, scope and numbers

**Pitch:** a schema and data platform where tens of thousands of organisations share infrastructure, no tenant can ever see another's data, and a whale can graduate to dedicated capacity online.

**Who uses it:** tenant admins (instant workspace, custom fields, export and delete), end users (often members of several tenants), platform engineers (one data API that is hard to misuse), SRE and DBAs (move tenants, roll migrations, restore one tenant), enterprise security teams (proof of isolation, residency).

**In scope:**
- **Provisioning:** a pool tenant is created by inserting rows, no DDL, in under 5 s.
- **Routing:** every request goes to the tenant's shard or silo via the tenant directory.
- **Isolation:** tenant filter in the data access layer plus database row-level security.
- **Multi-tenant users:** one login, memberships in many tenants with per-tenant roles.
- **Custom fields:** per-tenant field definitions, type-checked, optionally indexed.
- **Lifecycle:** online tenant moves (under 30 s write freeze), export, hard delete within 30 days, migrations everywhere.

**Out of scope:** the analytics warehouse beyond consuming CDC, billing logic, search indexing, identity provider and SSO details.

**Non-functional targets:**
- **Isolation:** zero cross-tenant reads or writes; RLS on 100% of tenant tables.
- **Latency:** API p99 under 150 ms; primary-key query p99 under 20 ms.
- **Availability:** 99.95% per tenant; one shard failure hits under 5% of tenants.
- **Durability:** RPO 5 minutes (WAL archiving), 3 copies in region; enterprise restore RTO 4 h.
- **Residency:** EU data stays in the EU, Indian data in India (DPDP Act).
- **Cost:** under about 2 USD per month per pooled tenant.

**Capacity math (50,000 tenants, 2M users, 400k daily active):**
- **Small tenants:** 49,950 x 200,000 rows x 1 KB = about 10 TB.
- **Whales:** 50 x 80M rows x 1 KB = about 4 TB, so 0.1% of tenants hold about 30% of storage. So hashing alone will not balance load; placement must be load-aware.
- **Queries:** 20,000 requests/s x 4 = 80,000 QPS, 64,000 reads and 16,000 writes.
- **Shards:** one 32 vCPU PostgreSQL primary does 10,000 to 15,000 simple writes/s, so at least 2 shards; with headroom and about 1 TB each, plan 16 pooled shards. So shard by tenant.
- **Per shard:** about 3,100 tenants, 5,000 QPS, 2 read replicas.
- **Connections:** a primary handles only a few thousand, so per-tenant pools are impossible; PgBouncer in transaction mode, 400 server connections per shard.

## Page 2. The architecture

```
 Client -> API gateway (JWT: user_id, tenant_id, rate limit) -> App services
                                                                  |
                                                         Tenant-aware DAL
                                                          |            |
                                  Tenant directory (cached 60 s)    Redis
                                                          |   tenant:{id}:*
           +-----------------------+----------------------+
           |                       |                      |
   Pool shards 1..16        Bridge cluster          Silo DBs (enterprise)
   PgBouncer + Postgres     schema per tenant       DB per tenant, own region
   RLS on tenant_id         search_path = t_123     same DDL, same code
   2 replicas each
           |
   CDC (Debezium) -> Kafka -> Warehouse (cross-tenant analytics, billing)

 Control plane: Provisioner | Migration orchestrator | Tenant mover | Quotas
```

- **API gateway:** validates the JWT, checks membership, applies per-tenant rate limits.
- **Tenant directory:** tenant_id -> tier, region, shard, status; cached in every app node.
- **Tenant-aware DAL:** routes to the shard, sets tenant context, refuses unscoped queries.
- **Pooled shards:** thousands of tenants each; tenant_id leads every key; RLS on.
- **Bridge and silo:** dedicated schema or database for enterprise; identical DDL.
- **PgBouncer:** multiplexes many app connections onto few server connections.
- **Migration orchestrator:** expand-and-contract steps on every target, tracked per target.
- **Tenant mover:** logical replication copy, catch-up, brief freeze, directory flip.
- **CDC to warehouse:** analytics, billing and search kept off the OLTP path.

**Flow A: authenticated read**
1. GET /v1/records with a JWT holding user_id and the active tenant_id.
2. Gateway verifies it, checks membership, takes a token from the tenant's bucket.
3. DAL resolves the tenant to shard 7 from its cache and borrows a PgBouncer connection.
4. In a transaction: SET LOCAL app.tenant_id, then a query with WHERE tenant_id = $1.
5. RLS filters again; index (tenant_id, status, updated_at) returns rows in about 5 ms.

**Flow B: provisioning a pool tenant**
1. Provisioner picks the least-loaded shard in the tenant's region.
2. Inserts the directory row (provisioning), then seed rows (roles, settings) in the shard.
3. Marks the tenant active, in under 5 s, because no DDL runs.

## Page 3. The core deep dives

### 1. Isolation in depth
Four independent layers. The tenant comes from the signed token, never the URL. The DAL injects tenant_id into every query. PostgreSQL RLS adds a policy USING (tenant_id = current_setting('app.tenant_id')) to every read and a WITH CHECK to every write, so a forgotten WHERE clause returns an empty result instead of a leak. Composite foreign keys (tenant_id, x_id) make cross-tenant references impossible. The trap: PgBouncer transaction pooling reuses server connections, so a session-level SET would leak to the next tenant; SET LOCAL dies at COMMIT. If the setting is missing, current_setting raises and the query fails closed. The app role is not the table owner and has no BYPASSRLS.

### 2. Sharding by tenant with a directory
tenant_id is the shard key because almost every query is within one tenant; co-locating all of a tenant's tables keeps joins and transactions on one node. Hashing balances tenant counts, but sizes follow a power law, so a directory places tenants by load: score = 0.5 x bytes + 0.3 x QPS + 0.2 x tenant count (each as a share of the shard's budget), skip shards above 0.7, and open a new shard if none fit.

### 3. Online tenant move (whale to its own shard)
Create a logical replication publication filtered to tenant_id = X (PostgreSQL 15 row filters). The target copies a snapshot, then streams changes until lag is under 1 s. Mark the tenant "moving"; writes get a retryable 503 for a few seconds while reads continue. Wait for lag 0, compare row counts and checksums, flip the directory shard and bump its version, and broadcast invalidation. Old rows are deleted after 7 days. Any failure aborts before the flip, so the tenant never loses reads.

### 4. Custom fields and migrations
Custom fields live in a JSONB column validated against per-tenant definitions (max 200 per object type). An indexed field gets a partial expression index for that tenant only, capped at 10 per tenant. EAV was rejected: three conditions mean three self-joins over a tall table. Migrations use expand and contract: add, dual-write, backfill in 5,000-row batches, switch reads, drop, with lock_timeout 3 s.

**Data model:**
- **tenant** (control-plane PostgreSQL): PK tenant_id; tier, region, shard_id, status, dir_version; about 50,000 rows, cached.
- **membership** (global identity DB): PK (user_id, tenant_id) plus role; index (tenant_id, user_id).
- **record** (pooled shard): PK (tenant_id, record_id); index (tenant_id, status, updated_at); custom jsonb; sharded by tenant_id.
- **field_definition**: PK (tenant_id, object_type, field_key).
- **tenant_usage** (Redis): usage:{tenant_id}:{minute} for noisy-neighbour detection and billing.

**Key APIs:**
- `POST /v1/tenants`: control plane; idempotent on an Idempotency-Key header.
- `GET /v1/records?filter=&cursor=`: keyset pagination on (tenant_id, updated_at, id).
- `POST /v1/fields`: defines a custom field; indexed=true schedules a concurrent index build.
- `POST /internal/tenants/{id}/move`: starts the mover state machine, returns job_id.
- `DELETE /v1/tenants/{id}`: suspends now, purges after 30 days, crypto-shreds backups.

## Page 4. Scale, failures and trade-offs

**Bottlenecks at 10x:**
- **Writes:** add pooled shards; growth is linear because tenants never span shards.
- **Whales:** when a tenant exceeds 20% of a shard's CPU for an hour, recommend a move to a dedicated shard or silo.
- **Noisy neighbours:** token buckets at the gateway, per-tenant concurrency caps in the DAL, statement_timeout 5 s, reports on replicas or the warehouse.
- **Connections:** PgBouncer transaction pooling, never per-tenant pools.
- **Sign-up bursts (1,000 tenants a minute):** provisioning is row inserts, and a pre-warmed empty shard per region is kept ready.

**Failure modes:**
- **Shard primary fails:** Patroni promotes the synchronous standby in about 30 s; only that shard's roughly 3,100 tenants see errors; clients retry with backoff and jitter.
- **Directory database down:** app nodes serve from their in-memory snapshot; provisioning and moves pause.
- **Tenant move fails in catch-up:** abort, never flip, drop the subscription, delete target rows.
- **Migration takes a long lock:** lock_timeout aborts it, the orchestrator retries; the contract step waits for every target.
- **Redis down:** reads fall back to replicas with per-tenant concurrency caps; rate limits use local buckets.
- **Region lost:** tenants fail over to the paired region within residency rules (EU to EU); RPO a few seconds, RTO under 1 h.

**Trade-offs chosen:**
- **Pool by default, silo as a paid tier, over one model for all:** 50,000 databases are unmanageable; a few hundred silos are fine.
- **App filter and RLS over either alone:** each covers the other's failure modes; RLS overhead is small.
- **Directory over pure hash mapping:** skew and residency need load-aware placement, and a move becomes one update.
- **JSONB over EAV or pre-allocated columns:** in-row reads, flexible, indexable on demand.
- **Composite (tenant_id, id) keys over global sequences:** clusters a tenant's rows, enables composite FKs, makes moves conflict-free.
- **CDC to a warehouse over querying OLTP replicas:** keeps scans off the transactional path.
- **PostgreSQL sharding over distributed SQL:** cheaper per tenant, faster single-row ops, team expertise.

**What to measure:** any RLS violation or missing app.tenant_id (alert on 1), p99 per tenant and per shard, tenants breaching SLO, per-tenant QPS, rows scanned, CPU and bytes, shard skew (max/avg), PgBouncer wait time, replication and move lag, migration version per target, provisioning latency.

## Page 5. Say it in the interview

> "I will assume 50,000 business tenants with heavy skew: most are tiny, the top 50 hold about 30% of the data, and enterprises pay for residency or a dedicated database. I start with the cheapest safe model: pooled PostgreSQL tables where tenant_id leads every key, and isolation enforced twice, by the data access layer and by row-level security driven by a transaction-local setting. A tenant directory maps each tenant to a tier, region and shard, so I shard by tenant with all its tables co-located and can move a whale to its own schema or database without code changes. At 80,000 QPS that is 16 shards behind PgBouncer. Custom fields go into validated JSONB. I defend it with per-tenant limits, online moves, expand-and-contract migrations and per-tenant metrics."

**Key points to land:**
- Pool by default, bridge or silo as a paid tier, one schema everywhere.
- tenant_id leads every primary key, index and foreign key.
- Defense in depth: token, DAL injection, RLS with SET LOCAL, composite FKs.
- The directory routes tenants and turns a move into a metadata flip.
- Shard by tenant with co-location so joins and transactions stay on one node.
- Noisy neighbours: rate limit, bulkhead, timeout, then move the whale.
- Custom fields in JSONB with per-tenant definitions and partial indexes.
- Expand-and-contract migrations tracked per shard and silo.
- Cross-tenant analytics via CDC to a warehouse, never on OLTP.

**Likely follow-ups:**
1. **How do you prove isolation to an auditor?** Show the layers: signed tenant context, DAL injection, RLS on every table with a CI check for new tables, composite FKs, per-tenant keys, audit logs and cross-tenant pen tests.
2. **Restore one pooled tenant to yesterday 10:00?** Restore the shard backup plus WAL to a scratch instance, extract that tenant's rows and replay them into the live shard with a diff review; silo tenants use native PITR.
3. **Why not a database per tenant?** 50,000 databases to migrate, back up and pool connections for; idle cost dominates. Silo fits the few hundred who pay for it.
4. **Why not CockroachDB or Spanner?** Auto-splitting is attractive, but cost per tenant and single-row latency are higher, RLS differs, and the team knows PostgreSQL.
5. **A whale wants its own AWS account?** That is the silo tier: same code and DDL in their cell, the directory points there, the mover copies the data.

**Director layer:**
- **Cost drivers:** 16 pooled shards with 2 replicas each, a few dozen silos priced as a premium tier, per-tenant cost attribution so pricing tiers stay correct.
- **Phasing:** start with the pool, RLS and the directory; add the mover, silos and residency regions as enterprise demand arrives.
- **Team ownership:** data platform (DAL, directory, mover, migrations), DBA and SRE (shards, backups), security (isolation proof, audits), product teams build on the DAL.
- **Top risks:** a missing tenant filter, a whale outgrowing its shard, half-applied migrations across silos, the directory as a single point of failure, custom fields slowing queries.

# multi-tenant SaaS schema (pool, bridge and silo tenancy): recall card

> **Hook:** Tenant from token → Directory finds shard → SET LOCAL tenant → RLS filters again → Move whales by flipping the directory

**P · Problem:** It's really a data isolation and placement problem: many tiny tenants and a few whales sharing one schema and one codebase.

**N · Numbers:**
1. 50 whales hold about 30% of storage, so hashing alone will not balance load; placement must be load-aware.
2. 80,000 QPS against 10,000 to 15,000 writes/s per Postgres primary, so plan 16 pooled shards sharded by tenant.
3. A primary handles only a few thousand connections, so PgBouncer in transaction mode, never per-tenant pools.

**H · Hard part:** Guaranteeing no tenant ever sees another's data, while a whale can graduate to its own database online.

**B · Boxes:** `Client → API gateway → App service → Tenant-aware DAL → PgBouncer → Pooled Postgres shard`

Side path: `CDC (Debezium) → Kafka → Warehouse` for cross-tenant analytics and billing.

**D · Decisions:**
1. App filter and RLS over either alone, because each covers the other's failure modes and RLS overhead is small.
2. Pool by default, silo as a paid tier over one model for all, because 50,000 databases are unmanageable.
3. JSONB over EAV for custom fields, because reads stay in-row and EAV needs a self-join per condition.

**F · Failures:**
1. Shard primary fails → Patroni promotes the standby in about 30 s; only that shard's 3,100 tenants see errors.
2. Tenant move fails in catch-up → abort before the flip, drop the subscription, delete target rows.

**C · Close:** "I start with the cheapest safe model: pooled Postgres tables where tenant_id leads every key, and isolation enforced twice, by the data access layer and by row-level security with a transaction-local setting. A tenant directory maps each tenant to a tier, region and shard, so I can move a whale to its own schema or database without code changes. At 80,000 QPS that is 16 shards behind PgBouncer. Custom fields go into validated JSONB."

**Quiz yourself:**
1. Why SET LOCAL and not SET? → PgBouncer reuses connections, so a session SET would leak to the next tenant.
2. How is a whale moved? → Filtered logical replication, catch up, brief write freeze, flip the directory.
3. Why composite (tenant_id, id) keys? → They cluster a tenant's rows and make cross-tenant references impossible.

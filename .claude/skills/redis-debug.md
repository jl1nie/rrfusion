# Redis Debug Skill

## Purpose
Debug Redis data structures and diagnose storage issues.

## Redis Data Model

### Lane ZSET
```
Key: z:{snapshot}:{query_hash}:{lane}
Member: doc_id (app_doc_id/app_id)
Score: w_lane / (rrf_k + rank)
TTL: 24h (DATA_TTL_HOURS)
```

### Fusion ZSET
```
Key: z:rrf:{run_id}
Created via: ZUNIONSTORE
TTL: 24h
```

### Code Frequency Hash
```
Key: h:freq:{run_id}:{lane}
Fields: ipc, cpc, fi_norm, fi_full, ft
TTL: 24h
```

### Run Metadata Hash
```
Key: h:run:{run_id}
Fields: recipe, parent, lineage, source_lanes
TTL: 24h
```

### Snippet Cache
```
Key: h:snippet:{doc_id}
Fields: title, abst, claim, desc, app_doc_id, pub_id, exam_id
TTL: 72h (SNIPPET_TTL_HOURS)
```

## Debug Commands

### Connect to Redis
```bash
# Via Docker
docker compose -f infra/compose.ci.yml exec rrfusion-redis redis-cli

# Via local
redis-cli -h localhost -p 6379
```

### Inspect Lane Results
```bash
# List all lane ZSETs
KEYS z:*

# Check lane size
ZCARD z:{snapshot}:{query_hash}:fulltext

# View top 10 docs
ZREVRANGE z:{snapshot}:{query_hash}:fulltext 0 9 WITHSCORES

# Check specific doc score
ZSCORE z:{snapshot}:{query_hash}:fulltext "{doc_id}"
```

### Inspect Fusion Results
```bash
# List fusion runs
KEYS z:rrf:*

# Check fusion size
ZCARD z:rrf:{run_id}

# View top 50 fused docs
ZREVRANGE z:rrf:{run_id} 0 49 WITHSCORES
```

### Inspect Code Frequencies
```bash
# Check freq hash exists
EXISTS h:freq:{run_id}:fulltext

# View all code freq fields
HGETALL h:freq:{run_id}:fulltext

# Check FI/FT specifically
HGET h:freq:{run_id}:fulltext fi_norm
HGET h:freq:{run_id}:fulltext ft
```

### Inspect Run Metadata
```bash
# Get full recipe
HGETALL h:run:{run_id}

# Get specific fields
HGET h:run:{run_id} recipe
HGET h:run:{run_id} parent
HGET h:run:{run_id} lineage
```

### Check TTLs
```bash
# View remaining TTL
TTL z:{snapshot}:{query_hash}:fulltext
TTL h:freq:{run_id}:fulltext
TTL h:snippet:{doc_id}
```

### Memory Analysis
```bash
# Memory stats
INFO memory

# Key distribution
INFO keyspace

# Eviction stats
INFO stats
```

## Common Issues

### Issue: Lane ZSET empty
**Symptoms**: `ZCARD` returns 0

**Diagnosis**:
```bash
# Check if key exists
EXISTS z:{snapshot}:{query_hash}:fulltext

# Check TTL
TTL z:{snapshot}:{query_hash}:fulltext
```

**Solutions**:
- Run might have expired (24h TTL)
- Query hash mismatch
- Search never executed

### Issue: Fusion run not found
**Symptoms**: `get_provenance` returns 404

**Diagnosis**:
```bash
# Check run metadata
EXISTS h:run:{run_id}

# Check fusion ZSET
EXISTS z:rrf:{run_id}
```

**Solutions**:
- Run ID typo
- Run expired
- Fusion never executed

### Issue: Code frequencies missing FI/FT
**Symptoms**: `freq-snapshot` test fails

**Diagnosis**:
```bash
# Check freq hash
HKEYS h:freq:{run_id}:fulltext

# Verify FI/FT buckets
HGET h:freq:{run_id}:fulltext fi_norm
HGET h:freq:{run_id}:fulltext ft
```

**Solutions**:
- Backend not returning FI/FT codes
- Normalization not applied
- Update storage.py to save fi_norm

### Issue: Memory eviction
**Symptoms**: Random key disappearance

**Diagnosis**:
```bash
# Check eviction policy
CONFIG GET maxmemory-policy

# Check memory usage
INFO memory

# Check evicted count
INFO stats | grep evicted
```

**Solutions**:
- Increase `REDIS_MAX_MEMORY` in infra/.env
- Reduce TTLs
- Use `volatile-lru` policy (default)

## Useful Patterns

### Clear all test data
```bash
# Flush DB (CAUTION: development only)
FLUSHDB

# Delete by pattern
redis-cli --scan --pattern "z:*" | xargs redis-cli DEL
```

### Monitor real-time activity
```bash
MONITOR
```

### Snapshot current state
```bash
# Export specific run
redis-cli ZREVRANGE z:rrf:{run_id} 0 -1 WITHSCORES > fusion_dump.txt
redis-cli HGETALL h:run:{run_id} > metadata_dump.txt
```

### Verify fusion math
```python
# In Python shell
import redis
r = redis.from_url("redis://localhost:6379/0")

# Get lane scores
lane1 = r.zrevrange("z:snap:hash:fulltext", 0, -1, withscores=True)
lane2 = r.zrevrange("z:snap:hash:semantic", 0, -1, withscores=True)

# Get fusion result
fusion = r.zrevrange("z:rrf:run123", 0, -1, withscores=True)

# Verify RRF formula
# fusion_score(doc) = sum(w_lane / (k + rank_lane(doc)))
```

## Performance Monitoring

### Slow queries
```bash
SLOWLOG GET 10
```

### Connection stats
```bash
INFO clients
```

### Replication lag (if applicable)
```bash
INFO replication
```

## Environment Variables

### infra/.env
```bash
REDIS_MAX_MEMORY=2gb
REDIS_MAXMEMORY_POLICY=volatile-lru
DATA_TTL_HOURS=12
SNIPPET_TTL_HOURS=24
```

## References
- [storage.py implementation](../../src/rrfusion/storage.py)
- [AGENT.md Redis data model](../../AGENT.md#L96-L104)
- [compose.prod.yml Redis config](../../infra/compose.prod.yml)

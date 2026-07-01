# Redis Queue Backend Implementation

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/redis-queue-backend.md)

## [S1] Problem

SOAR orchestrator needs a production-ready Redis queue backend for distributed deployments. The current `RedisQueue` implementation is minimal and lacks error handling, connection management, and tests.

## [S2] Solution Overview

Iterate on existing `RedisQueue` implementation with:
- Connection pooling and auto-reconnect
- Proper error handling with exponential backoff
- Docker Compose Redis service
- Comprehensive tests
- Health check integration

## [S3] Architecture

Current architecture is already in place:
```
AbstractJobQueue (base.py)
├── InMemoryQueue (memory.py) - for single-instance deployments
└── RedisQueue (redis_queue.py) - for distributed deployments
```

Config already supports:
```yaml
queue:
  backend: memory | redis
  redis_url: redis://localhost:6379/0
```

## [S4] RedisQueue Enhancements

### Connection Management
- Use `aioredis.from_url()` with connection pool
- Configure `max_connections` based on worker count
- Implement automatic reconnection with exponential backoff

### Error Handling
- Catch `redis.exceptions.ConnectionError`
- Log errors with context
- Retry failed operations with backoff
- Fallback to None on persistent failures

### Timeouts
- Configure push/pop timeouts separately
- Default push timeout: 5s
- Default pop timeout: 1.0s (existing)

## [S5] Docker Integration

### Redis Service
```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: soar-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

volumes:
  redis-data:
```

### Orchestrator Dependencies
```yaml
services:
  orchestrator:
    depends_on:
      redis:
        condition: service_healthy
```

## [S6] Configuration

### Default Config (memory)
```yaml
queue:
  backend: memory
```

### Redis Config
```yaml
queue:
  backend: redis
  redis_url: redis://redis:6379/0
```

## [S7] Testing Strategy

### Unit Tests
- Mock `aioredis` for isolated testing
- Test push/pop/size/clear operations
- Test error handling and reconnection
- Test timeout behavior

### Integration Tests
- Use real Redis instance (Docker)
- Test concurrent access
- Test queue persistence across restarts

### Test Files
- `tests/orchestrator/test_redis_queue.py` - unit tests
- `tests/orchestrator/test_redis_integration.py` - integration tests

## [S8] Health Check

### Status Endpoint Enhancement
```json
{
  "queue": {
    "backend": "redis",
    "connected": true,
    "size": 5
  }
}
```

### Redis Connectivity Check
- Verify connection on startup
- Periodic health checks
- Log connection state changes

## [S9] Implementation Tasks

1. **Enhance RedisQueue** - Add connection pooling, error handling, reconnection
2. **Update Docker Compose** - Add Redis service with health check
3. **Update Config** - Add Redis-specific config options
4. **Write Unit Tests** - Mock-based tests for RedisQueue
5. **Write Integration Tests** - Tests with real Redis
6. **Update Health Check** - Add Redis connectivity to /status
7. **Update Documentation** - README, config examples

## [S10] Success Criteria

- [ ] RedisQueue handles connection errors gracefully
- [ ] Auto-reconnect works with exponential backoff
- [ ] Docker Compose includes Redis service
- [ ] All tests pass (unit + integration)
- [ ] Health check shows Redis status
- [ ] Config supports both memory and redis backends

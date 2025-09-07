# Redis Setup for MCP Connection State

## Overview
The MCP connection state is now managed using Redis instead of the database. This provides better performance and automatic cleanup of expired connections.

## Installation

### 1. Install Redis Server

**Windows:**
```bash
# Using Chocolatey
choco install redis-64

# Or download from: https://github.com/microsoftarchive/redis/releases
```

**macOS:**
```bash
brew install redis
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install redis-server
```

### 2. Start Redis Server

**Windows:**
```bash
redis-server
```

**macOS/Linux:**
```bash
redis-server
# Or as a service:
sudo systemctl start redis
sudo systemctl enable redis
```

### 3. Install Python Redis Client

The Redis client is already added to `requirements.txt`:
```bash
pip install redis[hiredis]
```

## Configuration

### Environment Variables
Add to your `.env` file:
```env
REDIS_URL=redis://localhost:6379/0
```

### Default Configuration
- **Host:** localhost
- **Port:** 6379
- **Database:** 0
- **TTL:** 24 hours (connections expire automatically)

## Redis Key Structure

```
mcp:user:{user_id}:connections                    # Set of connected server names
mcp:user:{user_id}:server:{server_name}:status    # Connection status
mcp:user:{user_id}:server:{server_name}:tools     # Tools JSON
mcp:user:{user_id}:server:{server_name}:connected_at # Timestamp

mcp:session:{session_key}:connections             # Set of connected server names (anonymous users)
mcp:session:{session_key}:server:{server_name}:status # Connection status
mcp:session:{session_key}:server:{server_name}:tools  # Tools JSON
mcp:session:{session_key}:server:{server_name}:connected_at # Timestamp
```

## Benefits

1. **Performance:** Much faster than database operations
2. **Automatic Cleanup:** TTL automatically removes expired connections
3. **Scalability:** Handles high concurrency better
4. **Memory Efficient:** Optimized for key-value storage
5. **Atomic Operations:** Built-in atomic operations for state management

## Monitoring

### Check Redis Status
```bash
redis-cli ping
# Should return: PONG
```

### View Connection Keys
```bash
redis-cli keys "mcp:*"
```

### Monitor Redis Activity
```bash
redis-cli monitor
```

## Troubleshooting

### Redis Connection Issues
1. Ensure Redis server is running: `redis-cli ping`
2. Check Redis URL in settings: `REDIS_URL=redis://localhost:6379/0`
3. Verify firewall settings allow Redis port 6379

### Memory Usage
```bash
redis-cli info memory
```

### Clear All MCP Data (if needed)
```bash
redis-cli --scan --pattern "mcp:*" | xargs redis-cli del
```

## Production Considerations

1. **Persistence:** Enable Redis persistence for production
2. **Security:** Set up Redis authentication
3. **Monitoring:** Use Redis monitoring tools
4. **Backup:** Implement Redis backup strategy
5. **Clustering:** Consider Redis Cluster for high availability

---
title: Require Client Identification Headers
impact: MEDIUM
impactDescription: Enables proper debugging, monitoring, and client tracking in production
tags: operations, monitoring, debugging, headers, middleware, observability
---

## Require Client Identification Headers

**Impact: MEDIUM (Enables proper debugging, monitoring, and client tracking in production)**

All GraphQL requests must include client identification headers to enable proper debugging and performance monitoring in production. Without client identification, it's nearly impossible to track down which application or service is causing issues, making debugging production problems extremely difficult.

**Required Headers:**
- `GraphQL-Client-Name`: Identifies the calling application/service (e.g., "web-app", "mobile-ios", "api-service")
- `GraphQL-Client-Version`: Version of the client making the request (e.g., "1.2.3", "2024-01-15")

**Benefits:**
- **Debugging**: Quickly identify which client is making problematic queries
- **Monitoring**: Track performance and error rates per client
- **Deprecation**: Safely deprecate features by knowing which clients use them
- **Rate Limiting**: Apply different rate limits per client
- **Analytics**: Understand client adoption and usage patterns
- **Incident Response**: Correlate issues with specific client versions

**Validation:**
- GraphQL middleware must validate headers are present and non-empty
- Return 400 Bad Request if headers are missing
- Log client identity with every request for observability

**When to Enforce:**
- Production environments (required)
- Staging/QA environments (recommended)
- Development environments (optional, for testing)

**Incorrect (No client identification validation):**

```typescript
// packages/server/src/middleware/graphqlMiddleware.ts
import { Request, Response, NextFunction } from 'express';

// BAD: No validation of client identity
export function graphqlMiddleware(req: Request, res: Response, next: NextFunction) {
  if (req.path === '/graphql') {
    console.log('Processing GraphQL request');
    // No way to identify which client made this request
  }
  next();
}
```

```typescript
// packages/server/src/routes/graphql.ts
import express from 'express';
import { graphqlHTTP } from 'express-graphql';
import { schema } from '../schema';

const router = express.Router();

// BAD: No header validation before processing requests
router.use('/graphql', graphqlHTTP({
  schema,
  graphiql: true
}));

export default router;
```

```typescript
// packages/server/src/apollo-server.ts
import { ApolloServer } from '@apollo/server';
import { startStandaloneServer } from '@apollo/server/standalone';

const server = new ApolloServer({
  typeDefs,
  resolvers
});

// BAD: No client identity validation
const { url } = await startStandaloneServer(server, {
  listen: { port: 4000 },
  context: async ({ req }) => ({
    // No client identity captured
    userId: req.headers.authorization
  })
});
```

```typescript
// Example: Production debugging nightmare without client headers
// Support ticket: "GraphQL API is slow"
// Logs show:
// [2024-01-15 10:30:15] GraphQL query executed in 5000ms
// [2024-01-15 10:30:16] GraphQL query executed in 200ms
// [2024-01-15 10:30:17] GraphQL query executed in 4800ms

// Questions that can't be answered:
// - Which client is making slow queries?
// - Is it all clients or just one?
// - Which version of the client?
// - Is it a specific query or operation?
// - Can we contact the team responsible?
```

```typescript
// Example: Impossible to deprecate features without client tracking
// Want to remove deprecated field but don't know who's using it

type Query {
  oldEndpoint: String @deprecated(reason: "Use newEndpoint instead")
  newEndpoint: String
}

// Questions that can't be answered:
// - Which clients are still using oldEndpoint?
// - What versions?
// - Can we safely remove it?
// - Who do we need to notify?
```

**Correct (Required client identification headers):**

```typescript
// packages/server/src/middleware/clientIdentityMiddleware.ts
import { Request, Response, NextFunction } from 'express';

interface ClientIdentity {
  name: string;
  version: string;
}

declare global {
  namespace Express {
    interface Request {
      clientIdentity?: ClientIdentity;
    }
  }
}

// GOOD: Validate client identity headers
export function validateClientIdentity(
  req: Request,
  res: Response,
  next: NextFunction
) {
  if (req.path === '/graphql') {
    const clientName = req.headers['graphql-client-name'] as string;
    const clientVersion = req.headers['graphql-client-version'] as string;

    // Validate both headers are present
    if (!clientName || !clientVersion) {
      return res.status(400).json({
        errors: [{
          message: 'Missing required client identification headers',
          extensions: {
            code: 'MISSING_CLIENT_HEADERS',
            required: ['GraphQL-Client-Name', 'GraphQL-Client-Version']
          }
        }]
      });
    }

    // Validate header format
    if (clientName.length < 3 || clientName.length > 50) {
      return res.status(400).json({
        errors: [{
          message: 'Invalid GraphQL-Client-Name: must be 3-50 characters',
          extensions: { code: 'INVALID_CLIENT_NAME' }
        }]
      });
    }

    // Add to request for downstream use
    req.clientIdentity = {
      name: clientName,
      version: clientVersion
    };
  }

  next();
}
```

```typescript
// packages/server/src/routes/graphql.ts
import express from 'express';
import { graphqlHTTP } from 'express-graphql';
import { schema } from '../schema';
import { validateClientIdentity } from '../middleware/clientIdentityMiddleware';

const router = express.Router();

// GOOD: Validate client identity before processing
router.use(
  '/graphql',
  validateClientIdentity,  // Validate headers first
  graphqlHTTP({
    schema,
    graphiql: process.env.NODE_ENV !== 'production',
    context: (req) => ({
      // Pass client identity to resolvers
      clientName: req.clientIdentity?.name,
      clientVersion: req.clientIdentity?.version,
      userId: req.user?.id
    })
  })
);

export default router;
```

```typescript
// packages/server/src/apollo-server.ts
import { ApolloServer } from '@apollo/server';
import { startStandaloneServer } from '@apollo/server/standalone';
import { GraphQLError } from 'graphql';

// GOOD: Plugin to validate client headers
const clientIdentityPlugin = {
  async requestDidStart({ request, contextValue }: any) {
    const clientName = request.http?.headers.get('graphql-client-name');
    const clientVersion = request.http?.headers.get('graphql-client-version');

    if (!clientName || !clientVersion) {
      throw new GraphQLError('Missing required client identification headers', {
        extensions: {
          code: 'MISSING_CLIENT_HEADERS',
          required: ['GraphQL-Client-Name', 'GraphQL-Client-Version'],
          http: { status: 400 }
        }
      });
    }

    // Add to context
    contextValue.clientName = clientName;
    contextValue.clientVersion = clientVersion;
  }
};

const server = new ApolloServer({
  typeDefs,
  resolvers,
  plugins: [clientIdentityPlugin]
});

const { url } = await startStandaloneServer(server, {
  listen: { port: 4000 },
  context: async ({ req }) => ({
    // Context will be populated by plugin
    userId: req.headers.authorization
  })
});
```

```typescript
// packages/server/src/logging/requestLogger.ts
import { Request } from 'express';
import { logger } from './logger';

// GOOD: Log client identity with every request
export function logGraphQLRequest(
  req: Request,
  operation: string,
  duration: number
) {
  logger.info('GraphQL request', {
    operation,
    duration,
    // Client identification for debugging
    client: {
      name: req.clientIdentity?.name,
      version: req.clientIdentity?.version
    },
    // Request metadata
    userId: req.user?.id,
    ip: req.ip,
    timestamp: new Date().toISOString()
  });
}

// Now when investigating issues:
// [2024-01-15 10:30:15] GraphQL request {
//   operation: "GetUser",
//   duration: 5000,
//   client: { name: "mobile-ios", version: "2.1.0" },
//   userId: "user_123"
// }
//
// Can immediately identify: iOS app v2.1.0 has performance issue
```

```typescript
// packages/server/src/monitoring/metrics.ts
// GOOD: Track metrics per client

interface MetricsCollector {
  recordQuery(operation: string, duration: number, client: ClientIdentity): void;
}

export class GraphQLMetrics {
  recordQuery(
    operation: string,
    duration: number,
    clientName: string,
    clientVersion: string
  ) {
    // Track performance per client
    this.histogram.record(duration, {
      operation,
      client_name: clientName,
      client_version: clientVersion
    });

    // Alert if specific client version has issues
    if (duration > 5000 && clientName === 'mobile-ios' && clientVersion === '2.1.0') {
      this.alerting.send({
        severity: 'warning',
        message: `Slow query detected for ${clientName} v${clientVersion}`,
        operation,
        duration
      });
    }
  }
}
```

```typescript
// packages/server/src/deprecation/tracker.ts
// GOOD: Track deprecated field usage by client

export function trackDeprecatedFieldUsage(
  fieldPath: string,
  clientName: string,
  clientVersion: string
) {
  logger.warn('Deprecated field used', {
    field: fieldPath,
    client: { name: clientName, version: clientVersion }
  });

  // Store in database for analysis
  db.deprecationUsage.create({
    fieldPath,
    clientName,
    clientVersion,
    timestamp: new Date()
  });
}

// Query deprecated field usage:
// SELECT client_name, client_version, COUNT(*)
// FROM deprecation_usage
// WHERE field_path = 'Query.oldEndpoint'
// GROUP BY client_name, client_version
//
// Results:
// web-app v1.0.0: 1,234 uses
// mobile-ios v2.0.0: 567 uses
//
// Now we know exactly who to contact before removing the field!
```

```typescript
// packages/web-app/src/graphql/client.ts
// GOOD: Client-side configuration with headers

import { ApolloClient, InMemoryCache, createHttpLink } from '@apollo/client';
import { setContext } from '@apollo/client/link/context';

const httpLink = createHttpLink({
  uri: 'https://api.example.com/graphql'
});

// Add client identification headers
const clientIdentityLink = setContext((_, { headers }) => ({
  headers: {
    ...headers,
    'GraphQL-Client-Name': 'web-app',
    'GraphQL-Client-Version': process.env.REACT_APP_VERSION || '1.0.0'
  }
}));

export const client = new ApolloClient({
  link: clientIdentityLink.concat(httpLink),
  cache: new InMemoryCache()
});
```

```typescript
// packages/mobile-app/src/api/graphql.ts
// GOOD: Mobile app with version from build

import { ApolloClient, InMemoryCache, HttpLink } from '@apollo/client';
import DeviceInfo from 'react-native-device-info';

const httpLink = new HttpLink({
  uri: 'https://api.example.com/graphql',
  headers: {
    'GraphQL-Client-Name': 'mobile-ios',
    'GraphQL-Client-Version': DeviceInfo.getVersion() // e.g., "2.1.0"
  }
});

export const client = new ApolloClient({
  link: httpLink,
  cache: new InMemoryCache()
});
```

```typescript
// packages/backend-service/src/graphql/client.ts
// GOOD: Service-to-service with service name

import { GraphQLClient } from 'graphql-request';

export const graphqlClient = new GraphQLClient(
  'https://api.example.com/graphql',
  {
    headers: {
      'GraphQL-Client-Name': 'notification-service',
      'GraphQL-Client-Version': process.env.SERVICE_VERSION || '1.0.0'
    }
  }
);
```

```typescript
// packages/server/src/ratelimiting/clientRateLimiter.ts
// GOOD: Different rate limits per client type

import rateLimit from 'express-rate-limit';

export function createClientAwareRateLimiter() {
  return rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: (req) => {
      const clientName = req.clientIdentity?.name;

      // Different limits for different clients
      switch (clientName) {
        case 'web-app':
          return 1000; // Higher limit for web
        case 'mobile-ios':
        case 'mobile-android':
          return 500;  // Mobile apps
        case 'notification-service':
          return 10000; // Internal services get high limits
        default:
          return 100;   // Unknown clients get low limits
      }
    },
    message: (req) => ({
      error: 'Too many requests',
      client: req.clientIdentity?.name,
      retryAfter: '15 minutes'
    })
  });
}
```

```typescript
// Example: Dashboard showing client adoption

// Query: Which clients are using the new API?
SELECT
  client_name,
  client_version,
  COUNT(DISTINCT user_id) as active_users,
  COUNT(*) as total_requests
FROM graphql_logs
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY client_name, client_version
ORDER BY active_users DESC;

// Results:
// web-app v3.2.0:    5,432 users,  123,456 requests
// mobile-ios v2.1.0:  3,210 users,   89,012 requests
// mobile-ios v2.0.0:  1,234 users,   34,567 requests (old version!)
//
// Action: Send push notification to iOS users to update app
```

```typescript
// packages/server/src/middleware/clientIdentityMiddleware.ts
// GOOD: Enhanced validation with allowlist

const ALLOWED_CLIENTS = [
  'web-app',
  'mobile-ios',
  'mobile-android',
  'notification-service',
  'email-service',
  'analytics-service'
];

export function validateClientIdentity(
  req: Request,
  res: Response,
  next: NextFunction
) {
  if (req.path === '/graphql') {
    const clientName = req.headers['graphql-client-name'] as string;
    const clientVersion = req.headers['graphql-client-version'] as string;

    if (!clientName || !clientVersion) {
      return res.status(400).json({
        errors: [{
          message: 'Missing required headers: GraphQL-Client-Name and GraphQL-Client-Version'
        }]
      });
    }

    // Validate client is recognized
    if (!ALLOWED_CLIENTS.includes(clientName)) {
      logger.warn('Unknown client attempted GraphQL request', {
        clientName,
        clientVersion,
        ip: req.ip
      });

      return res.status(403).json({
        errors: [{
          message: 'Unknown client',
          extensions: { code: 'UNKNOWN_CLIENT' }
        }]
      });
    }

    req.clientIdentity = { name: clientName, version: clientVersion };
  }

  next();
}
```

```typescript
// packages/server/src/monitoring/alerting.ts
// GOOD: Alert on anomalous client behavior

export function monitorClientBehavior(
  clientName: string,
  clientVersion: string,
  errorRate: number
) {
  // Alert if error rate is abnormally high for specific client
  if (errorRate > 0.1) {  // 10% error rate
    alerting.send({
      severity: 'critical',
      title: `High error rate for ${clientName} v${clientVersion}`,
      description: `Error rate: ${(errorRate * 100).toFixed(1)}%`,
      action: `Check logs for client ${clientName} version ${clientVersion}`
    });
  }
}
```

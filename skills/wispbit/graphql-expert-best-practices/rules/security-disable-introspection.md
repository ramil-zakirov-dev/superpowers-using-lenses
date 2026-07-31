---
title: Disable Introspection in Production
impact: MEDIUM
impactDescription: Prevents schema disclosure and information leakage
tags: security, introspection, production, configuration
---

## Disable Introspection in Production

**Impact: MEDIUM (Prevents schema disclosure and information leakage)**

Disable GraphQL introspection in production environments by setting `introspection: false` in the GraphQL server configuration. Introspection allows clients to query the entire GraphQL schema, including types, fields, arguments, and descriptions. While useful for development and documentation tools, leaving it enabled in production exposes your API structure to potential attackers.

**Security Risks of Enabled Introspection:**
- **Schema Disclosure**: Attackers can discover all available queries, mutations, and types
- **Attack Surface Mapping**: Reveals internal API structure and relationships
- **Field Discovery**: Exposes deprecated fields, admin-only operations, or internal endpoints
- **Business Logic Hints**: Type names and field names can reveal business logic and data models
- **Enumeration**: Allows discovery of enum values that might reveal sensitive information

**When Introspection Should Be Disabled:**
- Production environments serving public-facing APIs
- APIs handling sensitive data or operations
- APIs with role-based access control that shouldn't be discoverable
- Any environment where schema structure should remain private

**When Introspection Can Remain Enabled:**
- Local development environments
- Internal development/staging servers (with proper network restrictions)
- APIs explicitly designed to be fully public and documented
- Testing environments (with proper access controls)

**Best Practices:**
- Use environment variables to control introspection (e.g., `NODE_ENV`)
- Disable both introspection and GraphQL Playground together in production
- Consider rate limiting introspection queries even in non-production environments
- Use schema documentation tools that don't require live introspection

**Defense in Depth:**
- Disabling introspection is one layer of security, not the only defense
- Still implement proper authentication and authorization
- Use field-level permissions to restrict access
- Monitor and log GraphQL queries for suspicious patterns

**Incorrect (Introspection enabled in production):**

```typescript
// packages/server/src/server.ts
import { ApolloServer } from '@apollo/server';
import { startStandaloneServer } from '@apollo/server/standalone';
import { typeDefs } from './schema';
import { resolvers } from './resolvers';

// BAD: Introspection explicitly enabled
const server = new ApolloServer({
  typeDefs,
  resolvers,
  introspection: true,  // Exposes schema in production
});

await startStandaloneServer(server, {
  listen: { port: 4000 }
});
```

```typescript
// packages/server/src/graphql/server.ts
import { GraphQLServer } from 'graphql-yoga';

// BAD: Missing introspection configuration - defaults to enabled
const server = new GraphQLServer({
  typeDefs: './schema.graphql',
  resolvers,
  // No introspection setting - defaults to true
});

server.start(() => {
  console.log('Server running');
});
```

```typescript
// packages/server/src/api/graphql.ts
import { createServer } from '@graphql-yoga/node';
import { schema } from './schema';

// BAD: Introspection always enabled regardless of environment
const server = createServer({
  schema,
  introspection: true,  // Should be conditional
  graphiql: true,       // Should also be disabled in production
});
```

```typescript
// packages/server/src/apollo-server.ts
import { ApolloServer } from '@apollo/server';
import { expressMiddleware } from '@apollo/server/express4';
import express from 'express';

const app = express();

// BAD: Wrong condition - introspection enabled in production
const server = new ApolloServer({
  typeDefs,
  resolvers,
  introspection: process.env.NODE_ENV !== 'production' ? true : true,  // Always true!
});

await server.start();
app.use('/graphql', expressMiddleware(server));
```

```typescript
// packages/server/src/index.ts
import { createYoga } from 'graphql-yoga';
import { createServer } from 'http';

// BAD: No introspection control
const yoga = createYoga({
  schema,
  // Missing introspection configuration
  // Missing graphiql configuration
});

const server = createServer(yoga);
server.listen(4000);
```

```typescript
// Example: Production deployment with introspection exposed
// Dockerfile
ENV NODE_ENV=production
ENV PORT=4000

// server.ts - BAD
const server = new ApolloServer({
  typeDefs,
  resolvers,
  // Introspection not disabled despite production environment
});

// This allows attackers to run:
// query {
//   __schema {
//     types {
//       name
//       fields {
//         name
//       }
//     }
//   }
// }
```

**Correct (Introspection disabled in production):**

```typescript
// packages/server/src/server.ts
import { ApolloServer } from '@apollo/server';
import { startStandaloneServer } from '@apollo/server/standalone';
import { typeDefs } from './schema';
import { resolvers } from './resolvers';

// GOOD: Introspection disabled in production
const server = new ApolloServer({
  typeDefs,
  resolvers,
  introspection: process.env.NODE_ENV !== 'production',
});

await startStandaloneServer(server, {
  listen: { port: 4000 }
});
```

```typescript
// packages/server/src/graphql/server.ts
import { GraphQLServer } from 'graphql-yoga';

// GOOD: Explicitly disable introspection in production
const server = new GraphQLServer({
  typeDefs: './schema.graphql',
  resolvers,
  introspection: process.env.NODE_ENV === 'development',
  playground: process.env.NODE_ENV === 'development',
});

server.start(() => {
  console.log('Server running');
});
```

```typescript
// packages/server/src/api/graphql.ts
import { createServer } from '@graphql-yoga/node';
import { schema } from './schema';

// GOOD: Conditional introspection and playground based on environment
const server = createServer({
  schema,
  introspection: process.env.NODE_ENV !== 'production',
  graphiql: process.env.NODE_ENV !== 'production',
  maskedErrors: process.env.NODE_ENV === 'production',
});

server.start();
```

```typescript
// packages/server/src/apollo-server.ts
import { ApolloServer } from '@apollo/server';
import { expressMiddleware } from '@apollo/server/express4';
import express from 'express';
import { typeDefs } from './schema';
import { resolvers } from './resolvers';

const app = express();

// GOOD: Multiple security configurations based on environment
const isProd = process.env.NODE_ENV === 'production';

const server = new ApolloServer({
  typeDefs,
  resolvers,
  introspection: !isProd,
  // Also disable in production
  includeStacktraceInErrorResponses: !isProd,
  // Cache control
  cache: isProd ? 'bounded' : undefined,
});

await server.start();

app.use(
  '/graphql',
  express.json(),
  expressMiddleware(server, {
    context: async ({ req }) => ({
      user: await authenticateUser(req),
    }),
  })
);

app.listen(4000);
```

```typescript
// packages/server/src/yoga-server.ts
import { createYoga } from 'graphql-yoga';
import { createServer } from 'http';
import { schema } from './schema';

// GOOD: Comprehensive production configuration
const isDevelopment = process.env.NODE_ENV === 'development';

const yoga = createYoga({
  schema,
  // Security settings
  introspection: isDevelopment,
  graphiql: isDevelopment,
  // Error masking in production
  maskedErrors: !isDevelopment,
  // Logging configuration
  logging: {
    level: isDevelopment ? 'debug' : 'error',
  },
});

const server = createServer(yoga);
server.listen(4000, () => {
  console.log(`Server running on http://localhost:4000/graphql`);
});
```

```typescript
// packages/server/src/config/graphql.ts
// GOOD: Centralized configuration with environment-based settings

interface GraphQLConfig {
  introspection: boolean;
  playground: boolean;
  debug: boolean;
  includeStacktrace: boolean;
}

export const getGraphQLConfig = (): GraphQLConfig => {
  const env = process.env.NODE_ENV || 'development';

  const configs: Record<string, GraphQLConfig> = {
    production: {
      introspection: false,
      playground: false,
      debug: false,
      includeStacktrace: false,
    },
    staging: {
      introspection: false,  // Also disable in staging
      playground: true,       // But allow playground for testing
      debug: true,
      includeStacktrace: true,
    },
    development: {
      introspection: true,
      playground: true,
      debug: true,
      includeStacktrace: true,
    },
  };

  return configs[env] || configs.development;
};

// Usage
import { ApolloServer } from '@apollo/server';
import { getGraphQLConfig } from './config/graphql';

const config = getGraphQLConfig();

const server = new ApolloServer({
  typeDefs,
  resolvers,
  introspection: config.introspection,
  includeStacktraceInErrorResponses: config.includeStacktrace,
});
```

```typescript
// packages/server/src/middleware/security.ts
// GOOD: Additional layer - custom introspection blocking middleware

import { GraphQLError } from 'graphql';

export const disableIntrospectionPlugin = {
  async requestDidStart() {
    return {
      async didResolveOperation({ request, operation }: any) {
        // Block introspection queries
        if (
          operation?.operation === 'query' &&
          operation?.selectionSet?.selections?.some((selection: any) => {
            return (
              selection?.name?.value === '__schema' ||
              selection?.name?.value === '__type'
            );
          })
        ) {
          throw new GraphQLError('Introspection is disabled', {
            extensions: { code: 'INTROSPECTION_DISABLED' },
          });
        }
      },
    };
  },
};

// Usage with ApolloServer
const server = new ApolloServer({
  typeDefs,
  resolvers,
  plugins: [
    process.env.NODE_ENV === 'production'
      ? disableIntrospectionPlugin
      : {},
  ],
});
```

```typescript
// packages/server/.env.production
// GOOD: Environment variables for production

NODE_ENV=production
GRAPHQL_INTROSPECTION=false
GRAPHQL_PLAYGROUND=false
ENABLE_DEBUG=false

// packages/server/src/server.ts
import * as dotenv from 'dotenv';
dotenv.config({ path: `.env.${process.env.NODE_ENV}` });

const server = new ApolloServer({
  typeDefs,
  resolvers,
  introspection: process.env.GRAPHQL_INTROSPECTION === 'true',
  // Can be overridden per environment
});
```

```typescript
// Example: Graceful degradation for authorized introspection
// Allow introspection for authenticated admin users

import { ApolloServer } from '@apollo/server';

const server = new ApolloServer({
  typeDefs,
  resolvers,
  // Base setting: disabled in production
  introspection: process.env.NODE_ENV !== 'production',
  plugins: [
    {
      async requestDidStart({ request, contextValue }: any) {
        return {
          async didResolveOperation({ operation }: any) {
            const isIntrospection = operation?.selectionSet?.selections?.some(
              (selection: any) =>
                selection?.name?.value === '__schema' ||
                selection?.name?.value === '__type'
            );

            if (isIntrospection && process.env.NODE_ENV === 'production') {
              // Allow introspection for admin users only
              if (!contextValue?.user?.isAdmin) {
                throw new GraphQLError('Introspection is disabled', {
                  extensions: { code: 'FORBIDDEN' },
                });
              }
            }
          },
        };
      },
    },
  ],
});
```
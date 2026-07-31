---
title: Prefer Deprecation Over Versioned APIs
impact: HIGH
impactDescription: Enables continuous API evolution without breaking changes
tags: schema, deprecation, versioning, api-evolution, migration
---

## Prefer Deprecation Over Versioned APIs

**Impact: HIGH (Enables continuous API evolution without breaking changes)**

Prefer deprecation over versioned APIs in GraphQL schemas. Use the `@deprecated` directive to evolve APIs continuously instead of creating versioned endpoints or fields. GraphQL's introspection and strong typing make it uniquely suited for gradual API evolution without the versioning complexity required in REST APIs.

**Avoid Versioned Patterns:**
- **No versioned endpoints**: Don't create `/graphql/v1`, `/graphql/v2`
- **No versioned types**: Don't create `UserV1`, `UserV2`, `QueryV3`
- **No versioned fields**: Don't create `fullName_v1`, `fullName_v2`

**Use @deprecated Directive:**
- Add new fields alongside existing ones
- Mark old fields as deprecated with clear migration guidance
- Track usage to know when safe to remove
- Maintain single evolving schema

**Benefits of Deprecation:**
- **Smooth Migration**: Clients can migrate at their own pace
- **Single Schema**: No need to maintain multiple API versions
- **Clear Communication**: Introspection shows deprecated fields with reasons
- **Gradual Adoption**: New and old fields coexist during transition
- **Easier Maintenance**: One schema evolves instead of multiple versions
- **Better Tooling**: GraphQL tools show deprecation warnings

**When to Use Deprecation:**
- Renaming fields (add new, deprecate old)
- Changing field structure (add new format, deprecate old)
- Removing unnecessary fields
- Consolidating similar fields
- Evolving types (add new fields, deprecate old pattern)

**Migration Process:**
1. Add new field alongside deprecated field
2. Mark old field with `@deprecated` directive and migration guidance
3. Update server to support both fields
4. Monitor deprecated field usage
5. Give clients time to migrate
6. Remove deprecated field once usage is zero

**Incorrect (Versioning creates maintenance burden):**

```graphql
# packages/server/graphql/schema.graphql

# BAD: Versioned types create schema bloat
type UserV1 {
  id: ID!
  name: String!
  email: String!
}

type UserV2 {
  id: ID!
  firstName: String!
  lastName: String!
  email: String!
  phoneNumber: String
}

type UserV3 {
  id: ID!
  firstName: String!
  lastName: String!
  emailAddress: String!
  phoneNumber: String
  avatar: String
}

# BAD: Versioned fields clutter schema
type Product {
  id: ID!
  title_v1: String!
  title_v2: String!
  name_v3: String!
  price_v1: Float!
  price_v2: Money!
}

# BAD: Multiple query versions
type Query {
  getUserV1(id: ID!): UserV1
  getUserV2(id: ID!): UserV2
  getUserV3(id: ID!): UserV3

  getProductV1(id: ID!): ProductV1
  getProductV2(id: ID!): ProductV2
}

# BAD: Versioned mutations
type Mutation {
  createUserV1(input: CreateUserV1Input!): UserV1
  createUserV2(input: CreateUserV2Input!): UserV2

  updateProductV1(id: ID!, input: UpdateProductV1Input!): ProductV1
  updateProductV2(id: ID!, input: UpdateProductV2Input!): ProductV2
}

# Problems:
# - Schema grows exponentially with each version
# - Clients must know which version to use
# - Maintenance nightmare (bug fixes need to be applied to all versions)
# - No clear migration path
# - Difficult to sunset old versions
```

```typescript
// packages/server/src/routes/graphql-v1.ts
// BAD: Separate GraphQL endpoints for versions

import { ApolloServer } from '@apollo/server';
import { schemaV1 } from './schema-v1';

const serverV1 = new ApolloServer({ schema: schemaV1 });

// /graphql/v1 endpoint

// packages/server/src/routes/graphql-v2.ts
// BAD: Another endpoint for v2

import { ApolloServer } from '@apollo/server';
import { schemaV2 } from './schema-v2';

const serverV2 = new ApolloServer({ schema: schemaV2 });

// /graphql/v2 endpoint

// Problems:
// - Multiple servers to maintain
// - Must support all versions simultaneously
// - No clear deprecation path
// - Difficult to track client usage by version
```

**Correct (Deprecation enables smooth evolution):**

```graphql
# packages/server/graphql/schema.graphql

# GOOD: Single evolving type with deprecated fields
type User {
  id: ID!

  # Old field - deprecated with clear migration guidance
  name: String! @deprecated(reason: "Use firstName and lastName instead. Split on first space for migration.")

  # New fields added alongside deprecated one
  firstName: String!
  lastName: String!

  # Evolved email field
  email: String! @deprecated(reason: "Use emailAddress field instead")
  emailAddress: String!

  # New field added
  phoneNumber: String
  avatar: String
}

# GOOD: Product evolution without versioning
type Product {
  id: ID!

  # Old field deprecated
  title: String! @deprecated(reason: "Use name field instead")

  # New standardized field
  name: String!

  # Price evolution
  priceAmount: Float! @deprecated(reason: "Use price object for currency support")
  price: Money!

  # Complex type evolution
  details: String @deprecated(reason: "Use description and specifications fields")
  description: String!
  specifications: [ProductSpecification!]!
}

type Money {
  amount: Float!
  currency: String!
}

type ProductSpecification {
  key: String!
  value: String!
}

# GOOD: Single query endpoint that evolves
type Query {
  user(id: ID!): User
  product(id: ID!): Product

  # Old query with deprecation
  getUserByEmail(email: String!): User @deprecated(reason: "Use user(id:) instead")
}

# GOOD: Mutations evolve with input types
input CreateUserInput {
  # Support both old and new patterns during migration
  name: String @deprecated(reason: "Use firstName and lastName")
  firstName: String
  lastName: String
  emailAddress: String!
  phoneNumber: String
}

type Mutation {
  createUser(input: CreateUserInput!): CreateUserPayload!
  updateUser(id: ID!, input: UpdateUserInput!): UpdateUserPayload!
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
// GOOD: Support both deprecated and new fields during migration

export const userResolvers = {
  User: {
    // Deprecated field - still functional during migration
    name: (parent: User) => {
      // Provide deprecated field from new data structure
      return `${parent.firstName} ${parent.lastName}`;
    },

    // Deprecated email field
    email: (parent: User) => {
      return parent.emailAddress;
    },

    // New fields
    firstName: (parent: User) => parent.firstName,
    lastName: (parent: User) => parent.lastName,
    emailAddress: (parent: User) => parent.emailAddress,
  },

  Mutation: {
    createUser: async (
      parent: any,
      args: { input: CreateUserInput },
      context: { service: Service }
    ) => {
      const { input } = args;

      // Handle both old and new input patterns
      let firstName: string;
      let lastName: string;

      if (input.name) {
        // Old pattern - still supported
        const parts = input.name.split(' ');
        firstName = parts[0];
        lastName = parts.slice(1).join(' ') || parts[0];
      } else if (input.firstName && input.lastName) {
        // New pattern - preferred
        firstName = input.firstName;
        lastName = input.lastName;
      } else {
        throw new Error('Must provide either name or firstName/lastName');
      }

      const user = await context.service.createUser({
        firstName,
        lastName,
        emailAddress: input.emailAddress,
        phoneNumber: input.phoneNumber
      });

      return { user, errors: [] };
    }
  }
};
```

```typescript
// packages/server/src/deprecation/tracker.ts
// GOOD: Track deprecated field usage

export function trackDeprecatedFieldUsage(
  fieldPath: string,
  clientName: string,
  clientVersion: string
) {
  logger.warn('Deprecated field used', {
    field: fieldPath,
    client: { name: clientName, version: clientVersion },
    timestamp: new Date()
  });

  // Store in database for analysis
  db.deprecatedFieldUsage.create({
    fieldPath,
    clientName,
    clientVersion,
    usedAt: new Date()
  });
}

// Query to check if safe to remove:
// SELECT client_name, client_version, COUNT(*) as usage_count
// FROM deprecated_field_usage
// WHERE field_path = 'User.name'
// AND used_at > NOW() - INTERVAL '30 days'
// GROUP BY client_name, client_version
//
// If usage_count is 0 for all clients, safe to remove!
```

```typescript
// packages/server/src/plugins/deprecationPlugin.ts
// GOOD: Apollo plugin to track deprecations

import { ApolloServerPlugin } from '@apollo/server';

export const deprecationTrackingPlugin: ApolloServerPlugin = {
  async requestDidStart() {
    return {
      async executionDidStart(requestContext) {
        return {
          willResolveField({ info, contextValue }) {
            const deprecationReason = info.parentType
              .getFields()
              [info.fieldName]?.deprecationReason;

            if (deprecationReason) {
              const fieldPath = `${info.parentType.name}.${info.fieldName}`;

              trackDeprecatedFieldUsage(
                fieldPath,
                contextValue.clientName,
                contextValue.clientVersion
              );

              // Add deprecation header
              requestContext.response.http.headers.set(
                'X-GraphQL-Deprecation-Warning',
                `Field ${fieldPath} is deprecated: ${deprecationReason}`
              );
            }
          }
        };
      }
    };
  }
};

// Usage
const server = new ApolloServer({
  schema,
  plugins: [deprecationTrackingPlugin]
});
```

```graphql
# Example: Client introspection sees deprecations

query IntrospectionQuery {
  __type(name: "User") {
    fields {
      name
      isDeprecated
      deprecationReason
    }
  }
}

# Response shows:
# {
#   "name": "name",
#   "isDeprecated": true,
#   "deprecationReason": "Use firstName and lastName instead"
# }
# {
#   "name": "firstName",
#   "isDeprecated": false,
#   "deprecationReason": null
# }
```

```typescript
// Example: GraphQL tools show deprecation warnings

// Client using deprecated field gets warning in IDE
const query = gql`
  query GetUser($id: ID!) {
    user(id: $id) {
      id
      name  # ⚠️ Warning: Field 'name' is deprecated
            #    Use firstName and lastName instead
      email # ⚠️ Warning: Field 'email' is deprecated
            #    Use emailAddress field instead
    }
  }
`;

// Updated query with new fields
const query = gql`
  query GetUser($id: ID!) {
    user(id: $id) {
      id
      firstName
      lastName
      emailAddress
    }
  }
`;
```

```typescript
// Example: Gradual migration approach

// Phase 1: Add new fields, deprecate old (Week 1)
type User {
  name: String @deprecated(reason: "Use firstName and lastName")
  firstName: String!
  lastName: String!
}

// Phase 2: Monitor usage (Weeks 2-6)
// - Track which clients still use deprecated fields
// - Send notifications to teams
// - Provide migration guides

// Phase 3: Remove once usage is zero (Week 7+)
type User {
  # Removed: name field (no longer used)
  firstName: String!
  lastName: String!
}
```

```graphql
# Example: Complex type evolution

type Order {
  id: ID!

  # Old structure deprecated
  shippingAddress: String @deprecated(reason: "Use shippingDetails object")
  billingAddress: String @deprecated(reason: "Use billingDetails object")

  # New structured approach
  shippingDetails: Address!
  billingDetails: Address!

  # Old status field
  status: String @deprecated(reason: "Use orderStatus enum for type safety")

  # New enum field
  orderStatus: OrderStatus!
}

type Address {
  street: String!
  city: String!
  state: String!
  postalCode: String!
  country: String!
}

enum OrderStatus {
  PENDING
  PROCESSING
  SHIPPED
  DELIVERED
  CANCELLED
}
```

```typescript
// Example: Documentation and communication

/**
 * User type - represents a user account
 *
 * Migration Guide:
 * - Field 'name' is deprecated. Use 'firstName' and 'lastName' instead.
 *   Split existing 'name' values on first space for migration.
 *
 * - Field 'email' is deprecated. Use 'emailAddress' instead.
 *   These fields return the same value during transition period.
 *
 * Deprecation Timeline:
 * - 2024-01-15: New fields added, old fields deprecated
 * - 2024-03-15: Target date for removing deprecated fields
 *
 * Contact: api-team@example.com for migration assistance
 */
type User {
  id: ID!
  name: String @deprecated(reason: "Use firstName and lastName instead. See migration guide.")
  firstName: String!
  lastName: String!
  email: String @deprecated(reason: "Use emailAddress instead. See migration guide.")
  emailAddress: String!
}
```

```typescript
// Example: Automated deprecation reports

async function generateDeprecationReport() {
  const deprecatedFields = await db.deprecatedFieldUsage
    .groupBy(['fieldPath', 'clientName'])
    .where('usedAt', '>', new Date(Date.now() - 30 * 24 * 60 * 60 * 1000))
    .count();

  const report = {
    generatedAt: new Date(),
    summary: `${deprecatedFields.length} deprecated fields still in use`,
    fields: deprecatedFields.map(field => ({
      path: field.fieldPath,
      usageCount: field.count,
      clients: field.clientName
    }))
  };

  // Send to team
  await slack.send({
    channel: '#api-deprecations',
    message: `Deprecation Report: ${report.summary}`,
    attachments: [{ text: JSON.stringify(report.fields, null, 2) }]
  });

  return report;
}

// Run weekly
cron.schedule('0 9 * * 1', generateDeprecationReport);
```

```graphql
# Example: Breaking changes that still use deprecation

# Instead of immediate breaking change:
# OLD (removed immediately):
# type Product { price: Float! }
# NEW: type Product { price: Money! }

# Use deprecation period:
type Product {
  id: ID!

  # Keep old field working during migration
  price: Float! @deprecated(reason: "Use priceDetails for currency support. This returns amount in USD.")

  # New field with full currency support
  priceDetails: Money!
}

type Money {
  amount: Float!
  currency: String!
  formatted: String!
}

# Resolver provides both:
resolvers = {
  Product: {
    price: (product) => product.priceDetails.amount,
    priceDetails: (product) => product.priceDetails
  }
}
```

```typescript
// Example: Deprecation with feature flags

type Query {
  # Gradual rollout with feature flag
  user(id: ID!): User

  # Beta field for new feature
  userProfile(id: ID!): UserProfile @beta
}

# Once userProfile is stable, deprecate old field:
type Query {
  user(id: ID!): User @deprecated(reason: "Use userProfile instead for richer data")
  userProfile(id: ID!): UserProfile
}
```
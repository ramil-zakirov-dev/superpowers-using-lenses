---
title: Ban Arbitrary JSON Filter Scalars
impact: CRITICAL
impactDescription: Prevents NoSQL injection and unauthorized data access
tags: security, schema, nosql-injection, filters, input-validation
---

## Ban Arbitrary JSON Filter Scalars

**Impact: CRITICAL (Prevents NoSQL injection and unauthorized data access)**

Prevent NoSQL injection vulnerabilities by banning arbitrary JSON filter scalars and requiring explicit filter inputs in GraphQL schemas and resolvers. Using generic JSON, JSONObject, or Any scalars for filters allows attackers to inject malicious query operators that can bypass authorization, access unauthorized data, or perform destructive operations.

**Schema Requirements:**
- Replace `JSON`, `JSONObject`, `Any`, or custom scalars used as filters with typed input objects
- Use specific input types with explicit field definitions instead of generic scalar types
- Define allowed filter fields explicitly in GraphQL schema

**Resolver Security:**
- Never spread/merge filter arguments directly into database queries
- Map filter inputs to explicit database query operators
- Validate and sanitize all filter parameters before database operations
- Whitelist allowed filter fields and operators

**NoSQL Injection Risks:**
- Arbitrary JSON allows injection of MongoDB operators like `$where`, `$regex`, `$ne`
- Attackers can bypass authorization checks with crafted filters
- Can enable data exfiltration by querying unauthorized fields
- May allow destructive operations through database-specific operators

**Real-World Attack Example:**
```json
// Attacker sends this filter:
{
  "filter": {
    "$where": "this.password.length > 0",
    "role": { "$ne": "admin" }
  }
}
// This bypasses authentication and exposes all users
```

**Incorrect (Arbitrary JSON filters enable NoSQL injection):**

```graphql
# packages/server/graphql/schema.graphql
scalar JSON
scalar JSONObject
scalar Any

type User {
  id: ID!
  email: String!
  role: String!
  income: [Income!]!
}

type Income {
  id: ID!
  amount: Float!
  date: String!
}

type Query {
  # Dangerous: accepts arbitrary JSON as filter
  users(filter: JSON): [User!]!

  # Also dangerous: JSONObject scalar
  searchUsers(criteria: JSONObject): [User!]!

  # Dangerous: Any scalar
  findUsers(where: Any): [User!]!
}

type User {
  # Dangerous: arbitrary filter on nested field
  income(filter: JSON): [Income!]!
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
import { Service } from '../../service';

interface QueryResolvers {
  users: (parent: any, args: { filter: any }, context: { service: Service }) => Promise<User[]>;
  searchUsers: (parent: any, args: { criteria: any }, context: { service: Service }) => Promise<User[]>;
}

export const userResolvers: QueryResolvers = {
  // CRITICAL VULNERABILITY: spreading filter directly into query
  users: async (parent, args, { service }) => {
    return await service.db.collection("users").find({
      ...args.filter  // NoSQL injection vulnerability!
      // Attacker can inject: { "$where": "malicious code" }
    });
  },

  // Also vulnerable: direct pass-through to database
  searchUsers: async (parent, args, { service }) => {
    // No validation or sanitization
    return await service.db.collection("users").find(args.criteria);
  }
};

// Example of exploitable resolver
const incomeResolver = {
  income: async (parent: User, args: { filter: any }, { service }: any) => {
    // Vulnerable: attacker can inject operators
    return await service.db.collection("income").find({
      userId: parent.id,
      ...args.filter  // Injection point
    });
  }
};
```

```typescript
// Real-world exploitation example
// Attacker query:
const maliciousQuery = `
  query {
    users(filter: {
      "$ne": null,
      "$where": "this.role === 'admin'"
    }) {
      id
      email
      role
    }
  }
`;
// This bypasses authorization and returns all admin users
```

**Correct (Explicit typed filters prevent injection):**

```graphql
# packages/server/graphql/schema.graphql
input UserFilter {
  email: String
  role: String
  createdAfter: String
  createdBefore: String
  isActive: Boolean
}

input IncomeFilter {
  from: String!
  to: String
  minAmount: Float
  maxAmount: Float
  currency: String
}

input UserSearchCriteria {
  emailContains: String
  roleIn: [String!]
  registeredAfter: String
}

type User {
  id: ID!
  email: String!
  role: String!
  # Safe: explicit typed filter
  income(filter: IncomeFilter): [Income!]!
}

type Income {
  id: ID!
  amount: Float!
  date: String!
  currency: String!
}

type Query {
  # Safe: explicit typed filter with defined fields
  users(filter: UserFilter): [User!]!

  # Safe: specific input type
  searchUsers(criteria: UserSearchCriteria): [User!]!
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
import { Service } from '../../service';
import { users } from '../../db/schema';

interface UserFilter {
  email?: string;
  role?: string;
  createdAfter?: string;
  createdBefore?: string;
  isActive?: boolean;
}

interface UserSearchCriteria {
  emailContains?: string;
  roleIn?: string[];
  registeredAfter?: string;
}

interface QueryResolvers {
  users: (parent: any, args: { filter?: UserFilter }, context: { service: Service }) => Promise<User[]>;
  searchUsers: (parent: any, args: { criteria?: UserSearchCriteria }, context: { service: Service }) => Promise<User[]>;
}

export const userResolvers: QueryResolvers = {
  // Safe: explicit mapping of each filter field
  users: async (parent, args, { service }) => {
    const query: any = {};

    // Whitelist approach: only map known, safe fields
    if (args.filter?.email) {
      // Direct equality check - safe
      query.email = args.filter.email;
    }

    if (args.filter?.role) {
      // Direct equality check - safe
      query.role = args.filter.role;
    }

    if (args.filter?.createdAfter) {
      // Controlled operator usage
      query.createdAt = { $gte: new Date(args.filter.createdAfter) };
    }

    if (args.filter?.createdBefore) {
      // Explicitly merge with existing createdAt filter
      query.createdAt = {
        ...query.createdAt,
        $lte: new Date(args.filter.createdBefore)
      };
    }

    if (args.filter?.isActive !== undefined) {
      query.isActive = args.filter.isActive;
    }

    return await service.db.collection("users").find(query);
  },

  // Safe: controlled mapping with validation
  searchUsers: async (parent, args, { service }) => {
    const query: any = {};

    if (args.criteria?.emailContains) {
      // Use safe regex construction, escape user input
      const escapedEmail = args.criteria.emailContains.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      query.email = { $regex: escapedEmail, $options: 'i' };
    }

    if (args.criteria?.roleIn && args.criteria.roleIn.length > 0) {
      // Use $in operator with validated array
      query.role = { $in: args.criteria.roleIn };
    }

    if (args.criteria?.registeredAfter) {
      query.registeredAt = { $gte: new Date(args.criteria.registeredAfter) };
    }

    return await service.db.collection("users").find(query);
  }
};

// Safe nested resolver with explicit filter mapping
const incomeResolver = {
  income: async (
    parent: User,
    args: { filter?: IncomeFilter },
    { service }: { service: Service }
  ) => {
    const query: any = {
      userId: parent.id  // Always scope to parent user
    };

    // Explicit field mapping - no arbitrary operators
    if (args.filter?.from) {
      query.date = { $gte: args.filter.from };
    }

    if (args.filter?.to) {
      query.date = { ...query.date, $lte: args.filter.to };
    }

    if (args.filter?.minAmount !== undefined) {
      query.amount = { $gte: args.filter.minAmount };
    }

    if (args.filter?.maxAmount !== undefined) {
      query.amount = { ...query.amount, $lte: args.filter.maxAmount };
    }

    if (args.filter?.currency) {
      query.currency = args.filter.currency;
    }

    return await service.db.collection("income").find(query);
  }
};
```

```typescript
// Additional security layer: query builder with validation
class SafeQueryBuilder {
  private query: any = {};

  addFilter(field: string, value: any, operator: '$eq' | '$gte' | '$lte' | '$in' = '$eq') {
    // Whitelist allowed fields
    const allowedFields = ['email', 'role', 'createdAt', 'isActive'];
    if (!allowedFields.includes(field)) {
      throw new Error(`Field ${field} is not allowed in filters`);
    }

    // Whitelist allowed operators
    const allowedOperators = ['$eq', '$gte', '$lte', '$in'];
    if (!allowedOperators.includes(operator)) {
      throw new Error(`Operator ${operator} is not allowed`);
    }

    if (operator === '$eq') {
      this.query[field] = value;
    } else {
      this.query[field] = { ...this.query[field], [operator]: value };
    }

    return this;
  }

  build() {
    return this.query;
  }
}

// Usage in resolver
export const safeUserResolver = {
  users: async (parent: any, args: { filter?: UserFilter }, { service }: any) => {
    const builder = new SafeQueryBuilder();

    if (args.filter?.email) {
      builder.addFilter('email', args.filter.email);
    }
    if (args.filter?.role) {
      builder.addFilter('role', args.filter.role);
    }
    if (args.filter?.createdAfter) {
      builder.addFilter('createdAt', new Date(args.filter.createdAfter), '$gte');
    }

    return await service.db.collection("users").find(builder.build());
  }
};
```

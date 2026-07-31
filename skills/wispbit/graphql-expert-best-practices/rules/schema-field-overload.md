---
title: Avoid Field Overloads for Viewer vs User
impact: HIGH
impactDescription: Prevents security issues and improves API clarity
tags: schema, security, api-design, viewer, user
---

## Avoid Field Overloads for Viewer vs User

**Impact: HIGH (Prevents security issues and improves API clarity)**

GraphQL queries must not overload fields to mean both "current user" and "arbitrary user". Use separate fields for viewer and user lookups. Overloading fields creates ambiguity, increases the risk of accidentally exposing private data, and makes the API harder to understand and type correctly.

**Field Separation:**
- Use `viewer` field for current authenticated user
- Use `user(id: ID!)` field for arbitrary user lookups with required ID

**Type Structure:**
- Create separate types that implement a common `User` interface
- `Viewer` type for authenticated user with private fields
- `PublicUser` type for arbitrary users with public fields only

**Security Benefits:**
- Clear separation prevents accidentally exposing private fields to unauthorized users
- Type system enforces different field access patterns
- Required ID parameter prevents confusion about which user is being queried

**API Clarity:**
- Clients know exactly what they're querying (current user vs another user)
- Type definitions clearly show which fields are private vs public
- No need for runtime checks based on null/undefined parameters

**Incorrect (Overloaded field with ambiguous meaning):**

```graphql
# packages/server/graphql/schema.graphql
interface User {
  id: ID!
  username: String!
}

type UserImpl implements User {
  id: ID!
  username: String!
  email: String!
  privateSettings: String
  organizations: [Organization!]!
}

type Query {
  # Ambiguous: null ID returns viewer, provided ID returns arbitrary user
  user(id: ID): UserImpl

  # Also ambiguous pattern
  profile(userId: ID): UserImpl
}
```

```typescript
// packages/server/src/routes/resolvers/user.ts
export const userResolvers = {
  Query: {
    user: async (parent: any, args: { id?: string }, context: { userId: string, service: Service }) => {
      // Ambiguous logic: conditional behavior based on parameter
      if (!args.id) {
        // Returns current user with all private fields
        return await context.service.getUserById(context.userId);
      }
      // Returns arbitrary user with same type (security risk!)
      return await context.service.getUserById(args.id);
    }
  }
};
```

**Correct (Separate fields with clear types):**

```graphql
# packages/server/graphql/schema.graphql
interface User {
  id: ID!
  username: String!
}

type Viewer implements User {
  id: ID!
  username: String!
  email: String!
  privateSettings: String
  organizations: [Organization!]!
  isWispbitEmployee: Boolean!
  createdAt: Float!
}

type PublicUser implements User {
  id: ID!
  username: String!
  providerType: RepositoryProvider!
  # No private fields like email, privateSettings
}

type Query {
  # Clear separation: viewer for current user
  viewer: Viewer!

  # Required ID for arbitrary user lookups
  user(id: ID!): PublicUser

  # Alternative naming that's also clear
  currentUser: Viewer!
  profile(id: ID!): PublicUser
}
```

```typescript
// packages/server/src/routes/resolvers/user.ts
export const userResolvers = {
  Query: {
    viewer: async (parent: any, args: {}, context: { userId: string, service: Service }) => {
      // Always returns current authenticated user with private fields
      return await context.service.getViewerById(context.userId);
    },

    user: async (parent: any, args: { id: string }, context: { service: Service }) => {
      // Required ID parameter, returns only public fields
      return await context.service.getPublicUserById(args.id);
    }
  }
};
```
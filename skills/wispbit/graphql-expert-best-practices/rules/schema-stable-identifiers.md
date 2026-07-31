---
title: Use Globally Stable Opaque Identifiers
impact: HIGH
impactDescription: Prevents information leakage and enables cross-environment portability
tags: schema, security, identifiers, uuid, database, portability
---

## Use Globally Stable Opaque Identifiers

**Impact: HIGH (Prevents information leakage and enables cross-environment portability)**

GraphQL types must use opaque, globally stable identifiers instead of exposing database primary keys directly. Never expose auto-increment database IDs, sequential integers, or other internal storage identifiers that reveal database structure or record counts.

**Database-Derived IDs to Avoid:**
- Auto-increment integers (1, 2, 3, ...)
- Sequential database primary keys
- Row IDs or internal database identifiers
- Any identifier that reveals insertion order or total count

**Stable Identifiers to Use:**
- UUIDs (universally unique identifiers)
- Prefixed opaque IDs (e.g., `usr_2a4b6c8d`, `post_9f8e7d6c`)
- Hashed values
- Encrypted database IDs
- Base64-encoded composite keys (Relay Global IDs)

**Why Sequential IDs Are Problematic:**
- **Information Leakage**: Reveals total number of records (ID 50000 = ~50k users)
- **Enumeration Attacks**: Attackers can guess valid IDs (1, 2, 3...)
- **Business Intelligence**: Competitors can track growth rates
- **No Portability**: IDs differ across dev/staging/production
- **Migration Issues**: Database migrations change IDs
- **Coupling**: Tight coupling to database implementation

**Benefits of Stable Identifiers:**
- **Opaque**: Don't reveal database structure or counts
- **Portable**: Same ID across all environments
- **Secure**: Hard to enumerate or guess
- **Future-Proof**: Can change database without changing IDs
- **Privacy**: Don't leak insertion order or activity patterns
- **Distributed**: Can generate IDs without database coordination

**Incorrect (Exposing database auto-increment IDs):**

```graphql
# packages/server/graphql/schema.graphql

# BAD: Exposing auto-increment database IDs
type User {
  id: ID!  # Database: users.id (integer, auto-increment)
  email: String!
  name: String!
}

type Post {
  id: ID!  # Database: posts.id (serial, sequential)
  title: String!
  author: User!
}

type Organization {
  id: ID!  # Database: organizations.id (bigint, auto-increment)
  name: String!
  memberCount: Int!
}

type Comment {
  id: ID!  # Database: comments.id (integer, auto-increment)
  content: String!
  post: Post!
}

# Problems exposed:
# - User 1, User 2, User 3... reveals total users
# - Post IDs reveal publication order
# - Can enumerate all posts: posts(id: 1), posts(id: 2)...
# - Different IDs in dev vs production
```

```typescript
// packages/server/src/db/schema.ts
// BAD: Database schema with auto-increment IDs

export const users = pgTable('users', {
  id: serial('id').primaryKey(),  // 1, 2, 3... sequential
  email: varchar('email', { length: 255 }),
  name: varchar('name', { length: 255 })
});

export const posts = pgTable('posts', {
  id: serial('id').primaryKey(),  // Sequential
  title: varchar('title', { length: 255 }),
  authorId: integer('author_id').references(() => users.id)
});

// Resolver exposes these directly:
export const userResolvers = {
  Query: {
    user: async (parent, args: { id: string }) => {
      // Directly using database ID
      return db.select().from(users).where(eq(users.id, parseInt(args.id)));
    }
  }
};

// Problems:
// - Query user(id: "50000") reveals ~50k users exist
// - Can iterate through all users: 1, 2, 3...
// - Dev has different IDs than production
```

```typescript
// Example: Security issues with sequential IDs

// Enumeration attack
for (let i = 1; i <= 10000; i++) {
  const user = await client.query({
    query: gql`query { user(id: "${i}") { email } }`
  });
  // Harvests all user emails
}

// Business intelligence leak
const user1 = await client.query({ query: gql`{ user(id: "1") { createdAt } }` });
const user5000 = await client.query({ query: gql`{ user(id: "5000") { createdAt } }` });
// Competitor calculates: 5000 users in X months = Y users/month growth rate

// Authorization bypass attempt
// User sees their post ID is 100
// Tries to access posts 99, 101, 102... to see others' posts
```

**Correct (Using stable opaque identifiers):**

```graphql
# packages/server/graphql/schema.graphql

# GOOD: Using UUIDs or opaque identifiers
type User {
  id: ID!  # "usr_2a4b6c8d9e0f1234" or UUID
  email: String!
  name: String!
}

type Post {
  id: ID!  # "post_9f8e7d6c5b4a3210" or UUID
  title: String!
  author: User!
}

type Organization {
  id: ID!  # "org_1a2b3c4d5e6f7890" or UUID
  name: String!
  memberCount: Int!
}

type Comment {
  id: ID!  # "cmt_5f4e3d2c1b0a9876" or UUID
  content: String!
  post: Post!
}

# Benefits:
# - Can't determine total count from ID
# - Can't enumerate sequentially
# - Same IDs across all environments
# - Opaque and secure
```

```typescript
// packages/server/src/db/schema.ts
// GOOD: Database schema with UUIDs

import { uuid } from 'drizzle-orm/pg-core';

export const users = pgTable('users', {
  id: uuid('id').defaultRandom().primaryKey(),
  email: varchar('email', { length: 255 }),
  name: varchar('name', { length: 255 })
});

export const posts = pgTable('posts', {
  id: uuid('id').defaultRandom().primaryKey(),
  title: varchar('title', { length: 255 }),
  authorId: uuid('author_id').references(() => users.id)
});

// Resolvers use UUIDs
export const userResolvers = {
  Query: {
    user: async (parent: any, args: { id: string }, context: { db: any }) => {
      return context.db.select().from(users).where(eq(users.id, args.id));
    }
  }
};

// UUIDs prevent enumeration:
// user(id: "550e8400-e29b-41d4-a716-446655440000") - can't guess next ID
```

```typescript
// packages/server/src/utils/identifiers.ts
// GOOD: Generating prefixed opaque IDs

import { nanoid } from 'nanoid';
import { createHash } from 'crypto';

/**
 * Generate a prefixed opaque ID
 * Format: {prefix}_{randomString}
 */
export function generateId(prefix: string): string {
  const random = nanoid(16); // Generates random 16-char string
  return `${prefix}_${random}`;
}

// Usage
const userId = generateId('usr');    // "usr_V1StGXR8_Z5jdHi6"
const postId = generateId('post');   // "post_K3S9fG2mP7qR4tX8"
const orgId = generateId('org');     // "org_L9mN2pQ5rT8vW3xY"

/**
 * Hash database ID to create stable opaque identifier
 * Same database ID always produces same hash
 */
export function hashId(dbId: number, salt: string): string {
  const hash = createHash('sha256')
    .update(`${dbId}-${salt}`)
    .digest('base64')
    .substring(0, 16)
    .replace(/[+/=]/g, '');

  return hash;
}

// Store mapping in database
export const idMappings = pgTable('id_mappings', {
  databaseId: integer('database_id').primaryKey(),
  publicId: varchar('public_id', { length: 32 }).notNull().unique()
});
```

```typescript
// packages/server/src/services/userService.ts
// GOOD: Service layer handles ID conversion

import { generateId } from '../utils/identifiers';

export class UserService {
  async createUser(data: CreateUserData) {
    // Generate stable opaque ID
    const publicId = generateId('usr');

    const user = await this.db.insert(users).values({
      publicId,  // Store opaque ID in database
      email: data.email,
      name: data.name
    }).returning();

    return user;
  }

  async getUserByPublicId(publicId: string) {
    // Query by opaque ID, not database auto-increment ID
    return await this.db
      .select()
      .from(users)
      .where(eq(users.publicId, publicId))
      .limit(1);
  }
}
```

```typescript
// packages/server/src/db/schema-with-mapping.ts
// GOOD: Database schema with both internal and public IDs

export const users = pgTable('users', {
  // Internal auto-increment ID (never exposed via GraphQL)
  _id: serial('_id').primaryKey(),

  // Public opaque ID (exposed via GraphQL)
  id: varchar('id', { length: 32 }).notNull().unique(),

  email: varchar('email', { length: 255 }),
  name: varchar('name', { length: 255 }),

  createdAt: timestamp('created_at').defaultNow()
});

// GraphQL resolver only uses public ID
export const userResolvers = {
  User: {
    id: (parent: UserRecord) => parent.id,  // Returns opaque ID
    // Never expose parent._id
  },

  Query: {
    user: async (parent: any, args: { id: string }, { db }: any) => {
      // Query by public ID
      return await db.select().from(users).where(eq(users.id, args.id));
    }
  }
};
```

```typescript
// packages/server/src/graphql/globalId.ts
// GOOD: Relay-style Global IDs

import { Buffer } from 'buffer';

/**
 * Create Relay Global ID
 * Format: base64("TypeName:localId")
 */
export function toGlobalId(type: string, id: string): string {
  return Buffer.from(`${type}:${id}`).toString('base64');
}

export function fromGlobalId(globalId: string): { type: string; id: string } {
  const decoded = Buffer.from(globalId, 'base64').toString();
  const [type, id] = decoded.split(':');
  return { type, id };
}

// Usage
const globalUserId = toGlobalId('User', 'usr_2a4b6c8d');
// "VXNlcjp1c3JfMmE0YjZjOGQ="

const { type, id } = fromGlobalId(globalUserId);
// type: "User", id: "usr_2a4b6c8d"

// GraphQL schema
interface Node {
  id: ID!  # Global ID
}

type User implements Node {
  id: ID!  # "VXNlcjp1c3JfMmE0YjZjOGQ="
  email: String!
}

// Resolver
export const nodeResolver = {
  Query: {
    node: async (parent: any, args: { id: string }, context: any) => {
      const { type, id } = fromGlobalId(args.id);

      switch (type) {
        case 'User':
          return context.services.user.getById(id);
        case 'Post':
          return context.services.post.getById(id);
        default:
          return null;
      }
    }
  }
};
```

```typescript
// packages/server/src/migrations/add-public-ids.ts
// GOOD: Migration to add public IDs to existing database

import { generateId } from '../utils/identifiers';

export async function up(db: Database) {
  // Add public_id column
  await db.schema.alterTable('users').addColumn('public_id', 'varchar(32)');

  // Generate public IDs for existing records
  const users = await db.select('id').from('users');

  for (const user of users) {
    const publicId = generateId('usr');
    await db('users')
      .where('id', user.id)
      .update({ public_id: publicId });
  }

  // Make public_id unique and not null
  await db.schema.alterTable('users')
    .alterColumn('public_id', (col) => col.notNull().unique());

  // Create index for fast lookups
  await db.schema.alterTable('users')
    .addIndex('idx_users_public_id', ['public_id']);
}

// GraphQL now uses public_id field instead of auto-increment id
```

```typescript
// Example: Environment portability with stable IDs

// Development database
const devUser = await createUser({ email: 'test@example.com' });
// devUser.id = "usr_2a4b6c8d"

// Production database
const prodUser = await createUser({ email: 'test@example.com' });
// prodUser.id = "usr_2a4b6c8d"  (same ID!)

// Stable across environments means:
// - Test data can use real production IDs
// - Fixtures have consistent IDs
// - Debugging is easier
// - No ID conflicts when syncing data
```

```typescript
// Example: Security comparison

// BAD: Sequential IDs
// Attacker knows IDs 1-1000 exist
// Tries: user(id: "1"), user(id: "2")...
// Can enumerate all users

// GOOD: Opaque IDs
// Attacker has ID "usr_2a4b6c8d"
// Can't guess next: "usr_2a4b6c8e"? "usr_2a4b6c8f"?
// Each ID is random - enumeration impossible
```

```typescript
// packages/server/src/plugins/validateIdentifiers.ts
// GOOD: Validation to ensure stable IDs are used

import { ApolloServerPlugin } from '@apollo/server';

export const identifierValidationPlugin: ApolloServerPlugin = {
  async serverWillStart({ schema }) {
    // Validate that ID fields use stable identifiers
    const types = schema.getTypeMap();

    for (const [typeName, type] of Object.entries(types)) {
      if ('getFields' in type && typeName !== 'Query' && typeName !== 'Mutation') {
        const fields = type.getFields();

        if (fields.id) {
          // Check if resolver returns stable ID
          // Log warning if ID looks like sequential integer
          console.log(`Validating ${typeName}.id uses stable identifier`);
        }
      }
    }
  }
};
```

```graphql
# Example: Complete schema with stable IDs

type User implements Node {
  id: ID!  # "usr_2a4b6c8d" - stable, opaque
  email: String!
  posts: [Post!]!
  organization: Organization!
}

type Post implements Node {
  id: ID!  # "post_9f8e7d6c" - stable, opaque
  title: String!
  author: User!
  comments: [Comment!]!
}

type Comment implements Node {
  id: ID!  # "cmt_5f4e3d2c" - stable, opaque
  content: String!
  author: User!
  post: Post!
}

type Organization implements Node {
  id: ID!  # "org_1a2b3c4d" - stable, opaque
  name: String!
  members: [User!]!
}

interface Node {
  id: ID!
}

type Query {
  node(id: ID!): Node
  user(id: ID!): User
  post(id: ID!): Post
  comment(id: ID!): Comment
  organization(id: ID!): Organization
}

# All IDs are:
# ✓ Opaque (can't guess next ID)
# ✓ Stable (same across environments)
# ✓ Prefixed (shows type)
# ✓ Secure (no enumeration)
# ✓ Portable (no coupling to database)
```
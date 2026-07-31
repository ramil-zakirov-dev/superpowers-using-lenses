---
title: Prevent Duplicate Fields Through Nested Objects
impact: MEDIUM
impactDescription: Reduces schema bloat and maintains single source of truth
tags: schema, design, duplication, normalization, best-practices
---

## Prevent Duplicate Fields Through Nested Objects

**Impact: MEDIUM (Reduces schema bloat and maintains single source of truth)**

GraphQL types must not contain duplicate fields that are already accessible through nested object fields. When a type includes a nested object field, avoid adding separate fields for properties that are already available through that nested object. This maintains a single source of truth and prevents schema bloat.

**Field Duplication Patterns to Avoid:**
- Adding `entityId: ID!` when `entity: Entity!` exists and `Entity` has an `id` field
- Adding `entityName: String` when `entity: Entity!` exists and `Entity` has a `name` field
- Adding `entitySlug: String` when `entity: Entity!` exists and `Entity` has a `slug` field
- Adding `entityPropertyName` when `entity: Entity!` exists and `Entity` has a `propertyName` field
- Any field that duplicates a property accessible through a nested object relationship

**Problems with Duplicate Fields:**
- **Schema Bloat**: Unnecessarily large schema with redundant fields
- **Maintenance Burden**: Must update multiple fields when data changes
- **Inconsistency Risk**: Duplicate fields can become out of sync
- **Confusion**: Unclear which field is the source of truth
- **Breaking Changes**: Harder to refactor without breaking multiple fields
- **Query Inefficiency**: Clients may query both fields unnecessarily

**Exceptions (Denormalization for Performance):**
- Explicitly denormalized fields for performance optimization
- Historical data that may differ from current nested object (e.g., product name at time of order)
- Fields required to avoid additional database queries in specific use cases
- Must be clearly documented why denormalization is necessary

**Incorrect (Duplicate fields through nested objects):**

```graphql
# graphql/schema.graphql
type Item {
  id: ID!
  name: String!
  versionId: ID!
}

type Organization {
  id: ID!
  name: String!
  slug: String!
}

type Repository {
  id: ID!
  name: String!
  slug: String!
}

type ItemDraftedActivity {
  organization: Organization!
  repository: Repository!
  item: Item!
  # BAD: Duplicates - all accessible through nested objects
  itemId: ID!           # Duplicate of item.id
  itemName: String!     # Duplicate of item.name
  repositoryId: ID!     # Duplicate of repository.id
  repositorySlug: String!  # Duplicate of repository.slug
  author: Author!
  createdAt: Float!
}

type User {
  id: ID!
  name: String!
  email: String!
}

type Organization {
  id: ID!
  name: String!
  slug: String!
}

type Project {
  id: ID!
  title: String!
  description: String!
  user: User!
  # BAD: Duplicates accessible through user field
  userId: ID!           # Duplicate of user.id
  userName: String!     # Duplicate of user.name
  organization: Organization!
  # BAD: Duplicates accessible through organization field
  organizationId: ID!   # Duplicate of organization.id
  organizationName: String!  # Duplicate of organization.name
  organizationSlug: String!  # Duplicate of organization.slug
}

type Comment {
  id: ID!
  content: String!
  author: User!
  # BAD: Duplicates
  authorId: ID!         # Duplicate of author.id
  authorName: String!   # Duplicate of author.name
  post: Post!
  postId: ID!          # Duplicate of post.id
  createdAt: Float!
}

type Team {
  id: ID!
  name: String!
  owner: User!
  # BAD: Duplicate
  ownerId: ID!         # Duplicate of owner.id
  members: [User!]!
}
```

```typescript
// src/resolvers/activityResolver.ts
// BAD: Must maintain consistency between duplicate fields

export const activityResolvers = {
  ItemDraftedActivity: {
    item: async (parent: any, args: any, context: { service: Service }) => {
      return await context.service.getItemById(parent.itemId);
    },

    // Resolver must ensure itemId matches item.id
    itemId: (parent: any) => parent.itemId,

    // Resolver must ensure itemName matches item.name
    itemName: async (parent: any, context: { service: Service }) => {
      const item = await context.service.getItemById(parent.itemId);
      return item.name;  // Extra query to get duplicate data
    }
  }
};

// Problem: What if item.name changes but itemName isn't updated?
```

```typescript
// Example: Maintenance nightmare with duplicates

// Service layer must keep fields in sync
class ActivityService {
  async createItemDraftedActivity(data: CreateActivityInput) {
    const item = await this.getItemById(data.itemId);
    const repository = await this.getRepositoryById(data.repositoryId);

    return await this.db.activities.create({
      itemId: item.id,           // Original
      itemName: item.name,       // Duplicate
      repositoryId: repository.id,      // Original
      repositorySlug: repository.slug,  // Duplicate
      // Must manually sync all duplicate fields
      // Easy to forget or get out of sync
    });
  }

  async updateItem(itemId: string, updates: ItemUpdates) {
    await this.db.items.update({ where: { id: itemId }, data: updates });

    // BUG: Forgot to update itemName in all activities!
    // Now activities have stale itemName values
  }
}
```

**Correct (Access fields through nested objects):**

```graphql
# graphql/schema.graphql
type Item {
  id: ID!
  name: String!
  versionId: ID!
}

type Organization {
  id: ID!
  name: String!
  slug: String!
}

type Repository {
  id: ID!
  name: String!
  slug: String!
}

# GOOD: No duplicate fields - all accessible through nested objects
type ItemDraftedActivity {
  organization: Organization!
  repository: Repository!
  item: Item!
  author: Author!
  source: CreateItemSource!
  createdAt: Float!
  # No itemId, itemName, repositoryId, repositorySlug
  # Access via: item.id, item.name, repository.id, repository.slug
}

type User {
  id: ID!
  name: String!
  email: String!
}

type Organization {
  id: ID!
  name: String!
  slug: String!
}

# GOOD: No duplicate fields
type Project {
  id: ID!
  title: String!
  description: String!
  user: User!
  organization: Organization!
  # No userId, userName, organizationId, etc.
  # Access via: user.id, user.name, organization.id, organization.name
}

type Post {
  id: ID!
  title: String!
  content: String!
}

# GOOD: Clean design without duplicates
type Comment {
  id: ID!
  content: String!
  author: User!
  post: Post!
  # No authorId, authorName, postId
  # Access via: author.id, author.name, post.id
  createdAt: Float!
}

type Team {
  id: ID!
  name: String!
  owner: User!
  members: [User!]!
  # No ownerId - access via owner.id
}
```

```typescript
// src/resolvers/activityResolver.ts
// GOOD: Simple resolvers, no duplication to maintain

export const activityResolvers = {
  ItemDraftedActivity: {
    item: async (parent: any, args: any, context: { service: Service }) => {
      return await context.service.getItemById(parent.itemId);
    },

    repository: async (parent: any, args: any, context: { service: Service }) => {
      return await context.service.getRepositoryById(parent.repositoryId);
    },

    organization: async (parent: any, args: any, context: { service: Service }) => {
      return await context.service.getOrganizationById(parent.organizationId);
    }

    // No duplicate field resolvers needed
    // Clients query: item { id name }, repository { id slug }
  }
};
```

```typescript
// Example: Clean client queries

// GOOD: Access nested object properties directly
const query = gql`
  query GetActivity($id: ID!) {
    activity(id: $id) {
      id
      createdAt
      item {
        id
        name
      }
      repository {
        id
        slug
      }
      organization {
        id
        name
      }
    }
  }
`;

// Clear and maintainable - single source of truth
```

```typescript
// Example: Service layer simplified

class ActivityService {
  async createItemDraftedActivity(data: CreateActivityInput) {
    // Store only foreign keys
    return await this.db.activities.create({
      itemId: data.itemId,
      repositoryId: data.repositoryId,
      organizationId: data.organizationId,
      authorId: data.authorId,
      createdAt: new Date()
      // No duplicate fields to maintain
    });
  }

  async updateItem(itemId: string, updates: ItemUpdates) {
    await this.db.items.update({ where: { id: itemId }, data: updates });
    // No need to update activities - they reference item by ID
    // GraphQL resolvers fetch current item data automatically
  }
}
```

```graphql
# Example: Exception - Explicit denormalization for historical data

type Product {
  id: ID!
  name: String!
  price: Float!
  description: String!
}

type OrderItem {
  id: ID!
  quantity: Int!

  # Current product reference
  product: Product!

  # Denormalized fields for historical accuracy
  # These capture product state at time of order
  # Documented as intentional denormalization
  productName: String!  # Product name when ordered (may differ from current)
  unitPrice: Float!     # Price when ordered (may differ from current)

  # Rationale: Product details can change after order is placed
  # Need to preserve what customer actually ordered and paid
}

type Invoice {
  id: ID!
  customer: User!

  # Denormalized for compliance/audit
  customerName: String!    # Name at time of invoice
  billingAddress: String!  # Address at time of invoice

  # Rationale: Legal requirement to preserve exact invoice details
  # Cannot change if customer updates profile
}
```

```graphql
# Example: Complex nested access is fine

type Activity {
  id: ID!
  item: Item!
  # Don't add itemAuthorName - access via item.author.name
  # Don't add itemRepositoryId - access via item.repository.id
  createdAt: Float!
}

type Item {
  id: ID!
  name: String!
  author: User!
  repository: Repository!
}

# Client query:
query GetActivity {
  activity(id: "123") {
    item {
      author {
        name  # Access deeply nested fields
      }
      repository {
        id    # No need for duplicate fields
      }
    }
  }
}
```

```typescript
// Example: Using DataLoader with nested objects (no duplicates needed)

export const activityResolvers = {
  ItemDraftedActivity: {
    item: async (parent: any, args: any, context: { loaders: any }) => {
      // DataLoader batches and caches
      return await context.loaders.itemById.load(parent.itemId);
    },

    repository: async (parent: any, args: any, context: { loaders: any }) => {
      return await context.loaders.repositoryById.load(parent.repositoryId);
    }
  },

  Item: {
    author: async (parent: any, args: any, context: { loaders: any }) => {
      // Nested resolvers work efficiently with DataLoader
      return await context.loaders.userById.load(parent.authorId);
    }
  }
};

// Client can query deeply without performance issues:
// activity { item { author { name } } }
// No need for activity.itemAuthorName duplicate field
```

```graphql
# Example: When you might think you need duplicates (but don't)

type PullRequest {
  id: ID!
  title: String!
  author: User!
  # DON'T add: authorLogin, authorName, authorId
  # Just query: author { id login name }

  repository: Repository!
  # DON'T add: repositoryName, repositoryOwner, repositorySlug
  # Just query: repository { name owner { login } slug }

  assignees: [User!]!
  # DON'T add: assigneeIds, assigneeNames
  # Just query: assignees { id name }
}

# Client can get all needed data:
query GetPullRequest($id: ID!) {
  pullRequest(id: $id) {
    title
    author { id login name }
    repository {
      name
      owner { login }
      slug
    }
    assignees { id name }
  }
}
```

```typescript
// Example: Database schema vs GraphQL schema

// Database - stores foreign keys
interface ActivityRecord {
  id: string;
  itemId: string;        // FK to items table
  repositoryId: string;  // FK to repositories table
  organizationId: string; // FK to organizations table
  createdAt: Date;
}

// GraphQL - exposes nested objects, not IDs
type ItemDraftedActivity {
  id: ID!
  item: Item!           # Resolved via itemId FK
  repository: Repository!  # Resolved via repositoryId FK
  organization: Organization!  # Resolved via organizationId FK
  createdAt: Float!
  # No itemId, repositoryId, organizationId exposed in GraphQL
}

// Resolver bridges the two:
export const activityResolvers = {
  ItemDraftedActivity: {
    item: (parent: ActivityRecord, args: any, { loaders }: any) => {
      return loaders.itemById.load(parent.itemId);
    }
  }
};
```

```graphql
# Example: Bad pattern - redundant parent ID in child

type User {
  id: ID!
  name: String!
  posts: [Post!]!
}

# BAD
type Post {
  id: ID!
  title: String!
  author: User!
  authorId: ID!  # Duplicate - accessible via author.id
}

# GOOD
type Post {
  id: ID!
  title: String!
  author: User!
  # No authorId - query author.id if needed
}
```

Reference: [GraphQL Best Practices - Schema Design](https://graphql.org/learn/best-practices/) | [GraphQL Schema Design Guide](https://www.apollographql.com/docs/apollo-server/schema/schema/)

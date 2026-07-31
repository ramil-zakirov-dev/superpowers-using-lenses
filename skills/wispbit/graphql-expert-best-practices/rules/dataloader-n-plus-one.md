---
title: Use DataLoader to Prevent N+1 Queries
impact: CRITICAL
impactDescription: Prevents exponential query growth in nested GraphQL resolvers
tags: performance, dataloader, n+1, batching, graphql
---

## Use DataLoader to Prevent N+1 Queries

**Impact: CRITICAL (Prevents exponential query growth in nested GraphQL resolvers)**

Use DataLoader to prevent N+1 queries when GraphQL resolvers or query execution code repeatedly fetches related objects. N+1 queries occur when a resolver fetches data individually for each parent object instead of batching requests, causing severe performance degradation as the number of objects grows.

**When to Use DataLoader:**
- Resolver functions that make individual database/API calls for related objects (users, organizations, products)
- Query execution patterns that perform separate lookups for individual records instead of batch operations
- Nested field resolvers that trigger database queries inside loops or for each parent object
- Any GraphQL query handling code that exhibits N+1 query patterns

**When DataLoader May Not Help:**
- Data can be fetched efficiently in a single query with SQL JOINs or equivalent batch operations
- Backend already provides batch APIs and is called only once per request
- Simple top-level queries without nested relationships
- Direct database queries that don't involve GraphQL resolution

**Implementation Requirements:**
- Create one loader per entity/key pattern (userById, commentsByPostId, etc.)
- Initialize loaders per request in GraphQL context or query execution context
- Batch function must return results in exact key order
- Return null or appropriate default for missing keys
- Consider clearing/priming loaders after mutations

**Incorrect (N+1 query - individual fetches for each parent):**

```typescript
// src/resolvers/user.ts
import { Service } from '@/services';

interface User {
  id: string;
  name: string;
  organizationId: string;
}

interface Organization {
  id: string;
  name: string;
}

// N+1 query - fetching organization individually for each user
export const userResolvers = {
  User: {
    organization: async (parent: User, args: any, context: { service: Service }) => {
      // This will be called for each user, causing N+1 queries
      return await context.service.getOrganizationById(parent.organizationId);
    }
  },
  Query: {
    users: async (parent: any, args: any, context: { service: Service }) => {
      return await context.service.getUsers();
    }
  }
};

// src/resolvers/post.ts
import { Service } from '@/services';

interface Post {
  id: string;
  authorId: string;
  content: string;
}

// Multiple N+1 patterns in nested resolvers
export const postResolvers = {
  Post: {
    author: async (parent: Post, args: any, context: { service: Service }) => {
      // N+1: Individual user lookup for each post
      return await context.service.getUserById(parent.authorId);
    },
    comments: async (parent: Post, args: any, context: { service: Service }) => {
      // N+1: Individual comment lookup for each post
      return await context.service.getCommentsByPostId(parent.id);
    }
  }
};
```

**Correct (DataLoader batches requests automatically):**

```typescript
// src/resolvers/user.ts
import DataLoader from 'dataloader';
import { Service } from '@/services';

interface User {
  id: string;
  name: string;
  organizationId: string;
}

interface Organization {
  id: string;
  name: string;
}

// Create DataLoader for batching organization queries
const createOrganizationLoader = (service: Service) => 
  new DataLoader<string, Organization | null>(async (organizationIds: readonly string[]) => {
    const organizations = await service.getOrganizationsByIds([...organizationIds]);
    const organizationMap = new Map(organizations.map(org => [org.id, org]));
    
    // Return results in exact key order
    return organizationIds.map(id => organizationMap.get(id) || null);
  });

export const userResolvers = {
  User: {
    organization: async (parent: User, args: any, context: { service: Service, loaders: any }) => {
      // Use DataLoader to batch organization requests
      return await context.loaders.organizationById.load(parent.organizationId);
    }
  },
  Query: {
    users: async (parent: any, args: any, context: { service: Service }) => {
      return await context.service.getUsers();
    }
  }
};

// src/resolvers/post.ts
import DataLoader from 'dataloader';
import { Service } from '@/services';

interface Post {
  id: string;
  authorId: string;
  content: string;
}

// Create DataLoaders for batching related data
const createUserLoader = (service: Service) =>
  new DataLoader<string, User | null>(async (userIds: readonly string[]) => {
    const users = await service.getUsersByIds([...userIds]);
    const userMap = new Map(users.map(user => [user.id, user]));
    return userIds.map(id => userMap.get(id) || null);
  });

const createCommentsLoader = (service: Service) =>
  new DataLoader<string, Comment[]>(async (postIds: readonly string[]) => {
    const comments = await service.getCommentsByPostIds([...postIds]);
    const commentMap = new Map<string, Comment[]>();
    
    // Group comments by postId
    comments.forEach(comment => {
      if (!commentMap.has(comment.postId)) {
        commentMap.set(comment.postId, []);
      }
      commentMap.get(comment.postId)!.push(comment);
    });
    
    return postIds.map(id => commentMap.get(id) || []);
  });

export const postResolvers = {
  Post: {
    author: async (parent: Post, args: any, context: { loaders: any }) => {
      return await context.loaders.userById.load(parent.authorId);
    },
    comments: async (parent: Post, args: any, context: { loaders: any }) => {
      return await context.loaders.commentsByPostId.load(parent.id);
    }
  }
};
```

Reference: [DataLoader GitHub](https://github.com/graphql/dataloader)

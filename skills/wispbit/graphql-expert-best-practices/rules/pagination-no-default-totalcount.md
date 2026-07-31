---
title: Avoid Default totalCount in Connections
impact: HIGH
impactDescription: Prevents performance degradation and maintains API flexibility
tags: pagination, performance, connections, relay, scalability
---

## Avoid Default totalCount in Connections

**Impact: HIGH (Prevents performance degradation and maintains API flexibility)**

GraphQL connection types should not include `totalCount` as a required field by default. Only expose `totalCount` when it's known to be cheap to compute or explicitly required. Counting large collections can become a major performance bottleneck, and once included in the API, it's nearly impossible to remove without breaking changes.

**Performance Considerations:**
- Counting large collections can be slow and expensive (especially with filters or joins)
- Database COUNT queries don't scale well with large datasets
- Once `totalCount` is in the API, clients depend on it and it's very hard to remove
- Teams often can't guarantee count operations remain cheap and stable over time
- Every paginated query incurs the count penalty, even if clients don't use it

**When to Include totalCount:**
- Only on selective connections where counting is guaranteed to be cheap (small, bounded collections)
- When explicitly required by business logic (shopping cart items, notifications)
- Consider making it nullable (`Int` instead of `Int!`) to allow for future flexibility
- Provide as a separate query/field when needed, not as default connection field

**API Evolution:**
- Adding `totalCount` later is a non-breaking change
- Removing or nullifying `totalCount` is a breaking change
- Start without it, add only when proven necessary

**Alternative Patterns:**
- Use `hasNextPage`/`hasPreviousPage` for infinite scroll (no count needed)
- Provide approximate counts when exact count is expensive
- Offer separate count queries that can be cached or approximated
- Use cursor-based pagination without total count

**Incorrect (totalCount required by default):**

```graphql
# packages/server/graphql/schema.graphql
type ProductEdge {
  cursor: String!
  node: Product!
}

type ProductConnection {
  edges: [ProductEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!        # Required everywhere by default - performance trap
}

type UserEdge {
  cursor: String!
  node: User!
}

type UserConnection {
  edges: [UserEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!        # Will become expensive as user base grows
}

type OrderEdge {
  cursor: String!
  node: Order!
}

type OrderConnection {
  edges: [OrderEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!        # Expensive for large order datasets with filters
}

type CommentEdge {
  cursor: String!
  node: Comment!
}

type CommentConnection {
  edges: [CommentEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!        # Scales poorly with millions of comments
}

type Query {
  products(
    first: Int
    after: String
    category: String
  ): ProductConnection!

  users(first: Int, after: String): UserConnection!

  orders(
    first: Int
    after: String
    status: String
    customerId: ID
  ): OrderConnection!
}
```

```typescript
// packages/server/src/routes/resolvers/productResolver.ts
import { Service } from '../../service';

interface ProductConnectionArgs {
  first?: number;
  after?: string;
  category?: string;
}

export const productResolvers = {
  Query: {
    products: async (
      parent: any,
      args: ProductConnectionArgs,
      context: { service: Service }
    ) => {
      const limit = args.first || 10;
      const cursor = args.after;

      // Fetch page of products
      const products = await context.service.getProducts({
        limit: limit + 1,
        cursor,
        category: args.category
      });

      // BAD: Expensive COUNT query on every request
      // This can take seconds on large tables, especially with filters
      const totalCount = await context.service.db
        .collection('products')
        .countDocuments(args.category ? { category: args.category } : {});

      const hasNextPage = products.length > limit;
      const edges = products.slice(0, limit).map(product => ({
        cursor: product.id,
        node: product
      }));

      return {
        edges,
        pageInfo: {
          hasNextPage,
          endCursor: edges[edges.length - 1]?.cursor
        },
        totalCount // Always computed, even if client doesn't request it
      };
    }
  }
};
```

```typescript
// Example: Complex filtered query with expensive count
export const orderResolvers = {
  Query: {
    orders: async (
      parent: any,
      args: { first?: number; after?: string; status?: string; customerId?: string },
      context: { service: Service }
    ) => {
      const filters: any = {};
      if (args.status) filters.status = args.status;
      if (args.customerId) filters.customerId = args.customerId;

      // Fetch paginated data
      const orders = await context.service.getOrders({
        limit: (args.first || 10) + 1,
        cursor: args.after,
        filters
      });

      // BAD: COUNT with complex filters can be very slow
      // May require full table scan if filters aren't indexed properly
      const totalCount = await context.service.db
        .collection('orders')
        .countDocuments(filters);

      return {
        edges: orders.slice(0, args.first || 10).map(order => ({
          cursor: order.id,
          node: order
        })),
        pageInfo: {
          hasNextPage: orders.length > (args.first || 10)
        },
        totalCount
      };
    }
  }
};
```

**Correct (Omit or make totalCount optional):**

```graphql
# packages/server/graphql/schema.graphql
type ProductEdge {
  cursor: String!
  node: Product!
}

type ProductConnection {
  edges: [ProductEdge!]!
  pageInfo: PageInfo!
  # No totalCount - avoid by default for large collections
}

type UserEdge {
  cursor: String!
  node: User!
}

type UserConnection {
  edges: [UserEdge!]!
  pageInfo: PageInfo!
  totalCount: Int         # Nullable - allows flexibility, can return null if expensive
}

type OrderEdge {
  cursor: String!
  node: Order!
}

type OrderConnection {
  edges: [OrderEdge!]!
  pageInfo: PageInfo!
  # No totalCount - too expensive with filters
}

type CategoryEdge {
  cursor: String!
  node: Category!
}

type CategoryConnection {
  edges: [CategoryEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!        # OK - categories are small, stable, and bounded
}

type CartItemEdge {
  cursor: String!
  node: CartItem!
}

type CartItemConnection {
  edges: [CartItemEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!        # OK - cart items are always small (user-scoped)
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}

type Query {
  # Pagination without totalCount
  products(
    first: Int
    after: String
    category: String
  ): ProductConnection!

  # Separate explicit count query (can be cached, approximated, or rate-limited)
  productCount(category: String): Int!

  # Approximate count for large datasets
  approximateProductCount(category: String): Int!

  users(first: Int, after: String): UserConnection!

  orders(
    first: Int
    after: String
    status: String
    customerId: ID
  ): OrderConnection!

  # Small, bounded collection - totalCount is fine
  categories(first: Int, after: String): CategoryConnection!

  # User-scoped small collection - totalCount is fine
  cartItems(cartId: ID!, first: Int, after: String): CartItemConnection!
}
```

```typescript
// packages/server/src/routes/resolvers/productResolver.ts
import { Service } from '../../service';

interface ProductConnectionArgs {
  first?: number;
  after?: string;
  category?: string;
}

export const productResolvers = {
  Query: {
    // GOOD: No totalCount in connection - fast pagination
    products: async (
      parent: any,
      args: ProductConnectionArgs,
      context: { service: Service }
    ) => {
      const limit = args.first || 10;
      const cursor = args.after;

      // Fetch one extra to check for next page
      const products = await context.service.getProducts({
        limit: limit + 1,
        cursor,
        category: args.category
      });

      const hasNextPage = products.length > limit;
      const edges = products.slice(0, limit).map(product => ({
        cursor: product.id,
        node: product
      }));

      return {
        edges,
        pageInfo: {
          hasNextPage,
          hasPreviousPage: !!cursor,
          startCursor: edges[0]?.cursor,
          endCursor: edges[edges.length - 1]?.cursor
        }
        // No totalCount - fast and efficient
      };
    },

    // GOOD: Separate count query that can be optimized independently
    productCount: async (
      parent: any,
      args: { category?: string },
      context: { service: Service }
    ) => {
      // Can implement caching strategy
      const cacheKey = `product_count:${args.category || 'all'}`;
      const cached = await context.service.cache.get(cacheKey);
      if (cached) return cached;

      const count = await context.service.db
        .collection('products')
        .countDocuments(args.category ? { category: args.category } : {});

      // Cache for 5 minutes
      await context.service.cache.set(cacheKey, count, 300);
      return count;
    },

    // GOOD: Approximate count for very large datasets
    approximateProductCount: async (
      parent: any,
      args: { category?: string },
      context: { service: Service }
    ) => {
      // Use database statistics for fast approximate count
      // MongoDB: estimatedDocumentCount or $collStats
      // PostgreSQL: pg_class.reltuples
      const stats = await context.service.db
        .collection('products')
        .estimatedDocumentCount();

      return Math.floor(stats);
    }
  }
};
```

```typescript
// Example: User connection with optional totalCount
export const userResolvers = {
  Query: {
    users: async (
      parent: any,
      args: { first?: number; after?: string },
      context: { service: Service }
    ) => {
      const limit = args.first || 10;

      const users = await context.service.getUsers({
        limit: limit + 1,
        cursor: args.after
      });

      const edges = users.slice(0, limit).map(user => ({
        cursor: user.id,
        node: user
      }));

      return {
        edges,
        pageInfo: {
          hasNextPage: users.length > limit,
          hasPreviousPage: !!args.after,
          startCursor: edges[0]?.cursor,
          endCursor: edges[edges.length - 1]?.cursor
        }
        // totalCount is nullable - resolver can return it or omit it
        // Don't compute it unless specifically requested via field selection
      };
    }
  },

  UserConnection: {
    // GOOD: Lazy resolver - only computes if requested
    totalCount: async (
      parent: any,
      args: any,
      context: { service: Service },
      info: any
    ) => {
      // Check if field was actually requested
      // Only compute if client explicitly asks for it
      try {
        const cached = await context.service.cache.get('user_count');
        if (cached) return cached;

        const count = await context.service.db.collection('users').countDocuments();

        await context.service.cache.set('user_count', count, 300);
        return count;
      } catch (error) {
        // If count fails or times out, return null (since field is nullable)
        console.error('Failed to get user count:', error);
        return null;
      }
    }
  }
};
```

```typescript
// Example: Small bounded collection - totalCount is fine
export const categoryResolvers = {
  Query: {
    // GOOD: Categories are small and stable - totalCount is acceptable
    categories: async (
      parent: any,
      args: { first?: number; after?: string },
      context: { service: Service }
    ) => {
      const limit = args.first || 10;

      const categories = await context.service.getCategories({
        limit: limit + 1,
        cursor: args.after
      });

      // OK: Category count is always small (< 100 categories)
      const totalCount = await context.service.db
        .collection('categories')
        .countDocuments();

      const edges = categories.slice(0, limit).map(category => ({
        cursor: category.id,
        node: category
      }));

      return {
        edges,
        pageInfo: {
          hasNextPage: categories.length > limit,
          hasPreviousPage: !!args.after,
          startCursor: edges[0]?.cursor,
          endCursor: edges[edges.length - 1]?.cursor
        },
        totalCount // OK because categories collection is small and bounded
      };
    }
  }
};
```

```typescript
// Example: User-scoped collection - totalCount is fine
export const cartResolvers = {
  Query: {
    // GOOD: Cart items are user-scoped and small - totalCount is fine
    cartItems: async (
      parent: any,
      args: { cartId: string; first?: number; after?: string },
      context: { service: Service; userId: string }
    ) => {
      const cart = await context.service.getCart(args.cartId);

      // Authorization check
      if (cart.userId !== context.userId) {
        throw new Error('Unauthorized');
      }

      const limit = args.first || 10;

      const items = await context.service.getCartItems({
        cartId: args.cartId,
        limit: limit + 1,
        cursor: args.after
      });

      // OK: Cart items are always small (user-scoped, typically < 50 items)
      const totalCount = await context.service.db
        .collection('cart_items')
        .countDocuments({ cartId: args.cartId });

      const edges = items.slice(0, limit).map(item => ({
        cursor: item.id,
        node: item
      }));

      return {
        edges,
        pageInfo: {
          hasNextPage: items.length > limit,
          hasPreviousPage: !!args.after,
          startCursor: edges[0]?.cursor,
          endCursor: edges[edges.length - 1]?.cursor
        },
        totalCount // OK because cart items are user-scoped and small
      };
    }
  }
};
```

Reference: [GraphQL Pagination Best Practices](https://graphql.org/learn/pagination/)

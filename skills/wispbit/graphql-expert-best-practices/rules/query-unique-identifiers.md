---
title: Use Unique Identifiers Over Composite Parameters
impact: MEDIUM
impactDescription: Simplifies API surface and reduces coupling
tags: query, parameters, api-design, identifiers, simplicity
---

## Use Unique Identifiers Over Composite Parameters

**Impact: MEDIUM (Simplifies API surface and reduces coupling)**

When querying for a specific entity, prefer using the entity's unique identifier over composite parameters. Instead of requiring clients to know parent entity relationships and provide multiple parameters, expose entities through globally unique identifiers that can be used directly.

**Parameter Design:**
- Use a single unique identifier parameter for entity lookups
- Avoid composite parameters that require knowledge of parent entity relationships
- Reserve multi-parameter queries for list/search operations, not single entity lookups

**Benefits:**
- **Simplifies API Surface**: Fewer parameters to understand and provide
- **Reduces Coupling**: Clients don't need to know entity relationships to query
- **Improves Portability**: Entity IDs can be passed around without context
- **Better Caching**: Single ID-based queries are easier to cache
- **Aligns with Best Practices**: Similar to REST where `/resource/{id}` is standard
- **Easier Refactoring**: Changing parent relationships doesn't affect queries

**When Composite Parameters Are Acceptable:**
- List/search queries with filters (e.g., `users(organizationId: ID!, role: String)`)
- When fetching resources scoped to a parent (e.g., `storeMembers(storeId: ID!)`)
- When natural keys are truly composite and domain-specific

**Global ID Pattern:**
- Use globally unique IDs (UUIDs, Relay Global IDs, etc.)
- Each entity has a unique identifier across the entire system
- Avoids namespace collisions and simplifies queries

**Incorrect (Composite parameters for single entity queries):**

```graphql
# graphql/schema.graphql
type Query {
  # BAD: Requires knowledge of parent structure
  order(storeId: ID!, orderNumber: Int!): Order

  # BAD: Complex nested parameter requirements
  lineItem(
    storeId: ID!
    orderId: ID!
    lineNumber: Int!
  ): LineItem

  # BAD: Multiple parent entity dependencies
  comment(
    orderId: ID!
    threadId: ID!
    commentIndex: Int!
  ): Comment

  # BAD: Requires understanding of store + branch structure
  asset(
    storeId: ID!
    branchName: String!
    assetPath: String!
  ): Asset

  # BAD: Deep hierarchical parameters
  assessment(
    organizationId: ID!
    storeId: ID!
    orderId: ID!
  ): Assessment

  # BAD: Composite key for single entity
  userRole(
    organizationId: ID!
    userId: ID!
  ): UserRole
}

type Order {
  id: ID!
  number: Int!
  storeId: ID!
  title: String!
}

type LineItem {
  number: Int!
  orderId: ID!
  storeId: ID!
  description: String!
}
```

```typescript
// resolvers/orderResolver.ts
export const orderResolvers = {
  Query: {
    // BAD: Client must know both storeId and order number
    order: async (
      parent: any,
      args: { storeId: string; orderNumber: number },
      context: { service: Service }
    ) => {
      // Client burden: must track store context
      return await context.service.getOrderByNumber(
        args.storeId,
        args.orderNumber
      );
    },

    // BAD: Three parameters required for single entity lookup
    lineItem: async (
      parent: any,
      args: {
        storeId: string;
        orderId: string;
        lineNumber: number;
      },
      context: { service: Service }
    ) => {
      // Complex query requiring deep knowledge of entity relationships
      return await context.service.getLineItem(
        args.storeId,
        args.orderId,
        args.lineNumber
      );
    }
  }
};
```

```typescript
// Example: Client code complexity with composite parameters
// BAD: Client must maintain context

// Client needs to track store context for order lookup
const store = await getStore();
const order = await client.query({
  query: GET_ORDER,
  variables: {
    storeId: store.id,     // Must provide parent ID
    orderNumber: 42        // Plus entity identifier
  }
});

// Worse: Deep nesting requires tracking multiple parents
const lineItem = await client.query({
  query: GET_LINE_ITEM,
  variables: {
    storeId: store.id,
    orderId: order.id,
    lineNumber: 5
  }
});

// Problem: Can't easily pass order reference without store context
function displayOrder(storeId: string, orderNumber: number) {
  // Both pieces needed just to query
  return getOrder(storeId, orderNumber);
}
```

**Correct (Unique identifiers for single entity queries):**

```graphql
# graphql/schema.graphql
type Query {
  # GOOD: Simple unique identifier access
  order(orderId: ID!): Order

  # GOOD: Single ID for single entity
  lineItem(lineItemId: ID!): LineItem

  # GOOD: Globally unique comment ID
  comment(commentId: ID!): Comment

  # GOOD: Direct entity access
  store(id: ID!): Store
  user(id: ID!): User
  assessment(assessmentId: ID!): Assessment

  # GOOD: List queries can use filters (this is acceptable)
  orders(
    storeId: ID!
    status: OrderStatus
    limit: Int
  ): [Order!]!

  # GOOD: Scoped list query with parent filter
  lineItems(
    storeId: ID!
    resolved: Boolean
    limit: Int
  ): [LineItem!]!

  # GOOD: Search/filter operations with multiple parameters
  users(
    organizationId: ID!
    role: String
    search: String
    limit: Int
  ): [User!]!

  # GOOD: Asset lookup by unique asset ID
  asset(assetId: ID!): Asset

  # GOOD: Alternative - asset tree browsing uses composite params
  assetsInDirectory(
    storeId: ID!
    path: String!
  ): [Asset!]!
}

type Order {
  id: ID!  # Globally unique
  number: Int!
  store: Store!
  title: String!
  lineItems: [LineItem!]!
}

type LineItem {
  id: ID!  # Globally unique
  number: Int!
  order: Order!
  description: String!
}

type Comment {
  id: ID!  # Globally unique
  content: String!
  author: User!
  thread: CommentThread!
}

type Asset {
  id: ID!  # Globally unique
  path: String!
  store: Store!
  content: String!
}
```

```typescript
// resolvers/orderResolver.ts
import { Service } from '../service';

export const orderResolvers = {
  Query: {
    // GOOD: Simple single parameter lookup
    order: async (
      parent: any,
      args: { orderId: string },
      context: { service: Service }
    ) => {
      // Clean, simple lookup by unique ID
      return await context.service.getOrderById(args.orderId);
    },

    // GOOD: Single ID for line item lookup
    lineItem: async (
      parent: any,
      args: { lineItemId: string },
      context: { service: Service }
    ) => {
      // No need for parent IDs - line item ID is globally unique
      return await context.service.getLineItemById(args.lineItemId);
    },

    // GOOD: List query with store filter
    orders: async (
      parent: any,
      args: {
        storeId: string;
        status?: string;
        limit?: number;
      },
      context: { service: Service }
    ) => {
      // List queries can use parent ID as filter
      return await context.service.getOrders({
        storeId: args.storeId,
        status: args.status,
        limit: args.limit || 20
      });
    },

    // GOOD: Comment by unique ID
    comment: async (
      parent: any,
      args: { commentId: string },
      context: { service: Service }
    ) => {
      return await context.service.getCommentById(args.commentId);
    }
  },

  Order: {
    // Nested resolvers handle relationships
    store: async (
      parent: Order,
      args: any,
      context: { service: Service }
    ) => {
      return await context.service.getStoreById(parent.storeId);
    },

    lineItems: async (
      parent: Order,
      args: any,
      context: { service: Service }
    ) => {
      return await context.service.getLineItemsByOrderId(parent.id);
    }
  }
};
```

```typescript
// Example: Simplified client code with unique IDs
// GOOD: Clean, simple queries

// Can query order with just its ID - no parent context needed
const order = await client.query({
  query: GET_ORDER,
  variables: {
    orderId: 'ord_abc123'  // Just the order ID
  }
});

// Can share order ID easily
const orderId = 'ord_abc123';
shareOrder(orderId);  // Simple to pass around

// Line item lookup is equally simple
const lineItem = await client.query({
  query: GET_LINE_ITEM,
  variables: {
    lineItemId: 'item_xyz789'  // Just the line item ID
  }
});

// Functions accept simple IDs
function displayOrder(orderId: string) {
  return getOrder(orderId);  // Clean interface
}

// Can construct URLs easily
const orderUrl = `/orders/${order.id}`;  // No parent context needed
```

```typescript
// Example: Database schema with globally unique IDs
// Good practice: Use UUIDs or composite global IDs

interface Order {
  id: string;  // UUID or encoded global ID
  number: number;  // Display number (not used for queries)
  storeId: string;
  title: string;
}

// Service implementation
class OrderService {
  async getOrderById(id: string): Promise<Order> {
    // Direct lookup by unique ID
    return await this.db.orders.findUnique({
      where: { id }
    });
  }

  // List query uses store as filter
  async getOrders(filters: {
    storeId: string;
    status?: string;
    limit: number;
  }): Promise<Order[]> {
    return await this.db.orders.findMany({
      where: {
        storeId: filters.storeId,
        status: filters.status
      },
      take: filters.limit
    });
  }
}
```

```typescript
// Example: Relay-style Global IDs
// Encode entity type and ID into globally unique identifier

function toGlobalId(type: string, id: string): string {
  return Buffer.from(`${type}:${id}`).toString('base64');
}

function fromGlobalId(globalId: string): { type: string; id: string } {
  const decoded = Buffer.from(globalId, 'base64').toString();
  const [type, id] = decoded.split(':');
  return { type, id };
}

// Usage in resolver
export const nodeResolver = {
  Query: {
    // GOOD: Universal node interface
    node: async (
      parent: any,
      args: { id: string },
      context: { service: Service }
    ) => {
      const { type, id } = fromGlobalId(args.id);

      switch (type) {
        case 'Order':
          return await context.service.getOrderById(id);
        case 'LineItem':
          return await context.service.getLineItemById(id);
        case 'Comment':
          return await context.service.getCommentById(id);
        default:
          throw new Error('Unknown type');
      }
    }
  }
};

// Schema with node interface
interface Node {
  id: ID!
}

type Order implements Node {
  id: ID!  # Relay Global ID: base64("Order:123")
  number: Int!
  title: String!
}

type Query {
  node(id: ID!): Node
  order(id: ID!): Order
}
```

```typescript
// Example: Maintaining backward compatibility
// Provide both new (simple) and legacy (composite) fields

type Query {
  # New simplified API
  order(orderId: ID!): Order

  # Legacy API for backward compatibility (deprecated)
  orderByNumber(
    storeId: ID!
    number: Int!
  ): Order @deprecated(reason: "Use order(orderId) instead")
}

// Resolver can handle both
export const orderResolvers = {
  Query: {
    order: async (
      parent: any,
      args: { orderId: string },
      context: { service: Service }
    ) => {
      return await context.service.getOrderById(args.orderId);
    },

    orderByNumber: async (
      parent: any,
      args: { storeId: string; number: number },
      context: { service: Service }
    ) => {
      // Legacy support
      return await context.service.getOrderByNumber(
        args.storeId,
        args.number
      );
    }
  }
};
```
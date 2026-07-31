---
title: Use Structured Types Over Unstructured Strings
impact: HIGH
impactDescription: Improves type safety, validation, and API discoverability
tags: schema, types, enums, type-safety, validation, json
---

## Use Structured Types Over Unstructured Strings

**Impact: HIGH (Improves type safety, validation, and API discoverability)**

Use structured GraphQL types instead of unstructured String or JSON fields when a known schema exists. String and JSON fields hide structure from clients, bypass GraphQL's type system, and make validation difficult. Structured types provide compile-time safety, better documentation, and clearer APIs.

**Avoid String Fields for Structured Data:**
- Replace String fields that contain JSON-encoded data with proper GraphQL types
- Replace String fields that represent enumerable values with GraphQL enums
- Replace String fields with known structure with object types

**Avoid JSON Scalar for Business Domain Data:**
- Replace JSON scalars used for business domain data with structured types
- JSON scalars should only be used for truly dynamic, schemaless data

**Use Enums for Finite Value Sets:**
- Replace String fields that represent a finite set of values with GraphQL enums
- Enums provide type safety and prevent invalid values

**Benefits of Structured Types:**
- **Type Safety**: Clients get compile-time validation
- **Discoverability**: Introspection shows available fields and values
- **Validation**: GraphQL validates structure automatically
- **Documentation**: Self-documenting schema
- **Refactoring**: Easier to evolve with breaking change detection
- **Tooling**: Better IDE autocomplete and error checking

**Problems with Unstructured Data:**
- **No Validation**: Any string value is accepted
- **Runtime Errors**: Malformed JSON or invalid values cause runtime failures
- **Poor Documentation**: Clients must guess structure
- **No Type Safety**: Client codegen produces generic types
- **Hard to Query**: Can't select specific nested fields
- **Schema Evolution**: Can't track changes to structure

**Incorrect (Unstructured String and JSON fields):**

```graphql
# packages/server/graphql/schema.graphql
scalar JSON

type Product {
  id: ID!
  name: String!

  # BAD: String field for enumerable values
  type: String!  # "apparel", "food", "toys" - no type safety

  # BAD: JSON scalar for structured data
  metaAttributes: JSON!  # { color: "red", size: "M" } - structure hidden

  # BAD: String field containing JSON-encoded data
  specifications: String!  # "[{\"name\":\"Weight\",\"value\":\"1kg\"}]"

  # BAD: String for status
  status: String!  # "active", "discontinued" - no validation
}

type User {
  id: ID!
  name: String!

  # BAD: JSON encoded string with list of tags
  tags: String!  # "[\"premium\",\"beta-tester\"]"

  # BAD: String field for status values
  status: String!  # "active", "inactive", "suspended"

  # BAD: JSON for settings
  preferences: JSON!  # { theme: "dark", language: "en" }
}

type Order {
  id: ID!

  # BAD: JSON scalar for address data
  shippingAddress: JSON!  # { street: "123 Main", city: "NYC" }

  # BAD: String field for payment method
  paymentMethod: String!  # "credit_card", "paypal"

  # BAD: JSON for items
  items: JSON!  # [{ productId: "123", quantity: 2 }]
}

type Activity {
  id: ID!
  type: String!

  # BAD: JSON for activity-specific data
  metadata: JSON!  # Different structure per activity type
}
```

```typescript
// packages/server/src/routes/resolvers/productResolver.ts
// BAD: Manual JSON parsing and validation

export const productResolvers = {
  Query: {
    product: async (parent: any, args: { id: string }, context: { service: Service }) => {
      const product = await context.service.getProduct(args.id);

      // Manual JSON parsing - error-prone
      return {
        ...product,
        specifications: JSON.stringify(product.specifications)
      };
    }
  },

  Mutation: {
    createProduct: async (
      parent: any,
      args: { input: any },
      context: { service: Service }
    ) => {
      // Manual validation of string/JSON fields
      if (!['apparel', 'food', 'toys', 'electronics'].includes(args.input.type)) {
        throw new Error('Invalid product type');
      }

      // Parse and validate JSON
      let specifications;
      try {
        specifications = JSON.parse(args.input.specifications);
      } catch {
        throw new Error('Invalid specifications JSON');
      }

      // Validate JSON structure manually
      if (!Array.isArray(specifications)) {
        throw new Error('Specifications must be an array');
      }

      return await context.service.createProduct(args.input);
    }
  }
};
```

```typescript
// Example: Client confusion with unstructured types

// What values are valid for type?
const product = await client.mutate({
  mutation: CREATE_PRODUCT,
  variables: {
    input: {
      name: 'Widget',
      type: 'gadget',  // Is this valid? No way to know!
      metaAttributes: {  // What fields can I include?
        color: 'red',
        size: 'M',
        unknownField: 'value'  // Will this be accepted?
      }
    }
  }
});

// Runtime errors instead of compile-time errors
```

**Correct (Structured types with proper schemas):**

```graphql
# packages/server/graphql/schema.graphql

# GOOD: Enum for finite value sets
enum ProductType {
  APPAREL
  FOOD
  TOYS
  ELECTRONICS
}

enum ProductStatus {
  ACTIVE
  DISCONTINUED
  OUT_OF_STOCK
}

# GOOD: Structured type for attributes
type ProductMetaAttribute {
  key: String!
  value: String!
  displayName: String
}

# GOOD: Structured type for specifications
type ProductSpecification {
  name: String!
  value: String!
  unit: String
  order: Int
}

type Product {
  id: ID!
  name: String!

  # GOOD: Type-safe enum
  type: ProductType!

  # GOOD: Structured list of attributes
  metaAttributes: [ProductMetaAttribute!]!

  # GOOD: Structured list of specifications
  specifications: [ProductSpecification!]!

  # GOOD: Enum for status
  status: ProductStatus!
}

# GOOD: Enum for user status
enum UserStatus {
  ACTIVE
  INACTIVE
  SUSPENDED
  DELETED
}

# GOOD: Structured user tag type
type UserTag {
  id: ID!
  name: String!
  category: String
  color: String
}

# GOOD: Structured preferences type
type UserPreferences {
  theme: Theme!
  language: String!
  timezone: String!
  emailNotifications: Boolean!
}

enum Theme {
  LIGHT
  DARK
  AUTO
}

type User {
  id: ID!
  name: String!

  # GOOD: List of structured tag objects
  tags: [UserTag!]!

  # GOOD: Enum for status
  status: UserStatus!

  # GOOD: Structured preferences
  preferences: UserPreferences!
}

# GOOD: Structured address type
type Address {
  street: String!
  city: String!
  state: String!
  zipCode: String!
  country: String!
  apartment: String
}

# GOOD: Enum for payment methods
enum PaymentMethod {
  CREDIT_CARD
  DEBIT_CARD
  PAYPAL
  BANK_TRANSFER
  APPLE_PAY
  GOOGLE_PAY
}

# GOOD: Structured order item type
type OrderItem {
  id: ID!
  product: Product!
  quantity: Int!
  unitPrice: Float!
}

type Order {
  id: ID!

  # GOOD: Structured address object
  shippingAddress: Address!

  # GOOD: Enum for payment method
  paymentMethod: PaymentMethod!

  # GOOD: List of structured items
  items: [OrderItem!]!
}

# GOOD: Union types for polymorphic data
union ActivityMetadata =
  | PostCreatedMetadata
  | UserFollowedMetadata
  | CommentLikedMetadata

type PostCreatedMetadata {
  postId: ID!
  title: String!
}

type UserFollowedMetadata {
  followedUserId: ID!
  followedUserName: String!
}

type CommentLikedMetadata {
  commentId: ID!
  postId: ID!
}

type Activity {
  id: ID!
  type: ActivityType!
  # GOOD: Union type instead of JSON
  metadata: ActivityMetadata!
  createdAt: Float!
}

enum ActivityType {
  POST_CREATED
  USER_FOLLOWED
  COMMENT_LIKED
}
```

```typescript
// packages/server/src/routes/resolvers/productResolver.ts
// GOOD: Type-safe resolvers with structured types

interface CreateProductInput {
  name: string;
  type: ProductType;
  metaAttributes: ProductMetaAttribute[];
  specifications: ProductSpecification[];
  status: ProductStatus;
}

enum ProductType {
  APPAREL = 'APPAREL',
  FOOD = 'FOOD',
  TOYS = 'TOYS',
  ELECTRONICS = 'ELECTRONICS'
}

interface ProductMetaAttribute {
  key: string;
  value: string;
  displayName?: string;
}

interface ProductSpecification {
  name: string;
  value: string;
  unit?: string;
  order?: number;
}

export const productResolvers = {
  Mutation: {
    createProduct: async (
      parent: any,
      args: { input: CreateProductInput },
      context: { service: Service }
    ) => {
      // No manual validation needed - type system guarantees structure
      const { name, type, metaAttributes, specifications } = args.input;

      // Type is guaranteed to be valid enum value
      // metaAttributes is guaranteed to be an array of proper objects
      // specifications is guaranteed to have correct structure

      return await context.service.createProduct({
        name,
        type,
        metaAttributes,
        specifications
      });
    }
  }
};
```

```typescript
// Example: Type-safe client code with structured types

// GOOD: TypeScript knows exact structure
const product = await client.mutate({
  mutation: CREATE_PRODUCT,
  variables: {
    input: {
      name: 'Widget',
      type: ProductType.Electronics,  // Enum - type error for invalid value
      metaAttributes: [
        {
          key: 'color',
          value: 'red',
          displayName: 'Color'
          // Type error if structure is wrong
        }
      ],
      specifications: [
        {
          name: 'Weight',
          value: '1',
          unit: 'kg'
          // Type error if missing required fields
        }
      ]
    }
  }
});

// Client can query nested fields
const query = gql`
  query GetProduct($id: ID!) {
    product(id: $id) {
      type
      metaAttributes {
        key
        value
        displayName
      }
      specifications {
        name
        value
        unit
      }
    }
  }
`;
```

```graphql
# Example: When JSON scalar is acceptable

scalar JSON

type Feature {
  id: ID!
  name: String!

  # OK: Truly dynamic configuration with no fixed schema
  runtimeConfig: JSON

  # OK: User-defined arbitrary metadata
  customMetadata: JSON
}

type IntegrationWebhook {
  id: ID!
  url: String!

  # OK: Arbitrary webhook headers (user-defined)
  headers: JSON
}

# Rule: Only use JSON when:
# - Structure is truly dynamic
# - User-defined with no constraints
# - Cannot be modeled with GraphQL types
```

```typescript
// Example: Migrating from unstructured to structured

// Phase 1: Add structured fields alongside old JSON field
type Product {
  metadata: JSON @deprecated(reason: "Use metaAttributes field")
  metaAttributes: [ProductMetaAttribute!]!
}

// Phase 2: Resolvers support both
resolvers = {
  Product: {
    metadata: (product) => {
      // Convert structured to JSON for backward compatibility
      return product.metaAttributes.reduce((acc, attr) => {
        acc[attr.key] = attr.value;
        return acc;
      }, {});
    },
    metaAttributes: (product) => product.metaAttributes
  }
}

// Phase 3: Remove deprecated field once migration complete
type Product {
  metaAttributes: [ProductMetaAttribute!]!
}
```

```graphql
# Example: Rich type definitions

# BAD: Storing JSON
type Notification {
  message: String!
  data: JSON  # What's in here? No way to know
}

# GOOD: Union types for different notification types
union NotificationData =
  | CommentNotificationData
  | FollowNotificationData
  | MentionNotificationData

type CommentNotificationData {
  commentId: ID!
  postId: ID!
  commenterName: String!
  excerpt: String!
}

type FollowNotificationData {
  followerId: ID!
  followerName: String!
  followerAvatar: String
}

type MentionNotificationData {
  mentionerId: ID!
  mentionerName: String!
  postId: ID!
  excerpt: String!
}

type Notification {
  id: ID!
  type: NotificationType!
  message: String!
  data: NotificationData!  # Structured union type
  createdAt: Float!
}

enum NotificationType {
  COMMENT
  FOLLOW
  MENTION
}

# Client can query specific fields:
query {
  notifications {
    ... on CommentNotificationData {
      commentId
      postId
      excerpt
    }
    ... on FollowNotificationData {
      followerId
      followerName
    }
  }
}
```

```typescript
// Example: Complex nested structures

// BAD: Nested JSON
type Report {
  id: ID!
  data: JSON  # Complex nested report data
}

// GOOD: Structured types
type Report {
  id: ID!
  summary: ReportSummary!
  sections: [ReportSection!]!
  charts: [ReportChart!]!
  generatedAt: Float!
}

type ReportSummary {
  title: String!
  description: String
  totalRecords: Int!
  dateRange: DateRange!
}

type DateRange {
  start: String!
  end: String!
}

type ReportSection {
  id: ID!
  title: String!
  content: String!
  metrics: [ReportMetric!]!
  order: Int!
}

type ReportMetric {
  name: String!
  value: Float!
  unit: String
  trend: TrendDirection
}

enum TrendDirection {
  UP
  DOWN
  STABLE
}

type ReportChart {
  id: ID!
  type: ChartType!
  title: String!
  data: ChartData!
}

enum ChartType {
  LINE
  BAR
  PIE
  SCATTER
}

type ChartData {
  labels: [String!]!
  datasets: [ChartDataset!]!
}

type ChartDataset {
  label: String!
  values: [Float!]!
  color: String
}
```

```typescript
// Example: Input validation with structured types

// BAD: Manual validation of JSON string
createProduct({
  specifications: "[{\"name\":\"Weight\",\"value\":\"1kg\"}]"
})
// Resolver must parse, validate structure, handle errors

// GOOD: Type system validates structure
createProduct({
  specifications: [
    {
      name: "Weight",
      value: "1",
      unit: "kg"
    }
  ]
})
// GraphQL validates structure automatically
// TypeScript provides autocomplete
// Runtime errors are impossible for structure
```
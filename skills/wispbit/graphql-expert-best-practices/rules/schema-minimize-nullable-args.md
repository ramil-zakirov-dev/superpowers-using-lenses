---
title: Minimize Nullable Arguments
impact: MEDIUM
impactDescription: Improves API clarity and prevents ambiguous behavior
tags: schema, api-design, nullable, arguments, type-safety
---

## Minimize Nullable Arguments

**Impact: MEDIUM (Improves API clarity and prevents ambiguous behavior)**

Minimize nullable arguments in GraphQL input fields and query/mutation arguments. Use non-null arguments where possible and create separate, specific fields rather than overloaded fields with multiple nullable parameters. Excessive nullable arguments create ambiguous behavior, complicate validation logic, and make it unclear which combinations of arguments are valid.

**Query and Mutation Arguments:**
- Avoid multiple nullable arguments that create ambiguous behavior
- Create separate fields with non-null arguments for each specific use case
- Each field should have a clear, singular purpose

**Input Field Design:**
- Design focused input types with non-null fields rather than "kitchen sink" input types
- Split large input types with many nullable fields into specific, focused inputs
- Each input type should represent a single, clear action

**Default Values:**
- When nullable arguments are necessary, provide meaningful default values
- Use enum types with defaults to make behavior transparent
- Document why nullable fields exist and how they should be used

**Benefits of Non-Null Arguments:**
- **Clarity**: Clear which arguments are required vs optional
- **Validation**: Type system enforces required fields at compile time
- **Documentation**: Self-documenting API (no need to guess which fields are needed)
- **Error Prevention**: Catches missing required data before execution
- **Client Type Safety**: Better TypeScript/Flow type generation

**Problems with Excessive Nullability:**
- Ambiguous which combinations of arguments are valid
- Complex validation logic in resolvers
- Unclear error messages when wrong combination is provided
- Difficult to understand API intent
- Leads to runtime errors instead of type errors

**Incorrect (Multiple nullable arguments create ambiguity):**

```graphql
# packages/server/graphql/schema.graphql
type Query {
  # BAD: Multiple nullable arguments - which one should client provide?
  user(id: ID, username: String, email: String): User

  # BAD: Unclear which arguments are needed together
  posts(
    userId: ID
    categoryId: ID
    tag: String
    search: String
    authorName: String
  ): [Post!]!

  # BAD: Kitchen sink input with many nullable fields
  searchProducts(input: ProductSearchInput): ProductConnection!
}

input ProductSearchInput {
  query: String
  category: String
  minPrice: Float
  maxPrice: Float
  brand: String
  rating: Float
  inStock: Boolean
  tags: [String!]
  # Unclear which combination of fields is valid
}

input UpdateUserInput {
  id: ID!
  name: String
  email: String
  phone: String
  address: String
  bio: String
  avatar: String
  preferences: UserPreferencesInput
  settings: UserSettingsInput
  # Too many nullable fields - unclear what's being updated
}

type Mutation {
  # BAD: Ambiguous nullable arguments
  createPost(title: String, content: String, categoryId: ID): CreatePostPayload!

  # BAD: Overloaded mutation with nullable fields
  updateProfile(
    userId: ID!
    name: String
    bio: String
    avatar: String
    website: String
    location: String
  ): UpdateProfilePayload!

  # BAD: Complex nullable parameter combinations
  inviteUser(
    email: String
    userId: ID
    teamId: ID
    role: String
  ): InviteUserPayload!
}

type Subscription {
  # BAD: Multiple ways to filter, unclear precedence
  commentAdded(postId: ID, userId: ID, tag: String): Comment!
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
export const userResolvers = {
  Query: {
    // BAD: Complex conditional logic to handle multiple nullable arguments
    user: async (
      parent: any,
      args: { id?: string; username?: string; email?: string },
      context: { service: Service }
    ) => {
      // Which one takes precedence? Unclear API contract
      if (args.id) {
        return await context.service.getUserById(args.id);
      } else if (args.username) {
        return await context.service.getUserByUsername(args.username);
      } else if (args.email) {
        return await context.service.getUserByEmail(args.email);
      } else {
        // What if none are provided? Runtime error instead of type error
        throw new Error('Must provide id, username, or email');
      }
    },

    // BAD: Unclear which argument combinations are valid
    posts: async (
      parent: any,
      args: {
        userId?: string;
        categoryId?: string;
        tag?: string;
        search?: string;
        authorName?: string;
      },
      context: { service: Service }
    ) => {
      // Complex conditional logic
      if (args.userId && args.authorName) {
        throw new Error('Cannot specify both userId and authorName');
      }

      if (!args.userId && !args.categoryId && !args.tag && !args.search && !args.authorName) {
        throw new Error('Must provide at least one filter');
      }

      // More complex filtering logic...
      const filters: any = {};
      if (args.userId) filters.userId = args.userId;
      if (args.categoryId) filters.categoryId = args.categoryId;
      // etc...

      return await context.service.getPosts(filters);
    }
  },

  Mutation: {
    // BAD: Required fields should be non-null in schema
    createPost: async (
      parent: any,
      args: { title?: string; content?: string; categoryId?: string },
      context: { service: Service }
    ) => {
      // Runtime validation that should be in type system
      if (!args.title) {
        throw new Error('Title is required');
      }
      if (!args.content) {
        throw new Error('Content is required');
      }
      if (!args.categoryId) {
        throw new Error('Category ID is required');
      }

      return await context.service.createPost({
        title: args.title,
        content: args.content,
        categoryId: args.categoryId
      });
    }
  }
};
```

**Correct (Separate fields with non-null arguments):**

```graphql
# packages/server/graphql/schema.graphql
type Query {
  # GOOD: Separate fields with clear, non-null arguments
  userById(id: ID!): User
  userByUsername(username: String!): User
  userByEmail(email: String!): User

  # GOOD: Focused queries with clear purpose
  postsByUser(userId: ID!): [Post!]!
  postsByCategory(categoryId: ID!): [Post!]!
  postsByTag(tag: String!): [Post!]!
  searchPosts(query: String!): [Post!]!

  # GOOD: Focused query with clear defaults
  products(
    limit: Int = 10
    sortBy: ProductSortField = CREATED_AT
    sortOrder: SortOrder = DESC
  ): ProductConnection!

  # GOOD: Specific product search with focused input
  searchProducts(input: ProductSearchInput!): ProductConnection!
}

enum ProductSortField {
  CREATED_AT
  PRICE
  RATING
  NAME
}

enum SortOrder {
  ASC
  DESC
}

# GOOD: Focused input with required search criteria
input ProductSearchInput {
  query: String!  # Required - what are we searching for?
  filters: ProductFilters  # Optional refinements
  limit: Int = 20
}

input ProductFilters {
  categoryIds: [ID!]
  priceRange: PriceRangeInput
  brands: [String!]
  minRating: Float
  inStockOnly: Boolean = false
}

input PriceRangeInput {
  min: Float!
  max: Float!
}

# GOOD: Focused input types for specific actions
input CreateUserInput {
  name: String!
  email: String!
  password: String!
  referralCode: String  # Optional with clear purpose
}

input UpdateUserNameInput {
  id: ID!
  name: String!
}

input UpdateUserEmailInput {
  id: ID!
  email: String!
}

input UpdateUserBioInput {
  id: ID!
  bio: String!
}

input UpdateUserAvatarInput {
  id: ID!
  avatarUrl: String!
}

type Mutation {
  # GOOD: All required fields are non-null
  createPost(input: CreatePostInput!): CreatePostPayload!

  # GOOD: Specific mutations for specific actions
  updateUserName(input: UpdateUserNameInput!): UpdateUserPayload!
  updateUserEmail(input: UpdateUserEmailInput!): UpdateUserPayload!
  updateUserBio(input: UpdateUserBioInput!): UpdateUserPayload!
  updateUserAvatar(input: UpdateUserAvatarInput!): UpdateUserPayload!

  # GOOD: Clear invitation with specific parameters
  inviteUserByEmail(input: InviteByEmailInput!): InviteUserPayload!
  inviteExistingUser(input: InviteExistingUserInput!): InviteUserPayload!
}

input CreatePostInput {
  title: String!
  content: String!
  categoryId: ID!
  tags: [String!] = []  # Optional with default
  isDraft: Boolean = false
}

input InviteByEmailInput {
  email: String!
  teamId: ID!
  role: TeamRole!
}

input InviteExistingUserInput {
  userId: ID!
  teamId: ID!
  role: TeamRole!
}

enum TeamRole {
  MEMBER
  ADMIN
  OWNER
}

type Subscription {
  # GOOD: Specific subscriptions with non-null filter
  commentAddedToPost(postId: ID!): Comment!
  commentAddedByUser(userId: ID!): Comment!
  commentAddedWithTag(tag: String!): Comment!
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
import { Service } from '../../service';

export const userResolvers = {
  Query: {
    // GOOD: Simple, clear resolver with non-null argument
    userById: async (
      parent: any,
      args: { id: string },
      context: { service: Service }
    ) => {
      // No conditional logic needed - type system guarantees id is present
      return await context.service.getUserById(args.id);
    },

    // GOOD: Each query has a single, clear purpose
    userByUsername: async (
      parent: any,
      args: { username: string },
      context: { service: Service }
    ) => {
      return await context.service.getUserByUsername(args.username);
    },

    userByEmail: async (
      parent: any,
      args: { email: string },
      context: { service: Service }
    ) => {
      return await context.service.getUserByEmail(args.email);
    },

    // GOOD: Focused query with clear filtering
    postsByUser: async (
      parent: any,
      args: { userId: string },
      context: { service: Service }
    ) => {
      return await context.service.getPostsByUserId(args.userId);
    },

    // GOOD: Default values make behavior explicit
    products: async (
      parent: any,
      args: {
        limit?: number;
        sortBy?: 'CREATED_AT' | 'PRICE' | 'RATING' | 'NAME';
        sortOrder?: 'ASC' | 'DESC';
      },
      context: { service: Service }
    ) => {
      // Defaults are clear from schema
      const limit = args.limit ?? 10;
      const sortBy = args.sortBy ?? 'CREATED_AT';
      const sortOrder = args.sortOrder ?? 'DESC';

      return await context.service.getProducts({ limit, sortBy, sortOrder });
    }
  },

  Mutation: {
    // GOOD: Type system guarantees all required fields are present
    createPost: async (
      parent: any,
      args: { input: CreatePostInput },
      context: { service: Service; userId: string }
    ) => {
      // No validation needed - type system ensures required fields exist
      const { title, content, categoryId, tags = [], isDraft = false } = args.input;

      const post = await context.service.createPost({
        title,
        content,
        categoryId,
        tags,
        isDraft,
        authorId: context.userId
      });

      return { post };
    },

    // GOOD: Focused mutation with clear purpose
    updateUserName: async (
      parent: any,
      args: { input: UpdateUserNameInput },
      context: { service: Service }
    ) => {
      const { id, name } = args.input;

      const user = await context.service.updateUserName(id, name);

      return { user };
    },

    // GOOD: Separate mutations for different use cases
    inviteUserByEmail: async (
      parent: any,
      args: { input: InviteByEmailInput },
      context: { service: Service }
    ) => {
      const { email, teamId, role } = args.input;

      // All required fields guaranteed by type system
      const invitation = await context.service.inviteUserByEmail({
        email,
        teamId,
        role
      });

      return { invitation };
    },

    inviteExistingUser: async (
      parent: any,
      args: { input: InviteExistingUserInput },
      context: { service: Service }
    ) => {
      const { userId, teamId, role } = args.input;

      // Different logic for existing user invitation
      const invitation = await context.service.inviteExistingUser({
        userId,
        teamId,
        role
      });

      return { invitation };
    }
  }
};
```

```typescript
// Example: Product search with focused input
interface ProductSearchInput {
  query: string;  // Required
  filters?: ProductFilters;
  limit?: number;
}

interface ProductFilters {
  categoryIds?: string[];
  priceRange?: { min: number; max: number };
  brands?: string[];
  minRating?: number;
  inStockOnly?: boolean;
}

export const productResolvers = {
  Query: {
    searchProducts: async (
      parent: any,
      args: { input: ProductSearchInput },
      context: { service: Service }
    ) => {
      const { query, filters, limit = 20 } = args.input;

      // Required field (query) is guaranteed to exist
      // Optional filters are clearly optional
      return await context.service.searchProducts({
        query,
        filters: filters || {},
        limit
      });
    }
  }
};
```

```typescript
// Example: Type-safe client code with non-null arguments
// Good: TypeScript/codegen knows exactly what's required
const user = await client.query({
  query: USER_BY_ID,
  variables: {
    id: '123'  // Type error if missing
  }
});

// Good: Clear separate queries for different lookups
const userByUsername = await client.query({
  query: USER_BY_USERNAME,
  variables: {
    username: 'john_doe'  // Type error if missing
  }
});

// Good: Clear required fields in mutations
const result = await client.mutate({
  mutation: CREATE_POST,
  variables: {
    input: {
      title: 'My Post',       // Type error if missing
      content: 'Content',     // Type error if missing
      categoryId: '456',      // Type error if missing
      tags: ['tech'],         // Optional, has default
      isDraft: false          // Optional, has default
    }
  }
});
```

Reference: [GraphQL Best Practices - Nullability](https://graphql.org/learn/best-practices/#nullability) | [GraphQL Schema Design](https://www.apollographql.com/docs/apollo-server/schema/schema/)

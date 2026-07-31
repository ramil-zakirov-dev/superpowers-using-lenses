---
title: Separate Input Types for Create and Update
impact: MEDIUM
impactDescription: Improves type safety and makes mutation requirements explicit
tags: mutation, input-types, type-safety, api-design, validation
---

## Separate Input Types for Create and Update

**Impact: MEDIUM (Improves type safety and makes mutation requirements explicit)**

Don't share the same input type between create and update mutations. Create and update operations have different requirements: create needs required fields, while update needs an ID and typically optional fields. Using the same input type for both operations creates ambiguity, weakens type safety, and complicates validation logic.

**Different Requirements:**
- **Create**: Requires all essential fields to create a new entity, ID should not be present
- **Update**: Requires entity ID, other fields are typically optional for partial updates

**Problems with Shared Input Types:**
- Unclear which fields are required vs optional
- ID field is nullable for create but required for update (confusing)
- All fields become nullable, losing type safety benefits
- Complex runtime validation needed to differentiate create vs update
- Error messages are less helpful
- Auto-generated client types are ambiguous

**Benefits of Separate Input Types:**
- **Type Safety**: Required fields are enforced at compile time
- **Clarity**: Clear which fields are needed for each operation
- **Better Errors**: Type system catches missing required fields before execution
- **Documentation**: Self-documenting API - schema shows exact requirements
- **Client Generation**: Better TypeScript/Flow type generation
- **Validation**: Simpler resolver logic without complex conditional validation

**Naming Conventions:**
- Create: `CreateXInput`, `XCreateInput`, or `NewXInput`
- Update: `UpdateXInput`, `XUpdateInput`, or `XPatchInput`

**Incorrect (Shared input type between create and update):**

```graphql
# schema.graphql
input ProductInput {
  id: ID            # Ambiguous: required for update, shouldn't exist for create
  name: String      # Should be required for create, optional for update
  price: Int        # Should be required for create, optional for update
  description: String
  categoryId: ID    # Should be required for create, optional for update
}

input UserInput {
  id: ID
  email: String     # Should be required for create
  name: String
  role: String
  password: String  # Should be required for create, not for update
}

input PostInput {
  id: ID
  title: String
  content: String
  authorId: ID
  publishedAt: String
}

type Mutation {
  # BAD: Sharing ProductInput between create and update
  createProduct(input: ProductInput!): Product!
  updateProduct(input: ProductInput!): Product!

  # BAD: Sharing UserInput between create and update
  createUser(input: UserInput!): User!
  updateUser(input: UserInput!): User!

  # BAD: Sharing PostInput
  createPost(input: PostInput!): Post!
  updatePost(input: PostInput!): Post!
}
```

```typescript
// resolvers/productResolver.ts
import { Service } from '../service';

interface ProductInput {
  id?: string;
  name?: string;
  price?: number;
  description?: string;
  categoryId?: string;
}

export const productResolvers = {
  Mutation: {
    // BAD: Complex conditional validation needed
    createProduct: async (
      parent: any,
      args: { input: ProductInput },
      context: { service: Service }
    ) => {
      const { id, name, price, description, categoryId } = args.input;

      // Runtime validation that should be in type system
      if (id) {
        throw new Error('ID should not be provided for create');
      }
      if (!name) {
        throw new Error('Name is required');
      }
      if (!price) {
        throw new Error('Price is required');
      }
      if (!categoryId) {
        throw new Error('Category ID is required');
      }

      return await context.service.createProduct({
        name,
        price,
        description,
        categoryId
      });
    },

    // BAD: Different validation logic for same input type
    updateProduct: async (
      parent: any,
      args: { input: ProductInput },
      context: { service: Service }
    ) => {
      const { id, name, price, description, categoryId } = args.input;

      // Different validation rules
      if (!id) {
        throw new Error('ID is required for update');
      }

      // All other fields are optional - unclear from type
      const updates: any = {};
      if (name !== undefined) updates.name = name;
      if (price !== undefined) updates.price = price;
      if (description !== undefined) updates.description = description;
      if (categoryId !== undefined) updates.categoryId = categoryId;

      return await context.service.updateProduct(id, updates);
    }
  }
};
```

```typescript
// Example: Client-side confusion with shared input types
// BAD: Unclear which fields are required

// Create - which fields are required? Type doesn't say
const newProduct = await client.mutate({
  mutation: CREATE_PRODUCT,
  variables: {
    input: {
      // Type allows this, but will fail at runtime
      name: 'Widget'
      // Missing price and categoryId - no type error!
    }
  }
});

// Update - which fields can be omitted? Type doesn't say
const updatedProduct = await client.mutate({
  mutation: UPDATE_PRODUCT,
  variables: {
    input: {
      id: '123',
      name: 'New Widget'
      // Can I omit other fields? Type suggests they might be required
    }
  }
});
```

**Correct (Separate input types for create and update):**

```graphql
# schema.graphql

# Create input - all essential fields are required
input CreateProductInput {
  name: String!
  price: Int!
  description: String!
  categoryId: ID!
}

# Update input - ID required, other fields optional for partial update
input UpdateProductInput {
  id: ID!
  name: String
  price: Int
  description: String
  categoryId: ID
}

# Create user input - required fields for new user
input CreateUserInput {
  email: String!
  name: String!
  role: String!
  password: String!
}

# Update user input - optional fields for partial update
input UpdateUserInput {
  id: ID!
  email: String
  name: String
  role: String
  # Note: password update might be separate mutation for security
}

# Create post input
input CreatePostInput {
  title: String!
  content: String!
  categoryId: ID!
  tags: [String!]
  isDraft: Boolean = false
}

# Update post input
input UpdatePostInput {
  id: ID!
  title: String
  content: String
  categoryId: ID
  tags: [String!]
}

# Publish post - separate action with just ID
input PublishPostInput {
  id: ID!
  publishedAt: String
}

type Mutation {
  # GOOD: Dedicated input types for create and update
  createProduct(input: CreateProductInput!): Product!
  updateProduct(input: UpdateProductInput!): Product!

  createUser(input: CreateUserInput!): User!
  updateUser(input: UpdateUserInput!): User!

  createPost(input: CreatePostInput!): Post!
  updatePost(input: UpdatePostInput!): Post!
  publishPost(input: PublishPostInput!): Post!
}
```

```typescript
// resolvers/productResolver.ts
import { Service } from '../service';

interface CreateProductInput {
  name: string;
  price: number;
  description: string;
  categoryId: string;
}

interface UpdateProductInput {
  id: string;
  name?: string;
  price?: number;
  description?: string;
  categoryId?: string;
}

export const productResolvers = {
  Mutation: {
    // GOOD: Type system guarantees all required fields are present
    createProduct: async (
      parent: any,
      args: { input: CreateProductInput },
      context: { service: Service }
    ) => {
      // No validation needed - type system ensures required fields exist
      const { name, price, description, categoryId } = args.input;

      return await context.service.createProduct({
        name,
        price,
        description,
        categoryId
      });
    },

    // GOOD: Clear that ID is required, other fields optional
    updateProduct: async (
      parent: any,
      args: { input: UpdateProductInput },
      context: { service: Service }
    ) => {
      const { id, ...updates } = args.input;

      // ID is guaranteed to exist
      // Only update fields that are provided
      return await context.service.updateProduct(id, updates);
    }
  }
};
```

```typescript
// resolvers/userResolver.ts
import { Service } from '../service';

interface CreateUserInput {
  email: string;
  name: string;
  role: string;
  password: string;
}

interface UpdateUserInput {
  id: string;
  email?: string;
  name?: string;
  role?: string;
}

export const userResolvers = {
  Mutation: {
    // GOOD: All required fields enforced by type system
    createUser: async (
      parent: any,
      args: { input: CreateUserInput },
      context: { service: Service }
    ) => {
      const { email, name, role, password } = args.input;

      // Additional business logic validation
      if (!email.includes('@')) {
        throw new Error('Invalid email format');
      }

      if (password.length < 8) {
        throw new Error('Password must be at least 8 characters');
      }

      const hashedPassword = await context.service.hashPassword(password);

      return await context.service.createUser({
        email,
        name,
        role,
        password: hashedPassword
      });
    },

    // GOOD: Partial update with clear optional fields
    updateUser: async (
      parent: any,
      args: { input: UpdateUserInput },
      context: { service: Service; userId: string }
    ) => {
      const { id, ...updates } = args.input;

      // Authorization check
      if (id !== context.userId && !context.isAdmin) {
        throw new Error('Unauthorized');
      }

      // Validate email if provided
      if (updates.email && !updates.email.includes('@')) {
        throw new Error('Invalid email format');
      }

      return await context.service.updateUser(id, updates);
    }
  }
};
```

```typescript
// Example: Clear client-side code with separate types
// GOOD: TypeScript knows exactly what's required

// Create - type system shows required fields
const newProduct = await client.mutate({
  mutation: CREATE_PRODUCT,
  variables: {
    input: {
      name: 'Widget',        // Required - type error if missing
      price: 1999,           // Required - type error if missing
      description: 'Great!', // Required - type error if missing
      categoryId: 'cat_123'  // Required - type error if missing
    }
  }
});

// Update - type system shows ID required, others optional
const updatedProduct = await client.mutate({
  mutation: UPDATE_PRODUCT,
  variables: {
    input: {
      id: '123',              // Required - type error if missing
      name: 'New Widget'      // Optional - can omit other fields
      // price, description, categoryId are optional
    }
  }
});

// Create user - clear required fields
const newUser = await client.mutate({
  mutation: CREATE_USER,
  variables: {
    input: {
      email: 'user@example.com',  // Required
      name: 'John Doe',            // Required
      role: 'USER',                // Required
      password: 'secret123'        // Required
    }
  }
});
```

```typescript
// Example: Advanced pattern - composition for shared fields
// When create and update share many fields, use composition

// Shared base fields
input ProductBaseInput {
  name: String
  description: String
  price: Int
}

# Create - extends base with required fields
input CreateProductInput {
  name: String!
  description: String!
  price: Int!
  categoryId: ID!
}

# Update - ID required, base fields optional
input UpdateProductInput {
  id: ID!
  name: String
  description: String
  price: Int
  categoryId: ID
}

// Note: GraphQL doesn't support extends for input types natively
// This is conceptual - in practice, define separately
```

```typescript
// Example: Upsert mutation with discriminated union
// If you truly need upsert, make it explicit

input CreateProductData {
  name: String!
  price: Int!
  description: String!
  categoryId: ID!
}

input UpdateProductData {
  id: ID!
  name: String
  price: Int
  description: String
  categoryId: ID
}

input UpsertProductInput {
  create: CreateProductData
  update: UpdateProductData
}

type Mutation {
  upsertProduct(input: UpsertProductInput!): Product!
}

// Resolver validates exactly one is provided
export const upsertProduct = async (
  parent: any,
  args: { input: UpsertProductInput },
  context: { service: Service }
) => {
  const { create, update } = args.input;

  if (create && update) {
    throw new Error('Provide either create or update, not both');
  }

  if (!create && !update) {
    throw new Error('Must provide either create or update');
  }

  if (create) {
    return await context.service.createProduct(create);
  } else {
    return await context.service.updateProduct(update!.id, update!);
  }
};
```

```graphql
# Example: Additional related input types for complex mutations

input CreateProductInput {
  name: String!
  price: Int!
  description: String!
  categoryId: ID!
}

input UpdateProductInput {
  id: ID!
  name: String
  price: Int
  description: String
}

# Separate input for partial price update
input UpdateProductPriceInput {
  id: ID!
  price: Int!
  effectiveDate: String
}

# Separate input for inventory management
input UpdateProductInventoryInput {
  id: ID!
  quantity: Int!
  warehouseId: ID!
}

type Mutation {
  createProduct(input: CreateProductInput!): Product!
  updateProduct(input: UpdateProductInput!): Product!
  updateProductPrice(input: UpdateProductPriceInput!): Product!
  updateProductInventory(input: UpdateProductInventoryInput!): Product!
}
```

Reference: [GraphQL Best Practices - Input Types](https://graphql.org/learn/schema/#input-types)
---
title: Use Union Result Types for Mutation Responses
impact: HIGH
impactDescription: Enables type-safe error handling and explicit error cases
tags: mutation, errors, union-types, type-safety, error-handling
---

## Use Union Result Types for Mutation Responses

**Impact: HIGH (Enables type-safe error handling and explicit error cases)**

All GraphQL mutations must return a union type that includes a dedicated success type and specific error types, not the success type directly. This pattern provides type-safe error handling, explicit error cases, and enables clients to handle specific error scenarios with full type information.

**Why Union Result Types**

- **Type Safety**: Clients know all possible error cases at compile time
- **Explicit Errors**: Each error type documents what can go wrong and why
- **Context-Rich Errors**: Error types can include fields specific to the error (e.g., `existingUserId` for duplicate errors)
- **No Nullable Fields**: Success and error cases are mutually exclusive via unions
- **Better Client Experience**: Clients can exhaustively pattern match on all outcomes
- **Self-Documenting**: Error types serve as documentation of failure modes
- **GraphQL Code Generation**: Tools like GraphQL Code Generator create typed result handlers

**Union Structure Requirements**

- Name union as `{MutationName}Result` (e.g., `CreateUserResult`, `DeleteProductResult`)
- Include dedicated success type named `{MutationName}Success`
- Include at least one specific error type
- All error types must implement base `Error` interface

**Success Types**

- Create dedicated success type named `{MutationName}Success`
- Success type contains entity as field (e.g., `user: User!`, `product: Product!`)
- Do not include entity directly in union

**Error Types**

- All error types implement `Error` interface with `message: String!`
- Use specific error types for domain validation (e.g., `InvalidEmailError`, `UserNotFoundError`)
- Include additional fields relevant to error context
- Add `code: String!` field for stable error identification across i18n

**Avoid Generic Error Patterns**

- Generic `errors: [Error!]` arrays without specific types
- Mutations returning `{ success: Boolean, message: String }`
- Error codes as strings without typed structure
- Returning entities directly without error handling
- Nullable entity fields that hide error states

**Incorrect (Direct entity returns, generic payloads):**

```graphql
# packages/server/graphql/schema.graphql

interface Error {
  message: String!
}

type User {
  id: ID!
  email: String!
  name: String!
}

type Product {
  id: ID!
  name: String!
  price: Float!
}

type Nursery {
  id: ID!
  name: String!
}

# BAD: Generic Error type used everywhere
type Error {
  message: String!
  code: String
}

# BAD: Generic payload with nullable fields and error array
type CreateUserPayload {
  user: User              # Nullable - hides error state
  errors: [Error!]        # Generic errors with no specificity
}

# BAD: Boolean success with generic message
type OpenNurseryPayload {
  success: Boolean!
  message: String
  nursery: Nursery
}

# BAD: Generic payload pattern
type DeleteUserPayload {
  success: Boolean!
  deletedUserId: ID
  error: String
}

type Mutation {
  # BAD: Returning entity directly - no error handling
  createUser(input: CreateUserInput!): User!

  # BAD: Returning product directly - client can't handle errors
  createProduct(input: CreateProductInput!): Product!

  # BAD: Boolean return - no context on what happened
  deleteUser(id: ID!): Boolean!

  # BAD: Generic payload with nullable fields
  updateUser(input: UpdateUserInput!): CreateUserPayload!

  # BAD: Generic success/message pattern
  openNursery(input: OpenNurseryInput!): OpenNurseryPayload!

  # BAD: Entity directly in union (should use dedicated success type)
  updateProduct(input: UpdateProductInput!): Product | InvalidInputError
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
// BAD: Throwing errors or returning null

export const userResolvers = {
  Mutation: {
    // BAD: Throwing error - client gets generic error response
    createUser: async (
      parent: any,
      args: { input: CreateUserInput },
      context: { service: Service }
    ) => {
      const existingUser = await context.service.getUserByEmail(args.input.email);

      if (existingUser) {
        // Client receives generic error, loses type information
        throw new Error('User with this email already exists');
      }

      if (!isValidEmail(args.input.email)) {
        throw new Error('Invalid email format');
      }

      return await context.service.createUser(args.input);
    },

    // BAD: Generic payload with nullable fields
    updateUser: async (
      parent: any,
      args: { input: UpdateUserInput },
      context: { service: Service }
    ) => {
      try {
        const user = await context.service.updateUser(args.input);
        return {
          user,
          errors: []
        };
      } catch (error) {
        // Generic error - no type safety
        return {
          user: null,
          errors: [{ message: error.message }]
        };
      }
    }
  }
};
```

```typescript
// packages/web-app/src/mutations/user.ts
// BAD: Client can't handle specific error cases

import { gql, useMutation } from '@apollo/client';

const CREATE_USER = gql`
  mutation CreateUser($input: CreateUserInput!) {
    createUser(input: $input) {
      id
      email
      name
    }
  }
`;

function useCreateUser() {
  const [createUser] = useMutation(CREATE_USER);

  return async (input: CreateUserInput) => {
    try {
      const result = await createUser({ variables: { input } });
      return result.data?.createUser;
    } catch (error) {
      // Can't distinguish between error types
      // Is it duplicate user? Invalid email? Network error?
      console.error('Failed to create user:', error.message);
      throw error;
    }
  };
}
```

**Correct (Union result types with specific errors):**

```graphql
# packages/server/graphql/schema.graphql

# Base error interface - all errors must implement
interface Error {
  message: String!
}

type User {
  id: ID!
  email: String!
  name: String!
}

type Product {
  id: ID!
  name: String!
  price: Float!
}

type Nursery {
  id: ID!
  name: String!
}

# Specific error types with context

type InvalidEmailError implements Error {
  message: String!
  field: String!
  providedEmail: String!
}

type UserNotFoundError implements Error {
  message: String!
  userId: ID!
}

type DuplicateUserError implements Error {
  message: String!
  existingUserId: ID!
  conflictingField: String!  # "email" or "username"
}

type ProductNameTakenError implements Error {
  code: String!              # Stable code for i18n: "PRODUCT_NAME_TAKEN"
  message: String!
  suggestedName: String      # Help user with alternative
}

type ProductNotFoundError implements Error {
  message: String!
  productId: ID!
}

type InsufficientPermissionsError implements Error {
  code: String!
  message: String!
  requiredRole: String!
  userRole: String!
}

type ValidationError implements Error {
  code: String!
  field: String!
  message: String!
  constraint: String         # "min_length", "max_value", etc.
}

type NurseryNameTakenError implements Error {
  message: String!
  existingNurseryId: ID!
}

# Dedicated success types (not entities directly)

type CreateUserSuccess {
  user: User!
}

type UpdateUserSuccess {
  user: User!
}

type DeleteUserSuccess {
  deletedUser: User!         # Include deleted entity for undo
}

type CreateProductSuccess {
  product: Product!
}

type UpdateProductSuccess {
  product: Product!
}

type DeleteProductSuccess {
  deletedProductId: ID!
}

type OpenNurserySuccess {
  nursery: Nursery!
}

# Union result types

union CreateUserResult =
  | CreateUserSuccess
  | InvalidEmailError
  | DuplicateUserError

union UpdateUserResult =
  | UpdateUserSuccess
  | UserNotFoundError
  | InvalidEmailError
  | InsufficientPermissionsError

union DeleteUserResult =
  | DeleteUserSuccess
  | UserNotFoundError
  | InsufficientPermissionsError

union CreateProductResult =
  | CreateProductSuccess
  | ProductNameTakenError
  | ValidationError
  | InsufficientPermissionsError

union UpdateProductResult =
  | UpdateProductSuccess
  | ProductNotFoundError
  | ValidationError
  | InsufficientPermissionsError

union DeleteProductResult =
  | DeleteProductSuccess
  | ProductNotFoundError
  | InsufficientPermissionsError

union OpenNurseryResult =
  | OpenNurserySuccess
  | NurseryNameTakenError
  | InsufficientPermissionsError

type Mutation {
  # All mutations return union types with explicit error cases
  createUser(input: CreateUserInput!): CreateUserResult!
  updateUser(input: UpdateUserInput!): UpdateUserResult!
  deleteUser(id: ID!): DeleteUserResult!

  createProduct(input: CreateProductInput!): CreateProductResult!
  updateProduct(input: UpdateProductInput!): UpdateProductResult!
  deleteProduct(id: ID!): DeleteProductResult!

  openNursery(input: OpenNurseryInput!): OpenNurseryResult!
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
// GOOD: Returning specific error types

interface CreateUserInput {
  email: string;
  name: string;
  password: string;
}

type CreateUserResult =
  | { __typename: 'CreateUserSuccess'; user: User }
  | { __typename: 'InvalidEmailError'; message: string; field: string; providedEmail: string }
  | { __typename: 'DuplicateUserError'; message: string; existingUserId: string; conflictingField: string };

export const userResolvers = {
  Mutation: {
    createUser: async (
      parent: any,
      args: { input: CreateUserInput },
      context: { service: Service }
    ): Promise<CreateUserResult> => {
      // Validate email format
      if (!isValidEmail(args.input.email)) {
        return {
          __typename: 'InvalidEmailError',
          message: 'The email address format is invalid',
          field: 'email',
          providedEmail: args.input.email
        };
      }

      // Check for existing user
      const existingUser = await context.service.getUserByEmail(args.input.email);

      if (existingUser) {
        return {
          __typename: 'DuplicateUserError',
          message: 'A user with this email already exists',
          existingUserId: existingUser.id,
          conflictingField: 'email'
        };
      }

      // Create user
      const user = await context.service.createUser(args.input);

      return {
        __typename: 'CreateUserSuccess',
        user
      };
    },

    deleteUser: async (
      parent: any,
      args: { id: string },
      context: { service: Service; userId: string }
    ) => {
      // Check if user exists
      const user = await context.service.getUserById(args.id);

      if (!user) {
        return {
          __typename: 'UserNotFoundError',
          message: `User with ID ${args.id} not found`,
          userId: args.id
        };
      }

      // Check permissions
      if (context.userId !== args.id && !context.service.isAdmin(context.userId)) {
        return {
          __typename: 'InsufficientPermissionsError',
          code: 'INSUFFICIENT_PERMISSIONS',
          message: 'You do not have permission to delete this user',
          requiredRole: 'admin',
          userRole: 'user'
        };
      }

      await context.service.deleteUser(args.id);

      return {
        __typename: 'DeleteUserSuccess',
        deletedUser: user
      };
    }
  },

  // Union resolvers
  CreateUserResult: {
    __resolveType(obj: any) {
      return obj.__typename;
    }
  },

  DeleteUserResult: {
    __resolveType(obj: any) {
      return obj.__typename;
    }
  }
};
```

```typescript
// packages/web-app/src/mutations/user.ts
// GOOD: Type-safe client with exhaustive error handling

import { gql, useMutation } from '@apollo/client';

const CREATE_USER = gql`
  mutation CreateUser($input: CreateUserInput!) {
    createUser(input: $input) {
      __typename
      ... on CreateUserSuccess {
        user {
          id
          email
          name
        }
      }
      ... on InvalidEmailError {
        message
        field
        providedEmail
      }
      ... on DuplicateUserError {
        message
        existingUserId
        conflictingField
      }
    }
  }
`;

interface CreateUserInput {
  email: string;
  name: string;
  password: string;
}

type CreateUserResult =
  | { __typename: 'CreateUserSuccess'; user: { id: string; email: string; name: string } }
  | { __typename: 'InvalidEmailError'; message: string; field: string; providedEmail: string }
  | { __typename: 'DuplicateUserError'; message: string; existingUserId: string; conflictingField: string };

function useCreateUser() {
  const [createUserMutation] = useMutation(CREATE_USER);

  return async (input: CreateUserInput) => {
    const result = await createUserMutation({ variables: { input } });
    const data = result.data?.createUser as CreateUserResult;

    // Exhaustive type-safe error handling
    switch (data.__typename) {
      case 'CreateUserSuccess':
        return { success: true, user: data.user };

      case 'InvalidEmailError':
        // Handle invalid email specifically
        return {
          success: false,
          error: 'INVALID_EMAIL',
          message: data.message,
          field: data.field
        };

      case 'DuplicateUserError':
        // Handle duplicate user specifically
        return {
          success: false,
          error: 'DUPLICATE_USER',
          message: data.message,
          existingUserId: data.existingUserId
        };

      default:
        // TypeScript ensures exhaustiveness
        const _exhaustive: never = data;
        throw new Error('Unhandled result type');
    }
  };
}

// Usage in component
function SignupForm() {
  const createUser = useCreateUser();
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (formData: CreateUserInput) => {
    const result = await createUser(formData);

    if (!result.success) {
      // Type-safe error handling with specific messages
      switch (result.error) {
        case 'INVALID_EMAIL':
          setError(`Invalid email format: ${result.message}`);
          break;

        case 'DUPLICATE_USER':
          setError('This email is already registered. Try logging in instead.');
          break;
      }
    } else {
      // Success case
      navigate(`/users/${result.user.id}`);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      {error && <ErrorMessage>{error}</ErrorMessage>}
      {/* form fields */}
    </form>
  );
}
```

```typescript
// Example: GraphQL Code Generator types

// Generated types from schema
type CreateUserResult =
  | { __typename: 'CreateUserSuccess'; user: User }
  | { __typename: 'InvalidEmailError'; message: string; field: string; providedEmail: string }
  | { __typename: 'DuplicateUserError'; message: string; existingUserId: string; conflictingField: string };

// Type-safe helper for exhaustive matching
function matchCreateUserResult<T>(
  result: CreateUserResult,
  handlers: {
    success: (data: Extract<CreateUserResult, { __typename: 'CreateUserSuccess' }>) => T;
    invalidEmail: (error: Extract<CreateUserResult, { __typename: 'InvalidEmailError' }>) => T;
    duplicateUser: (error: Extract<CreateUserResult, { __typename: 'DuplicateUserError' }>) => T;
  }
): T {
  switch (result.__typename) {
    case 'CreateUserSuccess':
      return handlers.success(result);
    case 'InvalidEmailError':
      return handlers.invalidEmail(result);
    case 'DuplicateUserError':
      return handlers.duplicateUser(result);
  }
}

// Usage
const result = await createUser(input);

const message = matchCreateUserResult(result, {
  success: (data) => `User ${data.user.name} created successfully!`,
  invalidEmail: (error) => `Invalid email: ${error.providedEmail}`,
  duplicateUser: (error) => 'Email already taken. Try logging in.'
});
```

```typescript
// Example: Product mutations with validation errors

interface CreateProductInput {
  name: string;
  price: number;
  description: string;
}

export const productResolvers = {
  Mutation: {
    createProduct: async (
      parent: any,
      args: { input: CreateProductInput },
      context: { service: Service }
    ) => {
      // Validation
      if (args.input.price < 0) {
        return {
          __typename: 'ValidationError',
          code: 'INVALID_PRICE',
          field: 'price',
          message: 'Price must be positive',
          constraint: 'min_value'
        };
      }

      if (args.input.name.length < 3) {
        return {
          __typename: 'ValidationError',
          code: 'INVALID_NAME_LENGTH',
          field: 'name',
          message: 'Product name must be at least 3 characters',
          constraint: 'min_length'
        };
      }

      // Check if name is taken
      const existingProduct = await context.service.getProductByName(args.input.name);

      if (existingProduct) {
        const suggestedName = await context.service.generateUniqueName(args.input.name);

        return {
          __typename: 'ProductNameTakenError',
          code: 'PRODUCT_NAME_TAKEN',
          message: `Product name "${args.input.name}" is already taken`,
          suggestedName
        };
      }

      // Check permissions
      if (!context.service.canCreateProduct(context.userId)) {
        return {
          __typename: 'InsufficientPermissionsError',
          code: 'INSUFFICIENT_PERMISSIONS',
          message: 'Only admins can create products',
          requiredRole: 'admin',
          userRole: context.service.getUserRole(context.userId)
        };
      }

      const product = await context.service.createProduct(args.input);

      return {
        __typename: 'CreateProductSuccess',
        product
      };
    }
  }
};
```

```typescript
// Example: Internationalization with error codes

// i18n/en.json
{
  "errors": {
    "PRODUCT_NAME_TAKEN": "This product name is already in use. Try: {{suggestedName}}",
    "INSUFFICIENT_PERMISSIONS": "You need {{requiredRole}} role to perform this action",
    "INVALID_EMAIL": "The email address is not valid",
    "DUPLICATE_USER": "A user with this email already exists"
  }
}

// Client-side error handling with i18n
function useCreateProduct() {
  const { t } = useTranslation();
  const [createProductMutation] = useMutation(CREATE_PRODUCT);

  return async (input: CreateProductInput) => {
    const result = await createProductMutation({ variables: { input } });
    const data = result.data?.createProduct;

    if (data.__typename === 'ProductNameTakenError') {
      // Use error code for translation
      const message = t(`errors.${data.code}`, {
        suggestedName: data.suggestedName
      });

      return { success: false, error: message };
    }

    if (data.__typename === 'InsufficientPermissionsError') {
      const message = t(`errors.${data.code}`, {
        requiredRole: data.requiredRole
      });

      return { success: false, error: message };
    }

    // ... handle other cases
  };
}
```

```graphql
# Example: Consistent pattern across all mutations

type Mutation {
  # User mutations
  createUser(input: CreateUserInput!): CreateUserResult!
  updateUser(input: UpdateUserInput!): UpdateUserResult!
  deleteUser(id: ID!): DeleteUserResult!

  # Product mutations
  createProduct(input: CreateProductInput!): CreateProductResult!
  updateProduct(input: UpdateProductInput!): UpdateProductResult!
  deleteProduct(id: ID!): DeleteProductResult!

  # Order mutations
  createOrder(input: CreateOrderInput!): CreateOrderResult!
  cancelOrder(id: ID!): CancelOrderResult!

  # All follow same pattern: {Action}{Entity}Result
}

# All success types follow pattern: {Action}{Entity}Success
type CreateUserSuccess { user: User! }
type CreateProductSuccess { product: Product! }
type CreateOrderSuccess { order: Order! }

# Error types are reusable across mutations
type ValidationError implements Error { ... }
type InsufficientPermissionsError implements Error { ... }
type NotFoundError implements Error { ... }
```
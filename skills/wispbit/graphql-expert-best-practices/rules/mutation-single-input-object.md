---
title: Use Single Input Object for Mutation Arguments
impact: HIGH
impactDescription: Improves API evolvability and client ergonomics
tags: mutation, input, arguments, api-design, evolvability
---

## Use Single Input Object for Mutation Arguments

**Impact: HIGH (Improves API evolvability and client ergonomics)**

GraphQL mutations should take a single input object argument instead of multiple scalar arguments. This pattern improves API evolvability, makes mutations easier to extend, and provides better client-side ergonomics.

**Why Single Input Objects**

- **Evolvability**: Adding new fields to an input object is backward compatible; adding new arguments is not
- **Named Arguments**: Input objects provide named fields, improving code clarity
- **Reusability**: Input types can be reused across multiple mutations
- **Client Ergonomics**: Easier to construct and pass around objects than manage many arguments
- **Validation**: Input objects can have complex validation logic and nested structures
- **Documentation**: Input types serve as documentation for what data mutations expect
- **Consistency**: Following Relay Modern and GraphQL best practices conventions

**Trigger Conditions**

Apply this rule when mutations have:
- More than 2-3 scalar arguments
- Mix of scalar arguments and input objects
- Arguments that logically group together (address fields, user data, etc.)
- Arguments that may need future extension

**Exceptions**

Single scalar argument mutations are acceptable for very simple operations:
- `deleteUser(id: ID!): DeleteUserPayload!` - OK, single identifier
- `likePost(postId: ID!): Post!` - OK, single action on single entity

**Incorrect (Multiple scalar arguments):**

```graphql
# packages/server/graphql/schema.graphql

type Mutation {
  # BAD: Too many scalar arguments (6 parameters)
  createOrder(
    userId: ID!,
    productId: ID!,
    quantity: Int!,
    price: Float!,
    discount: Float!,
    shippingCost: Float!
  ): Order!
  
  # BAD: Multiple scalars for address data
  addShippingAddressToCart(
    cartId: ID!,
    line1: String!,
    line2: String,
    city: String!,
    state: String!,
    zip: String!,
    country: String!
  ): Cart!
  
  # BAD: Mixing scalars with input objects
  updateUser(
    id: ID!,
    name: String!,
    email: String!,
    profile: ProfileInput!
  ): User!
  
  # BAD: Multiple unrelated scalars
  sendNotification(
    userId: ID!,
    title: String!,
    body: String!,
    type: String!,
    priority: Int!
  ): Notification!
  
  # BAD: Complex product creation with many scalars
  createProduct(
    name: String!,
    description: String!,
    price: Float!,
    category: String!,
    sku: String!,
    stock: Int!,
    weight: Float!,
    dimensions: String!
  ): Product!
}

input ProfileInput {
  bio: String
  avatar: String
}
```

```typescript
// packages/server/src/routes/resolvers/orderResolver.ts
// BAD: Resolver with many individual parameters

export const orderResolvers = {
  Mutation: {
    createOrder: async (
      parent: any,
      args: {
        userId: string;
        productId: string;
        quantity: number;
        price: number;
        discount: number;
        shippingCost: number;
      },
      context: { service: Service }
    ) => {
      // Hard to extend - adding new field requires changing signature
      return await context.service.createOrder({
        userId: args.userId,
        productId: args.productId,
        quantity: args.quantity,
        price: args.price,
        discount: args.discount,
        shippingCost: args.shippingCost
      });
    }
  }
};
```

```typescript
// packages/web-app/src/mutations/order.ts
// BAD: Client code with many individual arguments

import { gql, useMutation } from '@apollo/client';

const CREATE_ORDER = gql`
  mutation CreateOrder(
    $userId: ID!
    $productId: ID!
    $quantity: Int!
    $price: Float!
    $discount: Float!
    $shippingCost: Float!
  ) {
    createOrder(
      userId: $userId
      productId: $productId
      quantity: $quantity
      price: $price
      discount: $discount
      shippingCost: $shippingCost
    ) {
      id
      total
    }
  }
`;

function useCreateOrder() {
  const [createOrder] = useMutation(CREATE_ORDER);
  
  return (orderData: {
    userId: string;
    productId: string;
    quantity: number;
    price: number;
    discount: number;
    shippingCost: number;
  }) => {
    // Verbose: must map each field individually
    return createOrder({
      variables: {
        userId: orderData.userId,
        productId: orderData.productId,
        quantity: orderData.quantity,
        price: orderData.price,
        discount: orderData.discount,
        shippingCost: orderData.shippingCost
      }
    });
  };
}
```

**Correct (Single input object argument):**

```graphql
# packages/server/graphql/schema.graphql

type Mutation {
  # GOOD: Single input object
  createOrder(input: CreateOrderInput!): CreateOrderPayload!
  
  # GOOD: Single input with nested address
  addShippingAddressToCart(input: AddShippingAddressInput!): AddShippingAddressPayload!
  
  # GOOD: Single input object for user updates
  updateUser(input: UpdateUserInput!): UpdateUserPayload!
  
  # GOOD: Single input for notifications
  sendNotification(input: SendNotificationInput!): SendNotificationPayload!
  
  # GOOD: Single input for product creation
  createProduct(input: CreateProductInput!): CreateProductPayload!
  
  # GOOD: Simple single-argument mutations are OK
  deleteOrder(id: ID!): DeleteOrderPayload!
  likePost(postId: ID!): Post!
}

# Input types group related fields logically
input CreateOrderInput {
  userId: ID!
  productId: ID!
  quantity: Int!
  price: Float!
  discount: Float
  shippingCost: Float!
}

input AddShippingAddressInput {
  cartId: ID!
  address: AddressInput!
}

input AddressInput {
  line1: String!
  line2: String
  city: String!
  state: String!
  zip: String!
  country: String!
}

input UpdateUserInput {
  id: ID!
  name: String
  email: String
  profile: ProfileInput
}

input ProfileInput {
  bio: String
  avatar: String
}

input SendNotificationInput {
  userId: ID!
  title: String!
  body: String!
  type: NotificationType!
  priority: Int!
}

enum NotificationType {
  EMAIL
  PUSH
  SMS
}

input CreateProductInput {
  name: String!
  description: String!
  price: Float!
  category: String!
  sku: String!
  stock: Int!
  dimensions: DimensionsInput!
}

input DimensionsInput {
  weight: Float!
  length: Float!
  width: Float!
  height: Float!
}

# Consistent payload types
type CreateOrderPayload {
  order: Order
  errors: [UserError!]
}

type AddShippingAddressPayload {
  cart: Cart
  errors: [UserError!]
}

type UpdateUserPayload {
  user: User
  errors: [UserError!]
}

type SendNotificationPayload {
  notification: Notification
  errors: [UserError!]
}

type CreateProductPayload {
  product: Product
  errors: [UserError!]
}

type DeleteOrderPayload {
  deletedOrderId: ID
  errors: [UserError!]
}

type UserError {
  field: String
  message: String!
}
```

```typescript
// packages/server/src/routes/resolvers/orderResolver.ts
// GOOD: Resolver with single input object parameter

interface CreateOrderInput {
  userId: string;
  productId: string;
  quantity: number;
  price: number;
  discount?: number;
  shippingCost: number;
}

export const orderResolvers = {
  Mutation: {
    createOrder: async (
      parent: any,
      args: { input: CreateOrderInput },
      context: { service: Service }
    ) => {
      try {
        // Easy to extend - new fields added to input type
        // Easy to validate - can validate entire input object
        const order = await context.service.createOrder(args.input);
        
        return {
          order,
          errors: []
        };
      } catch (error) {
        return {
          order: null,
          errors: [{
            message: error.message
          }]
        };
      }
    }
  }
};
```

```typescript
// packages/web-app/src/mutations/order.ts
// GOOD: Client code with single input object

import { gql, useMutation } from '@apollo/client';

const CREATE_ORDER = gql`
  mutation CreateOrder($input: CreateOrderInput!) {
    createOrder(input: $input) {
      order {
        id
        total
        status
      }
      errors {
        field
        message
      }
    }
  }
`;

interface CreateOrderInput {
  userId: string;
  productId: string;
  quantity: number;
  price: number;
  discount?: number;
  shippingCost: number;
}

function useCreateOrder() {
  const [createOrder] = useMutation(CREATE_ORDER);
  
  return (input: CreateOrderInput) => {
    // Clean: pass entire object directly
    return createOrder({
      variables: { input }
    });
  };
}

// Usage
function CheckoutButton({ orderData }: { orderData: CreateOrderInput }) {
  const createOrder = useCreateOrder();
  
  const handleCheckout = async () => {
    // Easy to use - just pass the object
    const result = await createOrder(orderData);
    
    if (result.data?.createOrder.errors.length) {
      console.error('Order failed:', result.data.createOrder.errors);
    } else {
      console.log('Order created:', result.data?.createOrder.order);
    }
  };
  
  return <button onClick={handleCheckout}>Complete Order</button>;
}
```

```typescript
// Example: Evolvability - adding new fields

// BEFORE: Adding a field requires breaking change
// type Mutation {
//   createOrder(userId: ID!, productId: ID!, quantity: Int!): Order!
// }

// Need to add gift message - BREAKING CHANGE (new required arg position)
// type Mutation {
//   createOrder(userId: ID!, productId: ID!, quantity: Int!, giftMessage: String): Order!
// }

// AFTER: With input object - NON-BREAKING CHANGE
type Mutation {
  createOrder(input: CreateOrderInput!): CreateOrderPayload!
}

input CreateOrderInput {
  userId: ID!
  productId: ID!
  quantity: Int!
  # New optional field - backward compatible
  giftMessage: String
  # Can add more fields in future
  giftWrap: Boolean
  deliveryInstructions: String
}
```

```typescript
// Example: Complex nested inputs

// GOOD: Deeply nested input objects for complex operations
input CreateCheckoutSessionInput {
  cartId: ID!
  customer: CustomerInput!
  shipping: ShippingInput!
  billing: BillingInput!
  payment: PaymentInput!
}

input CustomerInput {
  email: String!
  phone: String
  firstName: String!
  lastName: String!
}

input ShippingInput {
  address: AddressInput!
  method: ShippingMethod!
}

input BillingInput {
  address: AddressInput!
  taxId: String
}

input PaymentInput {
  method: PaymentMethod!
  # Payment method specific fields
  cardToken: String
  bankAccountId: String
}

type Mutation {
  createCheckoutSession(input: CreateCheckoutSessionInput!): CheckoutSessionPayload!
}
```

```typescript
// Example: Input validation

import { z } from 'zod';

// GOOD: Input objects enable comprehensive validation
const CreateOrderInputSchema = z.object({
  userId: z.string().uuid(),
  productId: z.string().uuid(),
  quantity: z.number().int().min(1).max(100),
  price: z.number().positive(),
  discount: z.number().min(0).max(1).optional(),
  shippingCost: z.number().nonnegative()
});

export const orderResolvers = {
  Mutation: {
    createOrder: async (
      parent: any,
      args: { input: CreateOrderInput },
      context: { service: Service }
    ) => {
      // Validate entire input object
      const validationResult = CreateOrderInputSchema.safeParse(args.input);
      
      if (!validationResult.success) {
        return {
          order: null,
          errors: validationResult.error.errors.map(err => ({
            field: err.path.join('.'),
            message: err.message
          }))
        };
      }
      
      const order = await context.service.createOrder(validationResult.data);
      
      return {
        order,
        errors: []
      };
    }
  }
};
```

```graphql
# Example: Consistent mutation patterns

type Mutation {
  # All mutations follow same pattern: single input, payload response
  createUser(input: CreateUserInput!): CreateUserPayload!
  updateUser(input: UpdateUserInput!): UpdateUserPayload!
  deleteUser(input: DeleteUserInput!): DeleteUserPayload!
  
  createPost(input: CreatePostInput!): CreatePostPayload!
  updatePost(input: UpdatePostInput!): UpdatePostPayload!
  deletePost(input: DeletePostInput!): DeletePostPayload!
  
  createComment(input: CreateCommentInput!): CreateCommentPayload!
  updateComment(input: UpdateCommentInput!): UpdateCommentPayload!
  deleteComment(input: DeleteCommentInput!): DeleteCommentPayload!
}

# Consistent naming: {Action}{Entity}Input
input CreateUserInput {
  email: String!
  name: String!
}

input UpdateUserInput {
  id: ID!
  email: String
  name: String
}

input DeleteUserInput {
  id: ID!
}

# Consistent naming: {Action}{Entity}Payload
type CreateUserPayload {
  user: User
  errors: [UserError!]
}

type UpdateUserPayload {
  user: User
  errors: [UserError!]
}

type DeleteUserPayload {
  deletedUserId: ID
  errors: [UserError!]
}
```

```typescript
// Example: Reusable input types

// GOOD: Input types can be reused across mutations
input AddressInput {
  line1: String!
  line2: String
  city: String!
  state: String!
  zip: String!
  country: String!
}

type Mutation {
  # Reuse AddressInput in multiple mutations
  updateUserShippingAddress(input: UpdateUserShippingAddressInput!): User!
  updateUserBillingAddress(input: UpdateUserBillingAddressInput!): User!
  addWarehouseLocation(input: AddWarehouseLocationInput!): Warehouse!
}

input UpdateUserShippingAddressInput {
  userId: ID!
  address: AddressInput!
}

input UpdateUserBillingAddressInput {
  userId: ID!
  address: AddressInput!
}

input AddWarehouseLocationInput {
  warehouseId: ID!
  address: AddressInput!
}
```

Reference: [GraphQL Best Practices - Input Object Mutations](https://graphql.org/learn/best-practices/#input-object-mutations) | [Relay Input Object Mutations](https://relay.dev/docs/guides/graphql-server-specification/#mutations)

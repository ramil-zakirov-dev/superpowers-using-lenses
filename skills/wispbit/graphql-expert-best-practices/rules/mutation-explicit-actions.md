---
title: Design Mutations Around Explicit Actions
impact: HIGH
impactDescription: Improves API clarity, maintainability, and prevents hidden capabilities
tags: mutation, api-design, maintainability, schema, actions
---

## Design Mutations Around Explicit Actions

**Impact: HIGH (Improves API clarity, maintainability, and prevents hidden capabilities)**

GraphQL mutations should be designed around explicit user actions rather than generic "god update" patterns that hide capabilities. Generic update mutations with many optional fields make it unclear what operations are allowed, complicate authorization logic, and create maintenance nightmares as business rules evolve.

**Avoid Generic Update Mutations:**
- Split mutations that handle multiple business actions into explicit, action-specific mutations
- Replace broad `updateX`, `setX`, `editX` mutations with specific action verbs
- Each mutation should represent a single, clear business action

**When to Trigger (Heuristic):**

Trigger refactoring when a mutation name is broad (`updateX`, `setX`, `editX`) and its input object:
- Has many fields (e.g., > 6–10), especially mostly-optional fields, or
- Mixes concerns (profile fields + media upload + relations + settings), or
- Indicates it's being used as a "patch endpoint" for anything

**State Machine Flags:**
- Mutations should not use input fields that represent state machine transitions (like `isAvailable`, `status`, `isActive`) in generic update operations
- Create explicit mutations for state transitions: `activateX`, `deactivateX`, `publishX`, `archiveX`

**Multiple Business Actions:**
- When a single mutation performs different business logic based on which input fields are present, split it into separate mutations for each action
- Each mutation should have clear authorization rules and validation logic

**Benefits of Explicit Mutations:**
- **Clarity**: API consumers know exactly what operations are available
- **Authorization**: Easier to implement fine-grained permissions per action
- **Validation**: Each mutation can have specific validation rules
- **Tracking**: Analytics and audit logs show actual user intent
- **Evolution**: Easier to modify business rules for specific actions
- **Type Safety**: Stronger type checking with required vs optional fields per action

**Incorrect (Generic "god update" mutations):**

```graphql
# src/graphql/schema.graphql
input BookInput {
  title: String
  count: Int
  isAvailable: Boolean  # State machine flag
  status: String  # State machine flag
}

input CartInput {
  productId: ID
  couponCode: String
  shippingAddress: AddressInput
  paymentMethod: PaymentMethodInput
  # Mixes multiple concerns
}

input UpdatePlantInput {
  scientificName: String!
  name: String
  size: Int
  photos: [PhotoInput!]
  hosts: [InsectInput!]
  location: LocationInput
  wateringSchedule: String
  isActive: Boolean  # State machine flag
  notes: String
  # Too many fields, mixes concerns
}

input UserInput {
  name: String
  email: String
  profilePhoto: String
  preferences: PreferencesInput
  subscriptions: [SubscriptionInput!]
  isActive: Boolean  # State machine flag
  role: String  # Should be separate action
  lastLoginAt: String  # System field, shouldn't be in input
  # Mixes profile, settings, auth, system fields
}

input ProductUpdateInput {
  name: String
  price: Float
  description: String
  category: String
  tags: [String!]
  isAvailable: Boolean  # State machine flag
  inventory: Int
  photos: [String!]
  specifications: JSON
  # 9+ fields, mixes details, pricing, inventory, media
}

type Mutation {
  # Generic update with state machine flags
  updateBook(id: ID!, book: BookInput!): Boolean

  # Multiple business actions in one mutation
  updateCart(
    cartId: ID!
    productId: ID
    couponCode: String
    shippingAddress: AddressInput
    payment: PaymentMethodInput
  ): Cart!

  # Generic "do-everything" plant mutation
  updatePlant(input: UpdatePlantInput!): Plant!

  # Generic user update mixing concerns
  updateUser(id: ID!, input: UserInput!): User!

  # Broad mutation with many optional fields
  updateProduct(
    id: ID!
    name: String
    price: Float
    description: String
    category: String
    tags: [String!]
    isAvailable: Boolean
    inventory: Int
    photos: [String!]
    specifications: JSON
  ): Product!
}
```

```typescript
// src/resolvers/entityResolver.ts
export const productResolvers = {
  Mutation: {
    // BAD: Complex conditional logic based on which fields are present
    updateProduct: async (parent: any, args: any, context: { service: Service }) => {
      const { id, ...updates } = args;

      // Complex authorization logic
      if (updates.price !== undefined && !context.hasPermission('update:pricing')) {
        throw new Error('Unauthorized');
      }
      if (updates.isAvailable !== undefined && !context.hasPermission('manage:availability')) {
        throw new Error('Unauthorized');
      }
      if (updates.inventory !== undefined && !context.hasPermission('manage:inventory')) {
        throw new Error('Unauthorized');
      }

      // Different validation rules based on fields
      if (updates.price !== undefined && updates.price <= 0) {
        throw new Error('Price must be positive');
      }
      if (updates.inventory !== undefined && updates.inventory < 0) {
        throw new Error('Inventory cannot be negative');
      }

      // Different business logic paths
      if (updates.isAvailable !== undefined) {
        await context.service.updateProductAvailability(id, updates.isAvailable);
        await context.service.notifyInventorySystem(id);
      }

      if (updates.price !== undefined) {
        await context.service.updateProductPrice(id, updates.price);
        await context.service.invalidatePriceCache(id);
      }

      // Just patches everything else
      return await context.service.updateProduct(id, updates);
    }
  }
};
```

**Correct (Explicit action-based mutations):**

```graphql
# src/graphql/schema.graphql

# Book mutations - explicit actions
input BookDetailsInput {
  title: String
  count: Int
}

# Cart mutations - separate concerns
input AddProductInput {
  productId: ID!
  quantity: Int!
}

input ShippingAddressInput {
  street: String!
  city: String!
  state: String!
  zipCode: String!
  country: String!
}

# Plant mutations - focused inputs
input PlantBasicInfoInput {
  scientificName: String!
  name: String
  size: Int
  wateringSchedule: String
  notes: String
}

input PlantLocationInput {
  latitude: Float!
  longitude: Float!
  address: String
}

# User mutations - separated by concern
input UserProfileInput {
  name: String!
  email: String
  profilePhoto: String
}

input UserPreferencesInput {
  theme: String
  notifications: Boolean
  language: String
  timezone: String
}

# Product mutations - specific inputs per action
input ProductDetailsInput {
  name: String!
  description: String
  category: String
  tags: [String!]
}

input ProductPricingInput {
  price: Float!
  currency: String!
  compareAtPrice: Float
}

input ProductSpecificationsInput {
  specifications: JSON!
}

type Mutation {
  # Explicit book actions - clear intent
  updateBookDetails(id: ID!, input: BookDetailsInput!): Book!
  borrowBook(id: ID!): Book!
  returnBook(id: ID!): Book!
  markBookAsLost(id: ID!): Book!

  # Explicit cart workflow - each step is clear
  createCart: Cart!
  addProductToCart(cartId: ID!, input: AddProductInput!): Cart!
  removeProductFromCart(cartId: ID!, productId: ID!): Cart!
  updateCartProductQuantity(cartId: ID!, productId: ID!, quantity: Int!): Cart!
  applyCouponToCart(cartId: ID!, couponCode: String!): Cart!
  removeCouponFromCart(cartId: ID!): Cart!
  addShippingAddress(cartId: ID!, address: ShippingAddressInput!): Cart!
  addPaymentMethod(cartId: ID!, payment: PaymentMethodInput!): Cart!
  submitOrder(cartId: ID!): Order!

  # Task-focused plant mutations - single responsibility
  updatePlantBasicInfo(plantId: ID!, input: PlantBasicInfoInput!): Plant!
  updatePlantLocation(plantId: ID!, input: PlantLocationInput!): Plant!
  addPlantHost(plantId: ID!, insect: InsectInput!): Plant!
  removePlantHost(plantId: ID!, insectId: ID!): Plant!
  createPlantPhotoUploadUrl(plantId: ID!): CreatePlantPhotoUploadResult!
  deletePlantPhoto(plantId: ID!, photoId: ID!): Plant!
  activatePlant(plantId: ID!): Plant!  # Explicit state transition
  deactivatePlant(plantId: ID!): Plant!  # Explicit state transition

  # Explicit user actions - separated by concern
  updateUserProfile(id: ID!, profile: UserProfileInput!): User!
  updateUserPreferences(id: ID!, preferences: UserPreferencesInput!): User!
  createUserPhotoUploadUrl(id: ID!): CreatePhotoUploadResult!
  removeUserPhoto(id: ID!): User!
  activateUser(id: ID!): User!  # Explicit state transition
  deactivateUser(id: ID!): User!  # Explicit state transition
  changeUserRole(id: ID!, role: String!): User!  # Separate privileged action
  subscribeUser(id: ID!, subscriptionType: String!): User!
  unsubscribeUser(id: ID!, subscriptionType: String!): User!

  # Specific product actions - clear and focused
  updateProductDetails(id: ID!, input: ProductDetailsInput!): Product!
  updateProductPricing(id: ID!, input: ProductPricingInput!): Product!
  updateProductInventory(id: ID!, quantity: Int!): Product!
  addProductPhotos(id: ID!, photos: [String!]!): Product!
  removeProductPhoto(id: ID!, photoId: String!): Product!
  updateProductSpecifications(id: ID!, input: ProductSpecificationsInput!): Product!
  publishProduct(id: ID!): Product!  # Explicit state transition
  unpublishProduct(id: ID!): Product!  # Explicit state transition
  archiveProduct(id: ID!): Product!  # Explicit state transition
}
```

```typescript
// src/resolvers/entityResolver.ts
import { Service } from '../../service';

interface ProductDetailsInput {
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
}

interface ProductPricingInput {
  price: number;
  currency: string;
  compareAtPrice?: number;
}

export const productResolvers = {
  Mutation: {
    // GOOD: Clear, single-purpose mutation with specific authorization
    updateProductDetails: async (
      parent: any,
      args: { id: string; input: ProductDetailsInput },
      context: { service: Service; hasPermission: (perm: string) => boolean }
    ) => {
      // Single permission check
      if (!context.hasPermission('update:product-details')) {
        throw new Error('Unauthorized to update product details');
      }

      // Specific validation for this action
      if (args.input.name.length < 3) {
        throw new Error('Product name must be at least 3 characters');
      }

      // Clear business logic for this specific action
      const product = await context.service.updateProductDetails(args.id, args.input);

      // Specific side effects for this action
      await context.service.invalidateProductCache(args.id);

      return product;
    },

    // GOOD: Separate mutation for pricing with different authorization
    updateProductPricing: async (
      parent: any,
      args: { id: string; input: ProductPricingInput },
      context: { service: Service; hasPermission: (perm: string) => boolean }
    ) => {
      // Different permission for pricing
      if (!context.hasPermission('update:product-pricing')) {
        throw new Error('Unauthorized to update product pricing');
      }

      // Pricing-specific validation
      if (args.input.price <= 0) {
        throw new Error('Price must be positive');
      }

      if (args.input.compareAtPrice && args.input.compareAtPrice <= args.input.price) {
        throw new Error('Compare at price must be greater than price');
      }

      // Pricing-specific business logic
      const product = await context.service.updateProductPricing(args.id, args.input);

      // Pricing-specific side effects
      await context.service.invalidatePriceCache(args.id);
      await context.service.notifyPriceChangeSubscribers(args.id);

      return product;
    },

    // GOOD: Explicit state transition with clear semantics
    publishProduct: async (
      parent: any,
      args: { id: string },
      context: { service: Service; hasPermission: (perm: string) => boolean }
    ) => {
      if (!context.hasPermission('publish:product')) {
        throw new Error('Unauthorized to publish products');
      }

      // Validate product is ready for publishing
      const product = await context.service.getProduct(args.id);

      if (!product.price || product.price <= 0) {
        throw new Error('Cannot publish product without valid price');
      }

      if (!product.photos || product.photos.length === 0) {
        throw new Error('Cannot publish product without photos');
      }

      // Perform state transition
      const publishedProduct = await context.service.publishProduct(args.id);

      // State transition side effects
      await context.service.addToSearchIndex(args.id);
      await context.service.notifySubscribers(args.id, 'product_published');

      return publishedProduct;
    },

    // GOOD: Inventory update with specific logic
    updateProductInventory: async (
      parent: any,
      args: { id: string; quantity: number },
      context: { service: Service; hasPermission: (perm: string) => boolean }
    ) => {
      if (!context.hasPermission('manage:inventory')) {
        throw new Error('Unauthorized to manage inventory');
      }

      if (args.quantity < 0) {
        throw new Error('Inventory quantity cannot be negative');
      }

      const product = await context.service.updateProductInventory(args.id, args.quantity);

      // Inventory-specific side effects
      if (args.quantity === 0) {
        await context.service.notifyOutOfStock(args.id);
      } else if (args.quantity < 10) {
        await context.service.notifyLowStock(args.id);
      }

      await context.service.syncWithInventorySystem(args.id);

      return product;
    }
  }
};
```

```typescript
// Example: explicit workflow mutations
export const cartResolvers = {
  Mutation: {
    addProductToCart: async (
      parent: any,
      args: { cartId: string; input: AddProductInput },
      context: { service: Service; userId: string }
    ) => {
      // Clear authorization: user must own cart
      const cart = await context.service.getCart(args.cartId);
      if (cart.userId !== context.userId) {
        throw new Error('Cannot modify another user\'s cart');
      }

      // Specific validation
      if (args.input.quantity <= 0) {
        throw new Error('Quantity must be positive');
      }

      // Check product availability
      const product = await context.service.getProduct(args.input.productId);
      if (!product.isAvailable) {
        throw new Error('Product is not available');
      }

      if (product.inventory < args.input.quantity) {
        throw new Error('Insufficient inventory');
      }

      // Clear single action
      return await context.service.addProductToCart(
        args.cartId,
        args.input.productId,
        args.input.quantity
      );
    },

    submitOrder: async (
      parent: any,
      args: { cartId: string },
      context: { service: Service; userId: string }
    ) => {
      const cart = await context.service.getCart(args.cartId);

      // Authorization
      if (cart.userId !== context.userId) {
        throw new Error('Cannot submit another user\'s cart');
      }

      // Validate cart is ready for submission
      if (!cart.shippingAddress) {
        throw new Error('Shipping address is required');
      }

      if (!cart.paymentMethod) {
        throw new Error('Payment method is required');
      }

      if (cart.items.length === 0) {
        throw new Error('Cart is empty');
      }

      // Complex multi-step order submission
      const order = await context.service.createOrderFromCart(cart);
      await context.service.processPayment(order);
      await context.service.reserveInventory(order);
      await context.service.sendOrderConfirmation(order);

      return order;
    }
  }
};
```

Reference: [GraphQL Best Practices - Mutations](https://graphql.org/learn/queries/#mutations)

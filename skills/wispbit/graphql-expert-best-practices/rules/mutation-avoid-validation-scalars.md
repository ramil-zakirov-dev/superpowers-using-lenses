---
title: Avoid Custom Validation Scalars in Mutation Inputs
impact: MEDIUM
impactDescription: Prevents multi-request error-discovery loop and improves UX
tags: mutation, scalars, validation, ux, error-handling
---

## Avoid Custom Validation Scalars in Mutation Inputs

**Impact: MEDIUM (Prevents multi-request error-discovery loop and improves UX)**

Avoid using custom validation scalars (PhoneNumber, EmailAddress, PostalCode, etc.) for mutation inputs when the operation requires multi-error validation UX. Custom scalar validation errors force clients into a two-request error-discovery loop, degrading user experience.

**When to Apply:**
Apply this rule when mutations have both:
- Custom scalar types for validation (PhoneNumber, EmailAddress, etc.)
- Business rule validation (limits, quotas, fraud checks, duplicate detection, etc.)

**The Problem:**
Custom scalars validate at the GraphQL execution layer, before resolvers run. This creates a two-phase error discovery:

1. **First Request**: Fails at scalar validation (e.g., invalid email format)
2. Client fixes scalar errors
3. **Second Request**: Reaches resolver but fails business validation (e.g., email already exists)
4. Client must make multiple requests to discover all errors

**The Solution:**
Use `String` types and validate everything in the resolver. Return all validation errors (format + business rules) in a single structured response.

**Benefits:**
- **Single Request**: All errors discovered in one round trip
- **Better UX**: User sees all issues at once, not incrementally
- **Controlled Error Shape**: Consistent error format across all validations
- **Field-Level Errors**: Errors can be mapped to specific form fields
- **Flexibility**: Can customize validation rules without schema changes

**When Custom Scalars Are OK:**
- Read-only fields in query responses
- Internal APIs where multi-request loops aren't an issue
- Mutations with only scalar validation (no business rules)
- Non-user-facing APIs

**Incorrect (Custom scalars force multi-request loop):**

```graphql
# src/schema.graphql
scalar PhoneNumber
scalar EmailAddress
scalar PostalCode
scalar URL

input CheckoutInput {
  phone: PhoneNumber!      # Validates before resolver
  email: EmailAddress!     # Validates before resolver
  postalCode: PostalCode!  # Validates before resolver
  cartId: ID!
}

input CreateUserInput {
  email: EmailAddress!     # Validates before resolver
  phone: PhoneNumber!      # Validates before resolver
  website: URL
  referralCode: String
}

input CreateProductInput {
  name: String!
  price: Float!
  website: URL            # Validates before resolver
  supportEmail: EmailAddress!  # Validates before resolver
}

type Mutation {
  # BAD: Multi-phase error discovery
  checkout(input: CheckoutInput!): CheckoutPayload!
  createUser(input: CreateUserInput!): CreateUserPayload!
  createProduct(input: CreateProductInput!): CreateProductPayload!
}
```

```typescript
// src/resolvers/checkout.ts
// BAD: User experience flow

// Request 1: User submits form
checkout({
  phone: "555-1234",           // Invalid format
  email: "not-an-email",       // Invalid format
  postalCode: "12345",
  cartId: "cart_123"
})
// Response: Scalar validation error (before reaching resolver)
// Error: Invalid phone number format
// Error: Invalid email address format

// User fixes format errors...

// Request 2: User resubmits
checkout({
  phone: "+1-555-123-4567",    // Valid format now
  email: "user@example.com",   // Valid format now
  postalCode: "12345",
  cartId: "cart_123"
})
// Response: Business validation error (now reaches resolver)
// Error: Email already in use
// Error: Phone number already registered
// Error: Cart has expired items

// User has to go through multiple rounds to discover all errors!
```

```typescript
// src/types/scalars.ts
// BAD: Custom scalars validate before resolver

import { GraphQLError, GraphQLScalarType } from 'graphql';

export const EmailAddressScalar = new GraphQLScalarType({
  name: 'EmailAddress',
  serialize: (value) => value,
  parseValue: (value: string) => {
    // Validates during input parsing (before resolver)
    if (!value.includes('@')) {
      throw new GraphQLError('Invalid email address');
    }
    return value;
  }
});

// Problem: Client can't get business validation errors
// until scalar validation passes
```

**Correct (String types with resolver validation):**

```graphql
# src/schema.graphql

input CheckoutInput {
  phone: String!
  email: String!
  postalCode: String!
  cartId: ID!
}

input CreateUserInput {
  email: String!
  phone: String!
  website: String
  referralCode: String
}

input CreateProductInput {
  name: String!
  price: Float!
  website: String
  supportEmail: String!
}

# Structured error response
type ValidationError {
  field: String!
  message: String!
  code: String
}

type CheckoutPayload {
  order: Order
  errors: [ValidationError!]
}

type CreateUserPayload {
  user: User
  errors: [ValidationError!]
}

type CreateProductPayload {
  product: Product
  errors: [ValidationError!]
}

type Mutation {
  # GOOD: All validation in single request
  checkout(input: CheckoutInput!): CheckoutPayload!
  createUser(input: CreateUserInput!): CreateUserPayload!
  createProduct(input: CreateProductInput!): CreateProductPayload!
}
```

```typescript
// src/resolvers/checkout.ts
// GOOD: All validation in resolver, single request

import { Service } from '../services';

interface CheckoutInput {
  phone: string;
  email: string;
  postalCode: string;
  cartId: string;
}

interface ValidationError {
  field: string;
  message: string;
  code?: string;
}

export const checkoutResolvers = {
  Mutation: {
    checkout: async (
      parent: any,
      args: { input: CheckoutInput },
      context: { service: Service }
    ) => {
      const { phone, email, postalCode, cartId } = args.input;
      const errors: ValidationError[] = [];

      // Validate ALL errors at once - format + business rules

      // Format validation
      if (!isValidPhone(phone)) {
        errors.push({
          field: 'phone',
          message: 'Invalid phone number format',
          code: 'INVALID_PHONE_FORMAT'
        });
      }

      if (!isValidEmail(email)) {
        errors.push({
          field: 'email',
          message: 'Invalid email address',
          code: 'INVALID_EMAIL_FORMAT'
        });
      }

      if (!isValidPostalCode(postalCode)) {
        errors.push({
          field: 'postalCode',
          message: 'Invalid postal code',
          code: 'INVALID_POSTAL_CODE'
        });
      }

      // Business validation (runs even if format validation fails)
      if (await context.service.isEmailInUse(email)) {
        errors.push({
          field: 'email',
          message: 'Email already in use',
          code: 'EMAIL_ALREADY_EXISTS'
        });
      }

      if (await context.service.isPhoneRegistered(phone)) {
        errors.push({
          field: 'phone',
          message: 'Phone number already registered',
          code: 'PHONE_ALREADY_REGISTERED'
        });
      }

      const cart = await context.service.getCart(cartId);
      if (cart.hasExpiredItems) {
        errors.push({
          field: 'cartId',
          message: 'Cart contains expired items',
          code: 'CART_HAS_EXPIRED_ITEMS'
        });
      }

      // Return ALL errors in single response
      if (errors.length > 0) {
        return { order: null, errors };
      }

      // Proceed with checkout
      const order = await context.service.createOrder({
        phone,
        email,
        postalCode,
        cartId
      });

      return { order, errors: [] };
    }
  }
};

// Helper functions
function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function isValidPhone(phone: string): boolean {
  return /^\+?[1-9]\d{1,14}$/.test(phone);
}

function isValidPostalCode(code: string): boolean {
  return /^\d{5}(-\d{4})?$/.test(code);
}
```

```typescript
// src/validation/validators.ts
// GOOD: Centralized validation utilities

export interface ValidationResult {
  field: string;
  message: string;
  code: string;
}

export class Validator {
  private errors: ValidationResult[] = [];

  email(value: string, field: string = 'email'): this {
    if (!value || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      this.errors.push({
        field,
        message: 'Invalid email address',
        code: 'INVALID_EMAIL'
      });
    }
    return this;
  }

  phone(value: string, field: string = 'phone'): this {
    if (!value || !/^\+?[1-9]\d{1,14}$/.test(value)) {
      this.errors.push({
        field,
        message: 'Invalid phone number',
        code: 'INVALID_PHONE'
      });
    }
    return this;
  }

  postalCode(value: string, field: string = 'postalCode'): this {
    if (!value || !/^\d{5}(-\d{4})?$/.test(value)) {
      this.errors.push({
        field,
        message: 'Invalid postal code',
        code: 'INVALID_POSTAL_CODE'
      });
    }
    return this;
  }

  url(value: string, field: string = 'url'): this {
    try {
      new URL(value);
    } catch {
      this.errors.push({
        field,
        message: 'Invalid URL',
        code: 'INVALID_URL'
      });
    }
    return this;
  }

  async unique(
    value: string,
    field: string,
    checkFn: (value: string) => Promise<boolean>,
    message: string,
    code: string
  ): Promise<this> {
    if (await checkFn(value)) {
      this.errors.push({ field, message, code });
    }
    return this;
  }

  getErrors(): ValidationResult[] {
    return this.errors;
  }

  isValid(): boolean {
    return this.errors.length === 0;
  }
}

// Usage in resolver
export const createUserResolver = {
  createUser: async (
    parent: any,
    args: { input: CreateUserInput },
    context: { service: Service }
  ) => {
    const { email, phone, website } = args.input;

    const validator = new Validator();

    // All validation in one pass
    validator
      .email(email)
      .phone(phone);

    if (website) {
      validator.url(website, 'website');
    }

    // Async business validation
    await validator.unique(
      email,
      'email',
      (e) => context.service.emailExists(e),
      'Email already in use',
      'EMAIL_EXISTS'
    );

    await validator.unique(
      phone,
      'phone',
      (p) => context.service.phoneExists(p),
      'Phone already registered',
      'PHONE_EXISTS'
    );

    if (!validator.isValid()) {
      return { user: null, errors: validator.getErrors() };
    }

    const user = await context.service.createUser(args.input);
    return { user, errors: [] };
  }
};
```

```typescript
// Example: Client-side experience comparison

// BAD: Multi-request loop with custom scalars
async function submitCheckoutWithScalars(formData) {
  try {
    // First attempt
    const result = await client.mutate({
      mutation: CHECKOUT,
      variables: { input: formData }
    });
  } catch (error) {
    // Scalar validation error - no business errors yet
    showErrors(['Invalid email format', 'Invalid phone format']);
    // User fixes format...

    // Second attempt
    try {
      const result = await client.mutate({
        mutation: CHECKOUT,
        variables: { input: fixedFormData }
      });
    } catch (error) {
      // Now business validation errors appear
      showErrors(['Email already in use', 'Cart expired']);
      // User frustrated by multiple rounds
    }
  }
}

// GOOD: Single request with all errors
async function submitCheckoutWithStrings(formData) {
  const result = await client.mutate({
    mutation: CHECKOUT,
    variables: { input: formData }
  });

  if (result.data.checkout.errors.length > 0) {
    // ALL errors returned at once - format + business
    showErrors(result.data.checkout.errors.map(e => e.message));
    // User sees:
    // - Invalid email format
    // - Email already in use
    // - Invalid phone format
    // - Phone already registered
    // - Cart has expired items
    // All in one request!
  }
}
```

```typescript
// Example: Form integration with field-level errors

interface FormErrors {
  [field: string]: string;
}

async function handleSubmit(formData: CheckoutInput) {
  const result = await client.mutate({
    mutation: CHECKOUT,
    variables: { input: formData }
  });

  if (result.data.checkout.errors) {
    // Map errors to form fields
    const fieldErrors: FormErrors = {};

    result.data.checkout.errors.forEach(error => {
      fieldErrors[error.field] = error.message;
    });

    // Show all field errors at once
    setFieldErrors(fieldErrors);
    // {
    //   email: "Invalid email format",
    //   phone: "Phone already registered",
    //   cartId: "Cart contains expired items"
    // }
  }
}
```

```graphql
# Example: Query with custom scalar is fine (read-only)

scalar EmailAddress
scalar PhoneNumber

type User {
  id: ID!
  name: String!
  email: EmailAddress!  # OK - read-only field
  phone: PhoneNumber!   # OK - read-only field
}

type Query {
  user(id: ID!): User
}

# Custom scalars are fine for responses
# Problem is only with mutation inputs + multi-error validation
```

```typescript
// Example: When custom scalars are acceptable

// OK: Mutation with ONLY scalar validation (no business rules)
type Mutation {
  validateEmail(email: EmailAddress!): Boolean!
  validatePhone(phone: PhoneNumber!): Boolean!
}

// OK: Internal API (no user-facing forms)
type Mutation {
  syncUser(email: EmailAddress!): User!
}

// NOT OK: User-facing mutation with business validation
type Mutation {
  createUser(input: CreateUserInput!): CreateUserPayload!
}

input CreateUserInput {
  email: EmailAddress!  # BAD - will also check if email exists
  phone: PhoneNumber!   # BAD - will also check if phone exists
}
```

```typescript
// Example: Advanced - validation with internationalization

interface ValidationContext {
  locale: string;
}

class LocalizedValidator {
  constructor(private locale: string) {}

  email(value: string, field: string): ValidationResult | null {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      return {
        field,
        message: this.t('validation.email.invalid'),
        code: 'INVALID_EMAIL'
      };
    }
    return null;
  }

  phone(value: string, field: string): ValidationResult | null {
    if (!/^\+?[1-9]\d{1,14}$/.test(value)) {
      return {
        field,
        message: this.t('validation.phone.invalid'),
        code: 'INVALID_PHONE'
      };
    }
    return null;
  }

  private t(key: string): string {
    // Return localized message based on locale
    const messages = {
      'en': {
        'validation.email.invalid': 'Invalid email address',
        'validation.phone.invalid': 'Invalid phone number'
      },
      'es': {
        'validation.email.invalid': 'Dirección de correo electrónico no válida',
        'validation.phone.invalid': 'Número de teléfono no válido'
      }
    };
    return messages[this.locale]?.[key] || key;
  }
}

// Usage
export const createUserResolver = {
  createUser: async (
    parent: any,
    args: { input: CreateUserInput },
    context: { locale: string; service: Service }
  ) => {
    const validator = new LocalizedValidator(context.locale);
    // Returns errors in user's language
  }
};
```
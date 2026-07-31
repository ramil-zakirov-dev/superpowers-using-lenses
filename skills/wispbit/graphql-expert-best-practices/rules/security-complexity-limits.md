---
title: Require Complexity and Query Node Limits
impact: CRITICAL
impactDescription: Prevents resource exhaustion and denial of service attacks
tags: security, complexity, dos-prevention, validation, rate-limiting
---

## Require Complexity and Query Node Limits

**Impact: CRITICAL (Prevents resource exhaustion and denial of service attacks)**

GraphQL servers must implement complexity limits to prevent resource exhaustion attacks. Configure both complexity limits and query node limits using appropriate validation rules. Without these limits, malicious actors can craft deeply nested or extremely large queries that consume excessive server resources, leading to denial of service.

**Two Required Protections:**
1. **Complexity Limit**: Limits the computational cost of a query based on field weights
2. **Query Node Limit**: Limits the total number of AST nodes in a query

**Why Both Are Needed:**
- Complexity limits prevent expensive deeply-nested queries
- Query node limits prevent extremely wide queries with many fields
- Together they provide comprehensive protection against resource exhaustion

**Attack Scenarios Without Limits:**
- Deeply nested circular queries (e.g., `user { posts { author { posts { author ... } } } }`)
- Extremely wide queries requesting hundreds/thousands of fields
- Combination attacks mixing depth and breadth
- Queries with large argument values causing database strain

**Implementation Requirements:**

**TypeScript (Apollo Server):**
- Use `createComplexityLimitRule` for complexity limiting
- Implement custom `maxQueryNodesRule` for AST node counting
- Add both to `validationRules` array

**Python (Ariadne):**
- Use `cost_validator` for complexity limiting
- Implement custom `MaxQueryNodesRule` class extending `ValidationRule`
- Return both from `get_validation_rules` function

**Recommended Limits:**
- Complexity: 500-1000 for simple APIs, 1000-2000 for complex APIs
- Query Nodes: 3000-10000 depending on query patterns
- Adjust based on performance testing and monitoring

**Incorrect (Missing or incomplete protection):**

```typescript
// packages/server/src/server.ts
import { ApolloServer } from "@apollo/server";
import { schema } from "./schema";

// BAD: No complexity limits at all
export const server = new ApolloServer({
  schema,
  // No validationRules configured
  // Server is vulnerable to resource exhaustion attacks
});

// Vulnerable to attacks like:
// query {
//   user(id: "1") {
//     posts { author { posts { author { posts { author {
//       posts { author { posts { author { posts {
//         # ... 50+ levels deep
//       }}}}}}
//     }}}
//   }
// }
```

```typescript
// packages/server/src/graphql-server.ts
import { ApolloServer } from "@apollo/server";
import { createComplexityLimitRule } from "graphql-validation-complexity";

// BAD: Only complexity limit, missing query nodes limit
export const server = new ApolloServer({
  schema,
  validationRules: [
    createComplexityLimitRule(750),
    // Missing maxQueryNodesRule
  ],
});

// Still vulnerable to extremely wide queries:
// query {
//   field1 field2 field3 ... field10000
//   user(id: "1") { field1 field2 field3 ... field500 }
//   # Thousands of fields but low complexity
// }
```

```python
# packages/server/graphql/server.py
from ariadne.asgi import GraphQL
from ariadne import make_executable_schema

# BAD: No validation rules at all
app = GraphQL(
    make_executable_schema(type_defs, resolvers),
    # No validation_rules parameter
)
# Completely unprotected against resource exhaustion
```

```python
# packages/server/graphql/app.py
from ariadne.asgi import GraphQL
from ariadne.validation import cost_validator

# BAD: Only cost validator, missing query nodes rule
def get_validation_rules(context_value, document, data):
    return [
        cost_validator(maximum_cost=200, variables=data.get("variables")),
        # Missing MaxQueryNodesRule
    ]

app = GraphQL(schema, validation_rules=get_validation_rules)
# Still vulnerable to wide queries
```

```typescript
// Example: Real attack without protection
const maliciousQuery = `
  query AttackServer {
    ${Array.from({ length: 1000 }, (_, i) =>
      `user${i}: user(id: "${i}") {
        ${Array.from({ length: 100 }, (_, j) => `field${j}`).join('\n')}
      }`
    ).join('\n')}
  }
`;
// 1000 users × 100 fields = 100,000 operations
// Without limits, this will crash the server
```

**Correct (Both complexity and node limits configured):**

```typescript
// packages/server/src/server.ts
import { ApolloServer } from "@apollo/server";
import { GraphQLError, Kind, type ValidationRule } from "graphql";
import { createComplexityLimitRule } from "graphql-validation-complexity";
import { schema } from "./schema";

const MAX_COMPLEXITY = 750;
const MAX_QUERY_NODES = 5_000;

// GOOD: Custom query node limit validator
function maxQueryNodesRule(max: number): ValidationRule {
  return (context) => {
    let count = 0;

    return {
      enter(node) {
        // Count fields, fragment spreads, and inline fragments
        if (
          node.kind === Kind.FIELD ||
          node.kind === Kind.FRAGMENT_SPREAD ||
          node.kind === Kind.INLINE_FRAGMENT
        ) {
          count += 1;

          if (count > max) {
            context.reportError(
              new GraphQLError(
                `Query is too large: ${count} nodes (max ${max}).`,
                {
                  nodes: [node],
                  extensions: {
                    code: 'QUERY_TOO_LARGE',
                    maxNodes: max,
                    actualNodes: count
                  }
                }
              )
            );
          }
        }
      },
    };
  };
}

// GOOD: Both limits configured
export const server = new ApolloServer({
  schema,
  validationRules: [
    createComplexityLimitRule(MAX_COMPLEXITY, {
      onCost: (cost) => {
        console.log('Query complexity:', cost);
      },
    }),
    maxQueryNodesRule(MAX_QUERY_NODES),
  ],
});
```

```typescript
// packages/server/src/config/validation.ts
// GOOD: Centralized validation configuration

import { GraphQLError, Kind, type ValidationRule } from "graphql";
import { createComplexityLimitRule } from "graphql-validation-complexity";

interface ValidationConfig {
  maxComplexity: number;
  maxQueryNodes: number;
  enableLogging?: boolean;
}

export function createValidationRules(config: ValidationConfig): ValidationRule[] {
  const { maxComplexity, maxQueryNodes, enableLogging = false } = config;

  const complexityRule = createComplexityLimitRule(maxComplexity, {
    onCost: enableLogging ? (cost) => {
      console.log('[GraphQL] Query complexity:', cost);
    } : undefined,
    createError: (cost, max) => {
      return new GraphQLError(
        `Query complexity of ${cost} exceeds maximum of ${max}`,
        {
          extensions: {
            code: 'COMPLEXITY_LIMIT_EXCEEDED',
            maxComplexity: max,
            actualComplexity: cost
          }
        }
      );
    }
  });

  const nodeCountRule = (context: any) => {
    let count = 0;

    return {
      enter(node: any) {
        if (
          node.kind === Kind.FIELD ||
          node.kind === Kind.FRAGMENT_SPREAD ||
          node.kind === Kind.INLINE_FRAGMENT
        ) {
          count += 1;

          if (enableLogging && count % 1000 === 0) {
            console.log(`[GraphQL] Query node count: ${count}`);
          }

          if (count > maxQueryNodes) {
            context.reportError(
              new GraphQLError(
                `Query contains ${count} nodes, exceeding maximum of ${maxQueryNodes}`,
                {
                  nodes: [node],
                  extensions: {
                    code: 'NODE_LIMIT_EXCEEDED',
                    maxNodes: maxQueryNodes,
                    actualNodes: count
                  }
                }
              )
            );
          }
        }
      },
    };
  };

  return [complexityRule, nodeCountRule];
}

// Usage
import { ApolloServer } from "@apollo/server";
import { createValidationRules } from "./config/validation";

const isProd = process.env.NODE_ENV === 'production';

export const server = new ApolloServer({
  schema,
  validationRules: createValidationRules({
    maxComplexity: isProd ? 750 : 1500,  // Lower in production
    maxQueryNodes: isProd ? 5_000 : 10_000,
    enableLogging: !isProd
  }),
});
```

```python
# packages/server/graphql/server.py
from ariadne.asgi import GraphQL
from ariadne.validation import cost_validator
from graphql import GraphQLError
from graphql.language import FieldNode, FragmentSpreadNode, InlineFragmentNode
from graphql.validation import ValidationRule

MAX_COST = 200
MAX_QUERY_NODES = 5000

# GOOD: Custom query node limit validator
class MaxQueryNodesRule(ValidationRule):
    """Validates that queries don't exceed maximum AST node count."""

    def __init__(self, context, max_nodes=MAX_QUERY_NODES):
        super().__init__(context)
        self.max_nodes = max_nodes
        self.count = 0

    def _bump(self, node):
        """Increment node count and check limit."""
        self.count += 1
        if self.count > self.max_nodes:
            self.report_error(
                GraphQLError(
                    f"Query is too large: {self.count} nodes (max {self.max_nodes}).",
                    node,
                    extensions={
                        "code": "NODE_LIMIT_EXCEEDED",
                        "max_nodes": self.max_nodes,
                        "actual_nodes": self.count,
                    },
                )
            )

    def enter_field(self, node: FieldNode, *_args):
        self._bump(node)

    def enter_fragment_spread(self, node: FragmentSpreadNode, *_args):
        self._bump(node)

    def enter_inline_fragment(self, node: InlineFragmentNode, *_args):
        self._bump(node)

# GOOD: Both validation rules configured
def get_validation_rules(context_value, document, data):
    """Return validation rules for query protection."""
    return [
        cost_validator(
            maximum_cost=MAX_COST,
            variables=data.get("variables"),
            on_cost_calculated=lambda cost: print(f"Query cost: {cost}")
        ),
        lambda ctx: MaxQueryNodesRule(ctx, max_nodes=MAX_QUERY_NODES),
    ]

app = GraphQL(schema, validation_rules=get_validation_rules)
```

```python
# packages/server/graphql/validation_config.py
# GOOD: Centralized validation configuration

import os
from typing import Any, Callable, List
from ariadne.validation import cost_validator
from graphql import GraphQLError
from graphql.language import FieldNode, FragmentSpreadNode, InlineFragmentNode
from graphql.validation import ValidationRule

class MaxQueryNodesRule(ValidationRule):
    """Custom validation rule to limit query AST nodes."""

    def __init__(self, context, max_nodes: int, enable_logging: bool = False):
        super().__init__(context)
        self.max_nodes = max_nodes
        self.count = 0
        self.enable_logging = enable_logging

    def _bump(self, node):
        self.count += 1

        if self.enable_logging and self.count % 1000 == 0:
            print(f"[GraphQL] Query node count: {self.count}")

        if self.count > self.max_nodes:
            self.report_error(
                GraphQLError(
                    f"Query contains {self.count} nodes, exceeding maximum of {self.max_nodes}",
                    node,
                    extensions={
                        "code": "NODE_LIMIT_EXCEEDED",
                        "max_nodes": self.max_nodes,
                        "actual_nodes": self.count,
                    },
                )
            )

    def enter_field(self, node: FieldNode, *_args):
        self._bump(node)

    def enter_fragment_spread(self, node: FragmentSpreadNode, *_args):
        self._bump(node)

    def enter_inline_fragment(self, node: InlineFragmentNode, *_args):
        self._bump(node)

def create_validation_rules(
    max_cost: int = 200,
    max_nodes: int = 5000,
    enable_logging: bool = False,
) -> Callable:
    """
    Create validation rules with configurable limits.

    Args:
        max_cost: Maximum query complexity cost
        max_nodes: Maximum number of AST nodes
        enable_logging: Whether to log validation metrics

    Returns:
        Function that returns list of validation rules
    """
    def get_rules(context_value: Any, document: Any, data: Any) -> List:
        rules = [
            cost_validator(
                maximum_cost=max_cost,
                variables=data.get("variables"),
                on_cost_calculated=lambda cost: (
                    print(f"[GraphQL] Query cost: {cost}") if enable_logging else None
                ),
            ),
            lambda ctx: MaxQueryNodesRule(ctx, max_nodes, enable_logging),
        ]
        return rules

    return get_rules

# Usage
from ariadne.asgi import GraphQL

IS_PROD = os.getenv("ENVIRONMENT") == "production"

app = GraphQL(
    schema,
    validation_rules=create_validation_rules(
        max_cost=200 if IS_PROD else 500,
        max_nodes=5000 if IS_PROD else 10000,
        enable_logging=not IS_PROD,
    ),
)
```

```typescript
// Example: Testing complexity limits

import { ApolloServer } from "@apollo/server";
import { schema } from "./schema";
import { createValidationRules } from "./config/validation";

describe("Complexity Limits", () => {
  const server = new ApolloServer({
    schema,
    validationRules: createValidationRules({
      maxComplexity: 100,
      maxQueryNodes: 50,
    }),
  });

  it("should reject queries exceeding complexity limit", async () => {
    const query = `
      query {
        users {
          posts {
            comments {
              author {
                posts {
                  comments {
                    # Very deep nesting
                  }
                }
              }
            }
          }
        }
      }
    `;

    const result = await server.executeOperation({ query });

    expect(result.errors).toBeDefined();
    expect(result.errors[0].extensions?.code).toBe('COMPLEXITY_LIMIT_EXCEEDED');
  });

  it("should reject queries exceeding node limit", async () => {
    // Generate query with 100 fields
    const fields = Array.from({ length: 100 }, (_, i) => `field${i}`).join('\n');
    const query = `query { user { ${fields} } }`;

    const result = await server.executeOperation({ query });

    expect(result.errors).toBeDefined();
    expect(result.errors[0].extensions?.code).toBe('NODE_LIMIT_EXCEEDED');
  });

  it("should allow queries within limits", async () => {
    const query = `
      query {
        user(id: "123") {
          id
          name
          email
        }
      }
    `;

    const result = await server.executeOperation({ query });

    expect(result.errors).toBeUndefined();
  });
});
```

```typescript
// Example: Monitoring and alerting for blocked queries

import { ApolloServer } from "@apollo/server";
import { GraphQLError } from "graphql";
import { createComplexityLimitRule } from "graphql-validation-complexity";

const server = new ApolloServer({
  schema,
  validationRules: [
    createComplexityLimitRule(750, {
      onCost: (cost) => {
        // Log all query costs for analysis
        metrics.histogram('graphql.query.complexity', cost);

        // Alert on queries approaching the limit
        if (cost > 600) {
          logger.warn('High complexity query detected', {
            complexity: cost,
            threshold: 750
          });
        }
      },
      createError: (cost, max) => {
        // Alert when queries are blocked
        alerting.send({
          severity: 'warning',
          title: 'GraphQL query blocked due to complexity',
          description: `Query with complexity ${cost} exceeded limit of ${max}`,
          tags: ['graphql', 'security', 'dos-prevention']
        });

        // Track blocked query attempts
        metrics.increment('graphql.queries.blocked.complexity');

        return new GraphQLError(
          `Query complexity of ${cost} exceeds maximum of ${max}`,
          { extensions: { code: 'COMPLEXITY_LIMIT_EXCEEDED' } }
        );
      }
    })
  ],
  plugins: [
    {
      async requestDidStart() {
        return {
          async didEncounterErrors({ errors }) {
            errors.forEach(error => {
              if (error.extensions?.code === 'COMPLEXITY_LIMIT_EXCEEDED') {
                logger.error('Complexity limit exceeded', {
                  error: error.message,
                  extensions: error.extensions
                });
              }
            });
          }
        };
      }
    }
  ]
});
```

Reference: [GraphQL Complexity Analysis](https://github.com/4Catalyzer/graphql-validation-complexity) | [Securing GraphQL APIs](https://www.apollographql.com/docs/apollo-server/security/authentication/)

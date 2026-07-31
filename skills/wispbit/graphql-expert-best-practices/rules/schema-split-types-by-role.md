---
title: Split Types by Role to Prevent Field Leakage
impact: HIGH
impactDescription: Prevents privacy field leakage and eliminates runtime authorization complexity
tags: schema, security, types, authorization, privacy, interfaces
---

## Split Types by Role to Prevent Field Leakage

**Impact: HIGH (Prevents privacy field leakage and eliminates runtime authorization complexity)**

Split over-generic GraphQL types by role to avoid privacy field leakage and runtime authorization logic. A single type used across multiple contexts with different access levels leads to either exposing private fields inappropriately or requiring complex runtime conditionals in every resolver to hide fields based on context.

**Problem Pattern:**
- Single type (e.g., `User`) used across multiple contexts with different access levels
- Type accumulates fields that only make sense for specific roles
- Resolvers must implement runtime checks to conditionally return null for unauthorized fields
- Easy to accidentally expose private fields in new queries
- Schema doesn't clearly communicate what fields are available in which contexts

**Solution:**
- Create role-specific types that implement a common interface
- Separate concerns by access level and context
- Type system enforces field visibility at schema level
- Each type only contains fields appropriate for its context

**Benefits:**
- **Security by Design**: Type system prevents unauthorized field access
- **Clarity**: Schema clearly shows what fields are available in each context
- **Maintainability**: No scattered runtime authorization checks
- **Performance**: No need to fetch private fields when not needed
- **Documentation**: Self-documenting access patterns
- **Type Safety**: Clients know exactly what fields are available

**When to Split Types:**
- User types with different visibility levels (viewer, public profile, team member)
- Organization types with member vs public views
- Resource types with owner vs collaborator vs public access
- Any type where field visibility varies by context

**Incorrect (Over-generic type with mixed access levels):**

```graphql
# packages/server/graphql/schema.graphql
type Query {
  viewer: User!
  publicProfile(id: ID!): User
  user(id: ID!): User
}

type Team {
  id: ID!
  name: String!
  members: [User!]!
}

# BAD: Over-generic User type with mixed access levels
type User {
  id: ID!
  name: String!
  email: String!                      # Private - shouldn't be in public profile
  hasTwoFactorAuthentication: Boolean  # Private - only for viewer
  billing: Billing!                    # Private - only for viewer
  isTeamAdmin: Boolean                 # Context-specific - only in team context
  lastLoginAt: DateTime                # Private - only for viewer
  avatar: String                       # Public - OK everywhere
  privateNotes: String                 # Private - only for viewer
  # All fields exposed everywhere, requiring runtime checks
}

type Organization {
  id: ID!
  name: String!
  members: [User!]!
  billingInfo: BillingInfo!           # Should only be visible to admins
  apiKeys: [ApiKey!]!                 # Should only be visible to admins
  publicDescription: String!          # Public field
}

type Billing {
  plan: String!
  nextBillingDate: DateTime
  paymentMethod: PaymentMethod
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
import { Service } from '../../service';

// BAD: Runtime checks scattered across every field resolver
export const userResolvers = {
  Query: {
    viewer: async (
      parent: any,
      args: any,
      context: { service: Service; userId: string }
    ) => {
      return await context.service.getUserById(context.userId);
    },

    publicProfile: async (
      parent: any,
      args: { id: string },
      context: { service: Service }
    ) => {
      // Returns same User type but some fields should be hidden
      return await context.service.getUserById(args.id);
    }
  },

  User: {
    // BAD: Every resolver needs authorization logic
    email: async (
      parent: User,
      args: any,
      context: { userId?: string }
    ) => {
      // Runtime check - should this field be visible?
      if (parent.id !== context.userId) {
        return null;  // Hide email from non-owners
      }
      return parent.email;
    },

    hasTwoFactorAuthentication: async (
      parent: User,
      args: any,
      context: { userId?: string }
    ) => {
      // Repeated authorization pattern
      if (parent.id !== context.userId) {
        return null;
      }
      return parent.hasTwoFactorAuthentication;
    },

    billing: async (
      parent: User,
      args: any,
      context: { userId?: string; service: Service }
    ) => {
      // More authorization checks
      if (parent.id !== context.userId) {
        throw new Error('Unauthorized');
      }
      return await context.service.getBilling(parent.id);
    },

    isTeamAdmin: async (
      parent: User,
      args: any,
      context: { teamId?: string; service: Service }
    ) => {
      // Context-dependent field - needs team context
      if (!context.teamId) {
        return null;  // Not in team context
      }
      return await context.service.isTeamAdmin(parent.id, context.teamId);
    },

    // Easy to forget authorization checks and leak private data
    lastLoginAt: async (parent: User) => {
      // SECURITY BUG: Forgot to check authorization!
      return parent.lastLoginAt;
    }
  }
};
```

```typescript
// Example: Client confusion with over-generic types
// What fields can I actually access?

const publicProfile = await client.query({
  query: gql`
    query GetPublicProfile($id: ID!) {
      publicProfile(id: $id) {
        id
        name
        email  # Will this return null? Or error? Unclear!
        hasTwoFactorAuthentication  # Can I request this?
        billing { plan }  # What about this?
      }
    }
  `,
  variables: { id: 'user_123' }
});
// Runtime: Most fields return null or throw errors
// Type system doesn't help prevent this
```

**Correct (Role-specific types with shared interface):**

```graphql
# packages/server/graphql/schema.graphql

# Common interface for shared fields
interface User {
  id: ID!
  name: String!
  avatar: String
}

type Query {
  # Each query returns appropriate type for context
  viewer: Viewer!
  publicProfile(id: ID!): PublicUser
  user(id: ID!): User  # Can return any User interface implementation
}

type Team {
  id: ID!
  name: String!
  # Team context uses TeamMember type
  members: [TeamMember!]!
  owner: TeamMember!
}

# GOOD: Viewer type with all private fields
type Viewer implements User {
  id: ID!
  name: String!
  avatar: String
  # Private fields only in Viewer type
  email: String!
  hasTwoFactorAuthentication: Boolean!
  billing: Billing!
  lastLoginAt: DateTime!
  privateNotes: String
  organizations: [OrganizationMember!]!
}

# GOOD: Public profile with only public fields
type PublicUser implements User {
  id: ID!
  name: String!
  avatar: String
  # Only public fields - no private data
  bio: String
  joinedAt: DateTime!
}

# GOOD: Team member type with team-specific fields
type TeamMember implements User {
  id: ID!
  name: String!
  avatar: String
  # Team-specific fields
  role: TeamRole!
  isTeamAdmin: Boolean!
  joinedTeamAt: DateTime!
  permissions: [TeamPermission!]!
}

enum TeamRole {
  OWNER
  ADMIN
  MEMBER
}

# Organization types also split by role
interface Organization {
  id: ID!
  name: String!
  description: String
}

type OrganizationMember implements Organization {
  id: ID!
  name: String!
  description: String
  # Member-visible fields
  members: [OrganizationMemberUser!]!
  projects: [Project!]!
  role: OrganizationRole!
}

type OrganizationAdmin implements Organization {
  id: ID!
  name: String!
  description: String
  # Admin-visible fields (includes member fields)
  members: [OrganizationMemberUser!]!
  projects: [Project!]!
  role: OrganizationRole!
  # Admin-only fields
  billingInfo: BillingInfo!
  apiKeys: [ApiKey!]!
  auditLog: [AuditLogEntry!]!
}

type OrganizationPublic implements Organization {
  id: ID!
  name: String!
  description: String
  # Public-only fields
  memberCount: Int!
  publicProjects: [Project!]!
}

type Billing {
  plan: String!
  nextBillingDate: DateTime
  paymentMethod: PaymentMethod
}
```

```typescript
// packages/server/src/routes/resolvers/userResolver.ts
import { Service } from '../../service';

// GOOD: No runtime authorization checks needed
export const userResolvers = {
  Query: {
    // Returns Viewer type with all private fields
    viewer: async (
      parent: any,
      args: any,
      context: { service: Service; userId: string }
    ) => {
      const user = await context.service.getUserById(context.userId);
      return {
        ...user,
        __typename: 'Viewer'  // Explicitly return Viewer type
      };
    },

    // Returns PublicUser type with only public fields
    publicProfile: async (
      parent: any,
      args: { id: string },
      context: { service: Service }
    ) => {
      const user = await context.service.getUserById(args.id);
      return {
        id: user.id,
        name: user.name,
        avatar: user.avatar,
        bio: user.bio,
        joinedAt: user.createdAt,
        __typename: 'PublicUser'
      };
    }
  },

  // No field-level resolvers needed - type system handles access control
  Viewer: {
    billing: async (
      parent: any,
      args: any,
      context: { service: Service }
    ) => {
      // This resolver only runs for Viewer type
      // No authorization check needed - type guarantees correct context
      return await context.service.getBilling(parent.id);
    },

    organizations: async (
      parent: any,
      args: any,
      context: { service: Service }
    ) => {
      return await context.service.getUserOrganizations(parent.id);
    }
  },

  PublicUser: {
    // Only resolvers for public data
    // No private fields to worry about
  },

  TeamMember: {
    permissions: async (
      parent: any,
      args: any,
      context: { service: Service; teamId: string }
    ) => {
      // Team context guaranteed - no need to check
      return await context.service.getTeamMemberPermissions(
        parent.id,
        context.teamId
      );
    }
  }
};
```

```typescript
// packages/server/src/routes/resolvers/teamResolver.ts
import { Service } from '../../service';

export const teamResolvers = {
  Team: {
    members: async (
      parent: Team,
      args: any,
      context: { service: Service }
    ) => {
      // Returns TeamMember type with team-specific fields
      const members = await context.service.getTeamMembers(parent.id);

      return members.map(member => ({
        ...member,
        __typename: 'TeamMember'
      }));
    },

    owner: async (
      parent: Team,
      args: any,
      context: { service: Service }
    ) => {
      const owner = await context.service.getTeamOwner(parent.id);
      return {
        ...owner,
        __typename: 'TeamMember'
      };
    }
  }
};
```

```typescript
// Example: Clear client-side code with role-specific types
// Type system knows exactly what fields are available

// Viewer query - can access all private fields
const viewer = await client.query({
  query: gql`
    query GetViewer {
      viewer {
        id
        name
        avatar
        email                      # Available in Viewer
        hasTwoFactorAuthentication # Available in Viewer
        billing {
          plan
          nextBillingDate
        }
        lastLoginAt
      }
    }
  `
});

// Public profile - only public fields available
const publicProfile = await client.query({
  query: gql`
    query GetPublicProfile($id: ID!) {
      publicProfile(id: $id) {
        id
        name
        avatar
        bio
        joinedAt
        # email NOT available - type system prevents request
        # billing NOT available - type system prevents request
      }
    }
  `
});

// Team members - team-specific fields available
const team = await client.query({
  query: gql`
    query GetTeam($id: ID!) {
      team(id: $id) {
        members {
          id
          name
          avatar
          role
          isTeamAdmin
          joinedTeamAt
          # email NOT available in TeamMember type
        }
      }
    }
  `
});
```

```typescript
// Example: Type-safe service layer
interface UserBase {
  id: string;
  name: string;
  avatar: string | null;
}

interface ViewerData extends UserBase {
  email: string;
  hasTwoFactorAuthentication: boolean;
  lastLoginAt: Date;
}

interface PublicUserData extends UserBase {
  bio: string | null;
  joinedAt: Date;
}

interface TeamMemberData extends UserBase {
  role: string;
  isTeamAdmin: boolean;
  joinedTeamAt: Date;
}

class UserService {
  // Different methods return different types
  async getViewerData(userId: string): Promise<ViewerData> {
    // Fetch all private fields
    const user = await this.db.users.findUnique({
      where: { id: userId },
      include: {
        settings: true,
        sessions: true
      }
    });

    return {
      id: user.id,
      name: user.name,
      avatar: user.avatar,
      email: user.email,
      hasTwoFactorAuthentication: user.hasTwoFactorAuthentication,
      lastLoginAt: user.lastLoginAt
    };
  }

  async getPublicUserData(userId: string): Promise<PublicUserData> {
    // Fetch only public fields
    const user = await this.db.users.findUnique({
      where: { id: userId },
      select: {
        id: true,
        name: true,
        avatar: true,
        bio: true,
        createdAt: true
      }
    });

    return {
      id: user.id,
      name: user.name,
      avatar: user.avatar,
      bio: user.bio,
      joinedAt: user.createdAt
    };
  }

  async getTeamMemberData(
    userId: string,
    teamId: string
  ): Promise<TeamMemberData> {
    // Fetch team-specific fields
    const membership = await this.db.teamMembers.findUnique({
      where: { userId_teamId: { userId, teamId } },
      include: { user: true }
    });

    return {
      id: membership.user.id,
      name: membership.user.name,
      avatar: membership.user.avatar,
      role: membership.role,
      isTeamAdmin: membership.role === 'ADMIN',
      joinedTeamAt: membership.joinedAt
    };
  }
}
```

```graphql
# Example: Polymorphic queries with interfaces

type Query {
  # Returns User interface - can be any implementation
  user(id: ID!): User

  # Context-specific queries return specific types
  viewer: Viewer!
  publicProfile(id: ID!): PublicUser
}

# Query can return different types based on authorization
query GetUser($id: ID!) {
  user(id: $id) {
    id
    name
    avatar

    # Type-specific fields using fragments
    ... on Viewer {
      email
      billing { plan }
      hasTwoFactorAuthentication
    }

    ... on PublicUser {
      bio
      joinedAt
    }

    ... on TeamMember {
      role
      isTeamAdmin
      joinedTeamAt
    }
  }
}
```

```typescript
// Resolver that returns different types based on context
export const userResolver = {
  Query: {
    user: async (
      parent: any,
      args: { id: string },
      context: { service: Service; userId?: string }
    ) => {
      // Return appropriate type based on context
      if (args.id === context.userId) {
        // Viewing own profile - return Viewer
        const data = await context.service.getViewerData(args.id);
        return { ...data, __typename: 'Viewer' };
      } else {
        // Viewing other's profile - return PublicUser
        const data = await context.service.getPublicUserData(args.id);
        return { ...data, __typename: 'PublicUser' };
      }
    }
  }
};
```
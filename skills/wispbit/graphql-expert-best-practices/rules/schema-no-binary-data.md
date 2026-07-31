---
title: Avoid Large Binary Data in Schema
impact: CRITICAL
impactDescription: Prevents payload bloat, memory issues, and performance degradation
tags: schema, binary, performance, files, upload
---

## Avoid Large Binary Data in Schema

**Impact: CRITICAL (Prevents payload bloat, memory issues, and performance degradation)**

GraphQL schemas must not include fields or arguments that store large binary data. Use URLs or handles instead of Base64, Bytes, Blob, or large String fields meant for file data. Storing binary data in GraphQL responses dramatically increases payload size, causes memory pressure on servers and clients, and defeats caching strategies.

**File Data Fields to Avoid:**
- `Base64` scalars for file data
- `Bytes` or `Blob` types
- Large `String` fields containing file content
- Direct file payloads in mutation arguments

**Recommended Approach - Two-Step Upload Process:**
1. Generate pre-signed upload URLs via GraphQL
2. Client uploads directly to storage/CDN (bypassing GraphQL server)
3. Client sends metadata/reference back to GraphQL for confirmation

**Benefits of URL References:**
- Dramatically smaller GraphQL payloads (URL vs entire file)
- Direct uploads to CDN/storage reduce server load
- Better caching (URLs can be cached, binary data cannot)
- Parallel uploads don't block GraphQL operations
- Easier to implement resumable uploads
- CDN can handle file serving with proper headers and compression

**Performance Impact:**
- 10MB file as Base64 = ~13.3MB in JSON response
- Same file as URL = ~100 bytes in JSON response
- 100x+ reduction in payload size
- Eliminates server memory pressure from buffering large files

**Incorrect (Storing binary data in schema):**

```graphql
# packages/server/graphql/schema.graphql
scalar Base64
scalar Bytes

type File {
  id: ID!
  name: String!
  data: Base64!  # Stores raw file content - BAD!
  size: Int!
}

type Document {
  id: ID!
  title: String!
  content: Bytes!  # Large binary data - BAD!
}

type ProfileImage {
  id: ID!
  imageData: String!  # Base64 encoded image - BAD!
  thumbnailData: String!  # More binary data - BAD!
}

input FileUploadInput {
  name: String!
  data: Base64!  # File payload in mutation - BAD!
  mimeType: String!
}

type Mutation {
  # Accepts file data directly - causes memory issues
  uploadFile(input: FileUploadInput!): File!

  # Base64 data in mutation argument - bloats request
  createDocument(title: String!, content: Base64!): Document!

  # Multiple file uploads in single mutation - very bad for memory
  uploadProfileImages(avatar: Base64!, banner: Base64!): ProfileImage!
}

type Query {
  # Returns file data inline - bloats response
  file(id: ID!): File!

  # Returns multiple files with data - exponentially worse
  files(ids: [ID!]!): [File!]!
}
```

```typescript
// packages/server/src/routes/resolvers/file.ts
export const fileResolvers = {
  Mutation: {
    uploadFile: async (parent: any, args: { input: FileUploadInput }, context: { service: Service }) => {
      // BAD: Entire file buffered in memory as Base64
      const { name, data, mimeType } = args.input;

      // Decode Base64 (1.33x size in memory)
      const buffer = Buffer.from(data, 'base64');

      // Upload to storage
      const fileId = await context.service.uploadToStorage(buffer, name, mimeType);

      // Return with data still attached (doubles memory usage)
      return {
        id: fileId,
        name,
        data, // Still returning the Base64 data - BAD!
        size: buffer.length
      };
    }
  }
};
```

**Correct (Using URLs and two-step upload):**

```graphql
# packages/server/graphql/schema.graphql
scalar URL

type File {
  id: ID!
  name: String!
  url: URL!  # Reference to stored file location
  size: Int!
  mimeType: String!
  createdAt: Float!
}

type Document {
  id: ID!
  title: String!
  downloadUrl: URL!  # Reference to file location
  fileSize: Int!
}

type ProfileImage {
  id: ID!
  imageUrl: URL!  # URL to full-size image
  thumbnailUrl: URL!  # URL to thumbnail
  width: Int!
  height: Int!
}

type UploadUrlPayload {
  uploadUrl: URL!  # Pre-signed URL for direct upload
  fileId: ID!  # File identifier for confirmation
  expiresAt: Float!  # Upload URL expiration timestamp
}

input CreateFileInput {
  name: String!
  size: Int!
  mimeType: String!
}

type Mutation {
  # Step 1: Returns upload URL for client-side upload
  generateUploadUrl(input: CreateFileInput!): UploadUrlPayload!

  # Step 2: Confirms upload completion with metadata
  confirmFileUpload(fileId: ID!): File!

  # For profile images
  generateProfileImageUploadUrl(imageType: String!): UploadUrlPayload!
}

type Query {
  # Returns file metadata with URL reference
  file(id: ID!): File!

  # Multiple files still lightweight (just URLs)
  files(ids: [ID!]!): [File!]!
}
```

```typescript
// packages/server/src/routes/resolvers/file.ts
import { Service } from '../../service';

interface CreateFileInput {
  name: string;
  size: number;
  mimeType: string;
}

export const fileResolvers = {
  Mutation: {
    generateUploadUrl: async (
      parent: any,
      args: { input: CreateFileInput },
      context: { service: Service, userId: string }
    ) => {
      const { name, size, mimeType } = args.input;

      // Create file record in pending state
      const fileId = await context.service.createPendingFile({
        name,
        size,
        mimeType,
        userId: context.userId
      });

      // Generate pre-signed upload URL (S3, GCS, etc.)
      const uploadUrl = await context.service.generatePresignedUploadUrl({
        fileId,
        mimeType,
        expiresIn: 3600 // 1 hour
      });

      return {
        uploadUrl,
        fileId,
        expiresAt: Date.now() + 3600000
      };
    },

    confirmFileUpload: async (
      parent: any,
      args: { fileId: string },
      context: { service: Service, userId: string }
    ) => {
      // Verify file was uploaded and update status
      const file = await context.service.confirmFileUpload(args.fileId, context.userId);

      // Generate CDN URL for file access
      const url = await context.service.getFileUrl(file.id);

      return {
        id: file.id,
        name: file.name,
        url, // Just a URL, not the file content
        size: file.size,
        mimeType: file.mimeType,
        createdAt: file.createdAt
      };
    }
  },

  Query: {
    file: async (parent: any, args: { id: string }, context: { service: Service }) => {
      const file = await context.service.getFileById(args.id);

      // Generate signed URL for secure access
      const url = await context.service.getFileUrl(file.id);

      return {
        id: file.id,
        name: file.name,
        url, // Lightweight URL reference
        size: file.size,
        mimeType: file.mimeType,
        createdAt: file.createdAt
      };
    }
  }
};
```

```typescript
// Example client-side upload flow
async function uploadFile(file: File) {
  // Step 1: Get upload URL from GraphQL
  const { generateUploadUrl } = await graphqlClient.mutate({
    mutation: GENERATE_UPLOAD_URL,
    variables: {
      input: {
        name: file.name,
        size: file.size,
        mimeType: file.type
      }
    }
  });

  // Step 2: Upload directly to storage (bypasses GraphQL server)
  await fetch(generateUploadUrl.uploadUrl, {
    method: 'PUT',
    body: file,
    headers: {
      'Content-Type': file.type
    }
  });

  // Step 3: Confirm upload via GraphQL
  const { confirmFileUpload } = await graphqlClient.mutate({
    mutation: CONFIRM_FILE_UPLOAD,
    variables: {
      fileId: generateUploadUrl.fileId
    }
  });

  // File is now accessible via URL
  console.log('File URL:', confirmFileUpload.url);
}
```

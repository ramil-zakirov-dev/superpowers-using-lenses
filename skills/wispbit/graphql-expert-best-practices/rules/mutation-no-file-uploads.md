---
title: Avoid File Uploads Through GraphQL
impact: CRITICAL
impactDescription: Prevents memory exhaustion, stream leaks, and security vulnerabilities
tags: mutation, security, files, uploads, memory, performance
---

## Avoid File Uploads Through GraphQL

**Impact: CRITICAL (Prevents memory exhaustion, stream leaks, and security vulnerabilities)**

Avoid implementing file uploads through GraphQL. Use signed URLs with direct storage provider uploads instead. GraphQL was not designed for binary data handling and file uploads introduce significant security and reliability risks including memory exhaustion, stream leaks, CSRF vulnerabilities, and payload attacks.

**Problems with GraphQL File Uploads:**
- **Memory Exhaustion**: Large file uploads consume server memory
- **Stream Leaks**: Improper stream handling leads to memory leaks
- **CSRF Vulnerabilities**: File upload endpoints are CSRF attack vectors
- **Payload Attacks**: Malicious clients can send huge files to exhaust resources
- **Poor Performance**: GraphQL server becomes bottleneck for large files
- **Timeout Issues**: Large uploads can exceed request timeouts
- **No Resume Support**: Failed uploads must restart from beginning
- **Complexity**: Requires multipart/form-data handling, not standard GraphQL

**Recommended Approach (Three-Step Process):**

1. **Request Signed URL**: Create GraphQL mutation to request signed upload URL from storage provider
2. **Direct Upload**: Client uploads file directly to storage (S3, GCS, etc.) using signed URL
3. **Confirm Upload**: Submit GraphQL mutation to associate uploaded file with application data

**Benefits of Signed URL Pattern:**
- Server never handles binary data
- Storage provider handles upload reliability and security
- No memory pressure on GraphQL server
- Can set size limits and content type restrictions
- Resume support via storage provider features
- Parallel uploads don't block GraphQL operations
- CDN integration for global upload performance

**Security Benefits:**
- Storage provider validates file size and content type
- Time-limited signed URLs prevent replay attacks
- No CSRF vulnerabilities (CORS handled by storage provider)
- Can enforce additional security policies at storage layer

**Incorrect (Direct file uploads through GraphQL):**

```graphql
# graphql/schema.graphql
scalar Upload

type Mutation {
  # BAD: Direct file upload through GraphQL
  uploadProfileImage(file: Upload!): User!

  # BAD: Multiple file uploads through GraphQL
  uploadDocuments(files: [Upload!]!): [Document!]!

  # BAD: File upload mixed with mutation data
  createPost(title: String!, content: String!, image: Upload): Post!

  # BAD: Large file upload through GraphQL
  uploadVideo(file: Upload!, title: String!): Video!
}
```

```typescript
// src/resolvers/uploadResolver.ts
import { GraphQLUpload } from 'graphql-upload';
import { FileUpload } from 'graphql-upload';

export const resolvers = {
  Upload: GraphQLUpload,

  Mutation: {
    // BAD: Processing file uploads directly in GraphQL resolver
    uploadProfileImage: async (
      parent: any,
      { file }: { file: Promise<FileUpload> },
      context: { service: Service; userId: string }
    ) => {
      const { createReadStream, filename, mimetype, encoding } = await file;
      const stream = createReadStream();

      // RISK: Entire file buffered in memory
      const chunks: Buffer[] = [];
      for await (const chunk of stream) {
        chunks.push(chunk);
      }
      const buffer = Buffer.concat(chunks);

      // Memory exhaustion with large files
      if (buffer.length > 10 * 1024 * 1024) {
        throw new Error('File too large');
      }

      // GraphQL server handles upload - becomes bottleneck
      const result = await context.service.uploadToS3(buffer, filename, mimetype);

      return await context.service.updateUserProfileImage(
        context.userId,
        result.url
      );
    },

    // BAD: Multiple files through GraphQL
    uploadDocuments: async (
      parent: any,
      { files }: { files: Promise<FileUpload>[] },
      context: { service: Service }
    ) => {
      const results = [];

      for (const filePromise of files) {
        const { createReadStream, filename } = await filePromise;
        const stream = createReadStream();

        // Multiple files in sequence - slow and memory intensive
        const buffer = await streamToBuffer(stream);
        const result = await context.service.uploadDocument(buffer, filename);
        results.push(result);
      }

      return results;
    },

    // BAD: Video upload through GraphQL (very large files)
    uploadVideo: async (
      parent: any,
      { file, title }: { file: Promise<FileUpload>; title: string },
      context: { service: Service }
    ) => {
      const { createReadStream, filename } = await file;
      const stream = createReadStream();

      // CRITICAL: Large video files (100MB+) cause:
      // - Memory exhaustion
      // - Request timeouts
      // - Server crashes
      const buffer = await streamToBuffer(stream);

      return await context.service.uploadVideo(buffer, filename, title);
    }
  }
};

// Helper that loads entire file into memory - DANGEROUS
async function streamToBuffer(stream: NodeJS.ReadableStream): Promise<Buffer> {
  const chunks: Buffer[] = [];
  for await (const chunk of stream) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}
```

```typescript
// src/server.ts
// BAD: graphql-upload middleware

import { graphqlUploadExpress } from 'graphql-upload';

app.use('/graphql', graphqlUploadExpress({ maxFileSize: 10000000, maxFiles: 10 }));
app.use('/graphql', graphqlMiddleware);

// Problems:
// - Server handles all upload traffic
// - Memory exhaustion with concurrent uploads
// - Doesn't scale for high traffic
```

**Correct (Signed URL pattern with direct uploads):**

```graphql
# graphql/schema.graphql

type SignedUploadUrl {
  uploadUrl: String!
  fileKey: String!
  expiresAt: String!
  maxSize: Int!
}

input UploadRequest {
  filename: String!
  contentType: String!
  size: Int!
}

type FileUploadResult {
  id: ID!
  url: String!
  key: String!
  size: Int!
  contentType: String!
}

type Mutation {
  # Step 1: Request signed URL for direct upload
  requestProfileImageUpload(contentType: String!): SignedUploadUrl!

  # Step 2: Confirm upload after client uploads directly to storage
  confirmProfileImageUpload(fileKey: String!): User!

  # Multiple file upload workflow
  requestDocumentUploads(files: [UploadRequest!]!): [SignedUploadUrl!]!
  confirmDocumentUploads(fileKeys: [String!]!): [Document!]!

  # Post creation with optional image
  requestPostImageUpload(contentType: String!): SignedUploadUrl!
  createPost(input: CreatePostInput!): Post!

  # Video upload workflow
  requestVideoUpload(input: VideoUploadRequest!): SignedUploadUrl!
  confirmVideoUpload(fileKey: String!, title: String!): Video!
}

input CreatePostInput {
  title: String!
  content: String!
  imageKey: String  # Reference to uploaded file
}

input VideoUploadRequest {
  filename: String!
  contentType: String!
  size: Int!
  duration: Int
}
```

```typescript
// src/resolvers/uploadResolver.ts
// GOOD: Generate signed URLs, never handle binary data

import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { nanoid } from 'nanoid';

const s3Client = new S3Client({ region: process.env.AWS_REGION });

interface UploadRequest {
  filename: string;
  contentType: string;
  size: number;
}

export const uploadResolvers = {
  Mutation: {
    // GOOD: Generate signed URL - no binary data handling
    requestProfileImageUpload: async (
      parent: any,
      { contentType }: { contentType: string },
      context: { service: Service; userId: string }
    ) => {
      // Validate content type
      const allowedTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
      if (!allowedTypes.includes(contentType)) {
        throw new Error(`Content type ${contentType} not allowed`);
      }

      // Generate unique file key
      const fileKey = `profile-images/${context.userId}/${nanoid()}.${getExtension(contentType)}`;

      // Create S3 put object command
      const command = new PutObjectCommand({
        Bucket: process.env.S3_BUCKET,
        Key: fileKey,
        ContentType: contentType,
        // Security: Add metadata for tracking
        Metadata: {
          userId: context.userId,
          uploadedAt: new Date().toISOString()
        }
      });

      // Generate signed URL (valid for 5 minutes)
      const uploadUrl = await getSignedUrl(s3Client, command, {
        expiresIn: 300
      });

      // Store pending upload in database
      await context.service.createPendingUpload({
        fileKey,
        userId: context.userId,
        contentType,
        maxSize: 5 * 1024 * 1024 // 5MB
      });

      return {
        uploadUrl,
        fileKey,
        expiresAt: new Date(Date.now() + 300000).toISOString(),
        maxSize: 5 * 1024 * 1024
      };
    },

    // GOOD: Confirm upload after client uploads directly
    confirmProfileImageUpload: async (
      parent: any,
      { fileKey }: { fileKey: string },
      context: { service: Service; userId: string }
    ) => {
      // Verify file exists in S3
      const fileExists = await context.service.verifyS3File(fileKey);
      if (!fileExists) {
        throw new Error('File not found or upload failed');
      }

      // Verify user owns this upload
      const pendingUpload = await context.service.getPendingUpload(fileKey);
      if (pendingUpload.userId !== context.userId) {
        throw new Error('Unauthorized');
      }

      // Generate CDN URL for file access
      const cdnUrl = `https://cdn.example.org/${fileKey}`;

      // Update user profile
      const user = await context.service.updateUserProfileImage(
        context.userId,
        cdnUrl,
        fileKey
      );

      // Mark upload as confirmed
      await context.service.confirmUpload(fileKey);

      return user;
    },

    // GOOD: Multiple files - generate multiple signed URLs
    requestDocumentUploads: async (
      parent: any,
      { files }: { files: UploadRequest[] },
      context: { service: Service; userId: string }
    ) => {
      const signedUrls = [];

      for (const fileRequest of files) {
        // Validate file request
        if (fileRequest.size > 50 * 1024 * 1024) {
          throw new Error(`File ${fileRequest.filename} exceeds 50MB limit`);
        }

        const fileKey = `documents/${context.userId}/${nanoid()}-${fileRequest.filename}`;

        const command = new PutObjectCommand({
          Bucket: process.env.S3_BUCKET,
          Key: fileKey,
          ContentType: fileRequest.contentType
        });

        const uploadUrl = await getSignedUrl(s3Client, command, {
          expiresIn: 600 // 10 minutes
        });

        signedUrls.push({
          uploadUrl,
          fileKey,
          expiresAt: new Date(Date.now() + 600000).toISOString(),
          maxSize: 50 * 1024 * 1024
        });
      }

      return signedUrls;
    },

    // GOOD: Post creation with optional pre-uploaded image
    createPost: async (
      parent: any,
      { input }: { input: CreatePostInput },
      context: { service: Service; userId: string }
    ) => {
      const { title, content, imageKey } = input;

      let imageUrl: string | null = null;

      if (imageKey) {
        // Verify image was uploaded
        const fileExists = await context.service.verifyS3File(imageKey);
        if (!fileExists) {
          throw new Error('Image not found');
        }

        imageUrl = `https://cdn.example.org/${imageKey}`;
      }

      return await context.service.createPost({
        title,
        content,
        imageUrl,
        authorId: context.userId
      });
    }
  }
};

function getExtension(contentType: string): string {
  const map: Record<string, string> = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
    'image/gif': 'gif',
    'video/mp4': 'mp4',
    'application/pdf': 'pdf'
  };
  return map[contentType] || 'bin';
}
```

```typescript
// src/hooks/useFileUpload.ts
// GOOD: Client-side upload flow with signed URLs

import { useMutation } from '@apollo/client';
import { REQUEST_UPLOAD_URL, CONFIRM_UPLOAD } from '../graphql/mutations';

export function useFileUpload() {
  const [requestUploadUrl] = useMutation(REQUEST_UPLOAD_URL);
  const [confirmUpload] = useMutation(CONFIRM_UPLOAD);

  async function uploadFile(file: File): Promise<string> {
    // Step 1: Request signed URL from GraphQL
    const { data } = await requestUploadUrl({
      variables: {
        contentType: file.type
      }
    });

    const { uploadUrl, fileKey, maxSize } = data.requestProfileImageUpload;

    // Validate file size client-side
    if (file.size > maxSize) {
      throw new Error(`File size ${file.size} exceeds limit ${maxSize}`);
    }

    // Step 2: Upload directly to S3 (bypasses GraphQL)
    const uploadResponse = await fetch(uploadUrl, {
      method: 'PUT',
      body: file,
      headers: {
        'Content-Type': file.type
      }
    });

    if (!uploadResponse.ok) {
      throw new Error('Upload failed');
    }

    // Step 3: Confirm upload via GraphQL
    await confirmUpload({
      variables: { fileKey }
    });

    return fileKey;
  }

  return { uploadFile };
}

// Usage in component
function ProfileImageUpload() {
  const { uploadFile } = useFileUpload();

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      await uploadFile(file);
      toast.success('Image uploaded successfully');
    } catch (error) {
      toast.error('Upload failed');
    }
  }

  return <input type="file" accept="image/*" onChange={handleFileChange} />;
}
```

```typescript
// Example: Upload progress tracking

async function uploadFileWithProgress(
  file: File,
  onProgress: (percent: number) => void
): Promise<string> {
  // Step 1: Get signed URL
  const { data } = await requestUploadUrl({
    variables: { contentType: file.type }
  });

  const { uploadUrl, fileKey } = data.requestProfileImageUpload;

  // Step 2: Upload with progress tracking
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const percent = (event.loaded / event.total) * 100;
        onProgress(percent);
      }
    });

    xhr.addEventListener('load', async () => {
      if (xhr.status === 200) {
        // Step 3: Confirm upload
        await confirmUpload({ variables: { fileKey } });
        resolve(fileKey);
      } else {
        reject(new Error('Upload failed'));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new Error('Upload failed'));
    });

    xhr.open('PUT', uploadUrl);
    xhr.setRequestHeader('Content-Type', file.type);
    xhr.send(file);
  });
}
```

```typescript
// src/services/storageService.ts
// GOOD: Storage service handles S3 interactions

import { S3Client, HeadObjectCommand, CopyObjectCommand, DeleteObjectCommand } from '@aws-sdk/client-s3';

export class StorageService {
  constructor(private s3Client: S3Client) {}

  async verifyS3File(fileKey: string): Promise<boolean> {
    try {
      await this.s3Client.send(
        new HeadObjectCommand({
          Bucket: process.env.S3_BUCKET,
          Key: fileKey
        })
      );
      return true;
    } catch {
      return false;
    }
  }

  async moveToPermStorage(
    tempFileKey: string,
    permanentPrefix: string
  ): Promise<string> {
    const permanentKey = tempFileKey.replace('temp/', `${permanentPrefix}/`);

    // Copy from temp to permanent location
    await this.s3Client.send(
      new CopyObjectCommand({
        Bucket: process.env.S3_BUCKET,
        CopySource: `${process.env.S3_BUCKET}/${tempFileKey}`,
        Key: permanentKey
      })
    );

    // Delete temp file
    await this.s3Client.send(
      new DeleteObjectCommand({
        Bucket: process.env.S3_BUCKET,
        Key: tempFileKey
      })
    );

    return permanentKey;
  }

  async deleteFile(fileKey: string): Promise<void> {
    await this.s3Client.send(
      new DeleteObjectCommand({
        Bucket: process.env.S3_BUCKET,
        Key: fileKey
      })
    );
  }
}
```

```typescript
// Example: Security and validation

export const uploadResolvers = {
  Mutation: {
    requestProfileImageUpload: async (
      parent: any,
      { contentType }: { contentType: string },
      context: { service: Service; userId: string }
    ) => {
      // Whitelist allowed content types
      const allowedTypes = [
        'image/jpeg',
        'image/png',
        'image/webp',
        'image/gif'
      ];

      if (!allowedTypes.includes(contentType)) {
        throw new Error(
          `Content type ${contentType} not allowed. ` +
          `Allowed types: ${allowedTypes.join(', ')}`
        );
      }

      // Check user's upload quota
      const uploadCount = await context.service.getUserUploadCount(
        context.userId,
        'last_24_hours'
      );

      if (uploadCount >= 100) {
        throw new Error('Upload quota exceeded. Try again later.');
      }

      // Check user's storage usage
      const storageUsed = await context.service.getUserStorageUsage(context.userId);
      const storageLimit = 1024 * 1024 * 1024; // 1GB

      if (storageUsed >= storageLimit) {
        throw new Error('Storage limit exceeded');
      }

      const fileKey = `temp/${context.userId}/${nanoid()}`;

      // Generate signed URL with security constraints
      const command = new PutObjectCommand({
        Bucket: process.env.S3_BUCKET,
        Key: fileKey,
        ContentType: contentType,
        // S3 enforces these limits
        ContentLength: 5 * 1024 * 1024, // Max 5MB
        Metadata: {
          userId: context.userId,
          uploadedAt: new Date().toISOString()
        }
      });

      const uploadUrl = await getSignedUrl(s3Client, command, {
        expiresIn: 300 // 5 minutes
      });

      return {
        uploadUrl,
        fileKey,
        expiresAt: new Date(Date.now() + 300000).toISOString(),
        maxSize: 5 * 1024 * 1024
      };
    }
  }
};
```


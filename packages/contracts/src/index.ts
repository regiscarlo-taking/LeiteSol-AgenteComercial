export type ServiceStatus = "healthy" | "degraded";
export type ChatRole = "assistant" | "user" | "system";
export type ChatAttachmentStatus = "attached" | "reviewed";
export type ChatConversationStatus = "active" | "draft";

export interface BaseRequest<TData = unknown, TMetadata = Record<string, unknown>> {
  data: TData | null;
  metadata?: TMetadata | null;
  traceId?: string | null;
  timestamp?: string | null;
}

export interface BaseResponse<TData = unknown, TMetadata = Record<string, unknown>> {
  data: TData | null;
  statusCode: number;
  message: string;
  error: string | null;
  success: boolean;
  traceId: string;
  timestamp: string;
  metadata?: TMetadata | null;
}

export interface HealthStatus {
  service: string;
  status: ServiceStatus;
  version: string;
}

export interface Measure {
  measureId: string;
  friendlyName: string;
  daxName: string;
  type: string | null;
  unit: string | null;
  functionalRule: string | null;
  daxExpression: string | null;
  baseObject: string | null;
  dependencies: string | null;
  biSource: string | null;
  agentVisible: string | null;
}

export interface ChatAttachment {
  id: string;
  name: string;
  mimeType: string;
  sizeInBytes: number;
  status: ChatAttachmentStatus;
}

export interface ChatSqlResult {
  entity: string;
  sql: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  attachments?: ChatAttachment[] | null;
  sqlResult?: ChatSqlResult | null;
}

export interface ChatConversationSummary {
  id: string;
  title: string;
  lastMessagePreview: string;
  updatedAt: string;
  status: ChatConversationStatus;
}

export interface ChatConversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  status: ChatConversationStatus;
  messages: ChatMessage[];
  suggestedPrompts?: string[] | null;
}

export interface CreateChatRequest {
  title?: string | null;
  initialPrompt?: string | null;
}

export interface SendChatMessageRequest {
  content: string;
  attachments?: ChatAttachment[] | null;
}

export interface SendChatMessageResult {
  conversation: ChatConversation;
  reply: ChatMessage;
}

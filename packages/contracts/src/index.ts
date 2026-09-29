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
  sql?: string | null;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  rowCount: number;
}

// Envelope do POST /perguntas (contrato de dados, §6). Os nomes seguem o
// contrato em snake_case porque é o formato que a API devolve.
export type AgentAnswerStatus =
  | "respondida"
  | "esclarecimento"
  | "fora_de_escopo"
  | "sem_alcada"
  | "erro";

export interface AgentAnswerColumn {
  id: string;
  rotulo: string;
  unidade: string | null;
}

export interface AgentAnswerBlock {
  colunas: AgentAnswerColumn[];
  linhas: Array<Record<string, unknown>>;
}

export interface AgentAnswerNotice {
  codigo: string;
  origem: string;
  texto: string;
}

export interface AgentAnswer {
  correlation_id: string;
  status: AgentAnswerStatus;
  operacao: { id: string; nome_tecnico: string; skill: string } | null;
  parametros_interpretados: Record<string, unknown>;
  periodo: {
    inicio: string;
    fim_exclusivo: string;
    fim_exibicao: string;
    comparacao: { inicio: string; fim_exclusivo: string } | null;
    periodo_parcial: boolean;
    ultima_competencia_fechada: string | null;
  } | null;
  recorte: { tipo: string; descricao: string } | null;
  dados: {
    principal: AgentAnswerBlock;
    excecoes: Array<{ motivo: string; linhas: Array<Record<string, unknown>> }>;
  } | null;
  avisos: AgentAnswerNotice[];
  cobertura: unknown;
  narrativa: string | null;
  pergunta_ao_usuario: string | null;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  attachments?: ChatAttachment[] | null;
  sqlResult?: ChatSqlResult | null;
  agentAnswer?: AgentAnswer | null;
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

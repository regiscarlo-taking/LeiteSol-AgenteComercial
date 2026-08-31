import { z } from "zod";

import type { ChatAttachment, Measure } from "@leitesol/contracts";

export const chatFormSchema = z.object({
  userId: z.string().trim().min(3, "Informe um identificador de usuário válido."),
  message: z.string().trim().min(1, "Digite a mensagem para enviar."),
});

export type ChatFormValues = z.infer<typeof chatFormSchema>;

export interface ChatSendCommand {
  userId: string;
  content: string;
  attachments: ChatAttachment[];
}

export const toChatSendCommand = ({
  userId,
  message,
  attachments,
}: ChatFormValues & { attachments: ChatAttachment[] }): ChatSendCommand => ({
  userId,
  content: message,
  attachments,
});

export const buildBackendChatReply = (message: string, measures: Measure[]): string => {
  const baseMeasures = measures.slice(0, 5);
  const summary =
    baseMeasures.length > 0
      ? baseMeasures
          .map((measure) => `${measure.friendlyName ?? measure.measureId} (${measure.daxName ?? "sem dax"})`)
          .join("; ")
      : "Nenhuma medida retornada pela consulta real do backend.";

  return [
    "Resposta real do backend LeiteSol.",
    `Consulta recebida: "${message.trim()}"`,
    `Medidas retornadas: ${summary}`,
    `Total disponível: ${measures.length} registros consultados via /fabric/measures.`,
  ].join("\n\n");
};

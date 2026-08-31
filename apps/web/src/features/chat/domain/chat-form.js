import { z } from "zod";
export const chatFormSchema = z.object({
    userId: z.string().trim().min(3, "Informe um identificador de usuário válido."),
    message: z.string().trim().min(1, "Digite a mensagem para enviar."),
});
export const toChatSendCommand = ({ userId, message, attachments, }) => ({
    userId,
    content: message,
    attachments,
});
export const buildBackendChatReply = (message, measures) => {
    const baseMeasures = measures.slice(0, 5);
    const summary = baseMeasures.length > 0
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

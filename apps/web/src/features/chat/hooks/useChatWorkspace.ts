import {
  startTransition,
  useRef,
  useState,
  type ChangeEvent,
} from "react";

import type {
  ChartSpecification,
  ChatAttachment,
  ChatConversation,
  ChatConversationSummary,
  CreateChartRequest,
} from "@leitesol/contracts";

import { createChart, queryChat } from "../../../shared/api";

import {
  chatFormSchema,
  type ChatFormValues,
} from "../domain/chat-form";

const formatTime = (value: string): string =>
  new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));

const buildAttachmentFromFile = (file: File): ChatAttachment => ({
  id: `attachment-${crypto.randomUUID()}`,
  name: file.name,
  mimeType: file.type || "application/octet-stream",
  sizeInBytes: file.size,
  status: "attached",
});

const createLocalConversation = (): ChatConversation => {
  const now = new Date().toISOString();

  return {
    id: `chat-${crypto.randomUUID()}`,
    title: "Nova consulta comercial",
    createdAt: now,
    updatedAt: now,
    status: "active",
    messages: [],
  };
};

const toConversationSummary = (
  conversation: ChatConversation,
): ChatConversationSummary => {
  const lastMessage =
    conversation.messages[conversation.messages.length - 1];

  return {
    id: conversation.id,
    title: conversation.title,
    lastMessagePreview:
      lastMessage?.content.slice(0, 96) ?? "Sem mensagens ainda.",
    updatedAt: conversation.updatedAt,
    status: conversation.status,
  };
};

const buildComparisonChartRequest = (
  columns: string[],
  rows: Array<Record<string, unknown>>,
  question: string,
): CreateChartRequest | null => {
  const metricPreference = /\b(?:kg|quilo|kilo|volume)\b/i.test(question)
    ? "kg"
    : /\b(?:tonelada|toneladas|tons?)\b/i.test(question)
      ? "tons"
      : "r\\$";
  const metricPatterns = [
    {
      key: "r\\$",
      current: /^(?:fat\s*r\$|fat_rs)(?:\s+|_)atual$/i,
      previous: /^(?:fat\s*r\$|fat_rs)(?:\s+|_)ano anterior$/i,
      label: "FAT R$",
    },
    {
      key: "kg",
      current: /^(?:fat\s*kg|fat_kg)(?:\s+|_)atual$/i,
      previous: /^(?:fat\s*kg|fat_kg)(?:\s+|_)ano anterior$/i,
      label: "FAT KG",
    },
    {
      key: "tons",
      current: /^(?:fat\s*tons?|fat_tons?)(?:\s+|_)atual$/i,
      previous: /^(?:fat\s*tons?|fat_tons?)(?:\s+|_)ano anterior$/i,
      label: "FAT TONS",
    },
  ];
  const orderedMetrics = [
    ...metricPatterns.filter((metric) => metric.key === metricPreference),
    ...metricPatterns.filter((metric) => metric.key !== metricPreference),
  ];
  const selectedMetric = orderedMetrics
    .map((metric) => ({
      metric,
      currentColumn: columns.find((column) =>
        metric.current.test(column),
      ),
      previousColumn: columns.find((column) =>
        metric.previous.test(column),
      ),
    }))
    .find(
      (pair) =>
        pair.currentColumn !== undefined &&
        pair.previousColumn !== undefined,
    );

  if (!selectedMetric?.currentColumn || !selectedMetric.previousColumn) {
    return null;
  }

  const monthColumn = columns.find((column) => /compet[eê]ncia/i.test(column));
  if (monthColumn) {
    const monthRows = rows.filter(
      (row) =>
        typeof row[monthColumn] === "string" &&
        !/total do per[ií]odo/i.test(row[monthColumn]),
    );
    if (monthRows.length > 0) {
      return {
        columns,
        rows: monthRows,
        categoryColumn: monthColumn,
        valueColumns: [
          selectedMetric.currentColumn,
          selectedMetric.previousColumn,
        ],
        chartType: "line",
        title: `Comparativo mensal de ${selectedMetric.metric.label}`,
      };
    }
  }

  const categoryColumn = columns.find(
    (column) =>
      !/^(?:fat\s*(?:r\$|kg|tons?)|fat_(?:rs|kg|tons?))(?:\s+|_)(?:atual|ano anterior|varia[çc][ãa]o)/i.test(
        column,
      ) &&
      !/(?:^|_)(?:id|codigo|código)$/i.test(column) &&
      /cliente|produto|regi[aã]o|munic[ií]pio|^uf$|vendedor|representante/i.test(
        column,
      ),
  );
  const title = `Comparativo de ${selectedMetric.metric.label}`;

  if (categoryColumn) {
    return {
      columns,
      rows,
      categoryColumn,
      valueColumns: [
        selectedMetric.currentColumn,
        selectedMetric.previousColumn,
      ],
      chartType: "bar",
      title,
    };
  }

  const currentValue = rows[0]?.[selectedMetric.currentColumn];
  const previousValue = rows[0]?.[selectedMetric.previousColumn];
  if (
    typeof currentValue !== "number" ||
    typeof previousValue !== "number"
  ) {
    return null;
  }

  const valueColumn = selectedMetric.metric.label;
  return {
    columns: ["Período", valueColumn],
    rows: [
      { Período: "Período atual", [valueColumn]: currentValue },
      { Período: "Mesmo período do ano anterior", [valueColumn]: previousValue },
    ],
    categoryColumn: "Período",
    valueColumns: [valueColumn],
    chartType: "bar",
    title,
  };
};

export const useChatWorkspace = () => {
  const [activeChat, setActiveChat] =
    useState<ChatConversation | null>(null);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const chats: ChatConversationSummary[] = activeChat
    ? [toConversationSummary(activeChat)]
    : [];

  const openChat = async (chatId: string) => {
    if (!activeChat || activeChat.id !== chatId) {
      return;
    }

    setError("");
  };

  const handleCreateChat = async () => {
    setBusy(false);
    setError("");

    startTransition(() => {
      setActiveChat(null);
      setDraft("");
      setAttachments([]);
    });
  };

  const handleFileSelection = (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const selectedFiles = Array.from(
      event.target.files ?? [],
    ).map(buildAttachmentFromFile);

    if (selectedFiles.length === 0) {
      return;
    }

    setAttachments((currentAttachments) => [
      ...currentAttachments,
      ...selectedFiles,
    ]);

    event.target.value = "";
  };

  const removeAttachment = (attachmentId: string) => {
    setAttachments((currentAttachments) =>
      currentAttachments.filter(
        (attachment) => attachment.id !== attachmentId,
      ),
    );
  };

  const appendTranscript = (transcript: string) => {
    const cleaned = transcript.trim();
    if (!cleaned) {
      return;
    }
    setDraft((current) =>
      current
        ? `${current}${/\s$/.test(current) ? "" : " "}${cleaned}`
        : cleaned,
    );
  };

  const sendMessage = async () => {
    const parsed = chatFormSchema.safeParse({
      userId: "authenticated-user",
      message: draft,
    } satisfies ChatFormValues);

    if (!parsed.success) {
      setError(
        parsed.error.issues[0]?.message ??
          "Dados inválidos para envio.",
      );
      return;
    }

    if (!draft.trim() && attachments.length === 0) {
      return;
    }

    setBusy(true);
    setError("");

    try {
      const currentChat =
        activeChat ?? createLocalConversation();

      const userMessage = {
        id: `user-${crypto.randomUUID()}`,
        role: "user" as const,
        content: parsed.data.message,
        createdAt: new Date().toISOString(),
        attachments:
          attachments.length > 0 ? attachments : null,
      };

      const chatResponse = await queryChat(
        parsed.data.message,
        currentChat.id,
      );
      const sqlResult = chatResponse.data?.sqlResult ?? null;
      let chart: ChartSpecification | null = null;
      let chartError: string | null = null;

      if (sqlResult?.operationId === "OP17" && sqlResult.rows.length > 0) {
        const categoryColumn =
          sqlResult.columns.find((column) => /compet[eê]ncia/i.test(column)) ??
          sqlResult.columns[0];
        const metricColumns = sqlResult.columns.filter(
          (column) =>
            column !== categoryColumn &&
            !/varia[çc][ãa]o/i.test(column) &&
            sqlResult.rows.some((row) => typeof row[column] === "number"),
        );
        const valueColumn =
          metricColumns.find((column) => /FAT R\$/i.test(column)) ??
          metricColumns[0];

        if (categoryColumn && valueColumn) {
          try {
            const chartResponse = await createChart({
              columns: sqlResult.columns,
              rows: sqlResult.rows,
              categoryColumn,
              valueColumns: [valueColumn],
              chartType: "line",
              title: `Evolução mensal de ${valueColumn}`,
            });
            chart = chartResponse.data;
            if (!chart) {
              chartError = "A API não retornou os dados do gráfico.";
            }
          } catch (chartRequestError) {
            chartError =
              chartRequestError instanceof Error
                ? chartRequestError.message
                : "Não foi possível gerar o gráfico.";
          }
        } else {
          chartError = "O resultado não contém dados suficientes para gerar o gráfico.";
        }
      } else if (
        sqlResult?.operationId === "OP12" &&
        sqlResult.rows.length > 0
      ) {
        const chartRequest = buildComparisonChartRequest(
          sqlResult.columns,
          sqlResult.rows,
          parsed.data.message,
        );
        if (chartRequest) {
          try {
            const chartResponse = await createChart(chartRequest);
            chart = chartResponse.data;
            if (!chart) {
              chartError = "A API não retornou os dados do gráfico.";
            }
          } catch (chartRequestError) {
            chartError =
              chartRequestError instanceof Error
                ? chartRequestError.message
                : "Não foi possível gerar o gráfico.";
          }
        } else {
          chartError =
            "O resultado não contém uma métrica comparável para gerar o gráfico.";
        }
      }

      const backendContent =
        chatResponse.data?.answer ??
        "Nenhuma resposta retornada.";

      const assistantMessage = {
        id: `assistant-${crypto.randomUUID()}`,
        role: "assistant" as const,
        content: backendContent,
        createdAt: new Date().toISOString(),
        attachments: null,
        sqlResult,
        chart,
        chartError,
      };

      const updatedConversation: ChatConversation = {
        ...currentChat,
        title:
          currentChat.messages.length === 0
            ? parsed.data.message.slice(0, 60)
            : currentChat.title,
        updatedAt: new Date().toISOString(),
        status: "active",
        messages: [
          ...currentChat.messages,
          userMessage,
          assistantMessage,
        ],
      };

      startTransition(() => {
        setActiveChat(updatedConversation);
        setDraft("");
        setAttachments([]);
      });
    } catch (requestError) {
      setError(
        (requestError as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };

  return {
    activeChat,
    appendTranscript,
    attachments,
    busy,
    chats,
    draft,
    error,
    fileInputRef,
    formatTime,
    handleCreateChat,
    handleFileSelection,
    openChat,
    removeAttachment,
    sendMessage,
    setDraft,
  };
};
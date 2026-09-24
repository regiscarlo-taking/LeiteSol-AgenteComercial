import type { AgentAnswer, AgentAnswerColumn } from "@leitesol/contracts";

const numberFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const moneyFormat = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

const formatCell = (value: unknown, column: AgentAnswerColumn): string => {
  if (value === null || value === undefined) return "—";
  if (typeof value !== "number") return String(value);
  if (column.unidade === "R$") return moneyFormat.format(value);
  if (column.unidade === "%") return `${numberFormat.format(value)}%`;
  if (column.unidade) return `${numberFormat.format(value)} ${column.unidade}`;
  return numberFormat.format(value);
};

const formatDate = (value: string): string =>
  new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));

const ResultTable = ({
  columns,
  rows,
}: {
  columns: AgentAnswerColumn[];
  rows: Array<Record<string, unknown>>;
}) => (
  <div className="result-table-wrap">
    <table>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.id}>{column.rotulo}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={column.id}>{formatCell(row[column.id], column)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

// Mostra o que o envelope do /perguntas traz além da narrativa: período,
// recorte, tabela principal, exceções (fora do ranking) e avisos do catálogo.
export const AgentAnswerView = ({ answer }: { answer: AgentAnswer }) => {
  const { periodo, recorte, dados, avisos } = answer;

  return (
    <section className="query-result agent-answer">
      {periodo || recorte ? (
        <p className="agent-answer-context">
          {periodo
            ? `Período: ${formatDate(periodo.inicio)} a ${formatDate(periodo.fim_exibicao)}`
            : null}
          {periodo?.comparacao
            ? ` · comparado com ${formatDate(periodo.comparacao.inicio)} a ${formatDate(
                new Date(Date.parse(`${periodo.comparacao.fim_exclusivo}T00:00:00Z`) - 86_400_000)
                  .toISOString()
                  .slice(0, 10),
              )}`
            : null}
          {recorte ? ` · ${recorte.descricao}` : null}
        </p>
      ) : null}

      {dados && dados.principal.linhas.length > 0 ? (
        <ResultTable columns={dados.principal.colunas} rows={dados.principal.linhas} />
      ) : null}

      {dados?.excecoes.map((block) => (
        <div key={block.motivo} className="agent-answer-exceptions">
          <strong>{block.motivo}</strong>
          <ResultTable columns={dados.principal.colunas} rows={block.linhas} />
        </div>
      ))}

      {avisos.length > 0 ? (
        <ul className="agent-answer-notices">
          {avisos.map((notice) => (
            <li key={`${notice.codigo}-${notice.texto}`}>{notice.texto}</li>
          ))}
        </ul>
      ) : null}

      <small>Protocolo: {answer.correlation_id}</small>
    </section>
  );
};

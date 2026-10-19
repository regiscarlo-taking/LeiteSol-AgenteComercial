# Agent

O agente comercial, como biblioteca Python. A API (`apps/api`) importa este pacote
e entrega a ele a conexão com o Warehouse, a alçada do usuário e a chave do Gemini.

## O que fica aqui

| Pasta | Conteúdo |
| --- | --- |
| `domain/models.py` | Catálogo, operação, parâmetro, alçada, período e o envelope da resposta |
| `domain/usage.py` | Consumo da LLM por pergunta (chamadas e tokens) |
| `application/answer_question.py` | O fluxo de uma pergunta: alçada, intenção, parâmetros, execução, ressalvas e redação |
| `application/parameters.py` | Validação do que a LLM extraiu contra o catálogo |
| `application/where_filters.py` | Filtros `WHERE` estruturados, allowlist de campos/operações e validação |
| `application/charts.py` | Conversão de resultados tabulares em especificações de gráfico JSON |
| `application/operations/` | Operações com SQL fixo e regra de negócio; inclui executores do catálogo e análises locais de dimensões fechadas |
| `infrastructure/catalog.py` | Leitura do catálogo `IA_COMERCIAL.AGT_*`, com cache |
| `infrastructure/gemini.py` | Provedor Gemini: classificar, extrair parâmetros, redigir |
| `infrastructure/view_knowledge.py` | Contexto local recuperável das views a partir do mapeamento comercial |

## O que fica na API

Autenticação, resolução da alçada (`ScopeResolver`), conexão com o Fabric, Key Vault,
Blob Storage, rotas HTTP e o registro de consumo. O agente não lê variável de ambiente
nem abre conexão: recebe tudo pelo construtor de `AnswerQuestion`.

## Regras do fluxo

- A LLM escolhe uma **operação** de uma lista fechada e propõe parâmetros. Ela não
  escreve SQL e não produz número. O contexto de views é recuperado por relevância
  para classificação e extração, sem enviar o documento inteiro em toda chamada.
- Filtros adicionais são extraídos como condições estruturadas `where` (campo,
  operador e valor). O agente valida campo e operador em uma allowlist derivada das
  views suportadas; todos os valores entram no SQL como parâmetros. SQL livre,
  colunas arbitrárias e filtros que tentem substituir a alçada não são aceitos.
- Todo SQL está no código das operações, parametrizado, sobre as views `vw_*`. As
  junções e as regras de negócio vivem nas views e nas operações.
- Os filtros de localização usam a UF/região/município cadastrais do cliente; não
  confundem o cadastro com a UF em que a venda foi registrada. O calendário mantém
  o grão mensal, e termos de produto continuam sujeitos ao vocabulário cadastrado.
- Sem alçada resolvida, não há consulta.
- O texto da resposta é redigido depois, a partir do resultado.
- OP14 ranqueia representantes por uma métrica explícita (FAT KG ou FAT R$);
  o indicador composto continua bloqueado até homologação. A janela padrão é
  de três competências fechadas. A venda é creditada ao vendedor atual do
  cliente (`c.RCAAtual`), o mesmo usado na alçada; o vendedor da transação só
  entra com `tipo_atribuicao=vendedor_da_venda`, para conferência.
- O catálogo recebido do Fabric é complementado em memória por
  `APP_SALES_BREAKDOWN`, uma
  operação local fixa para ranking por produto, totais por UF/região/município
  e produtos por UF. Não é necessário cadastrar SQL nem permitir SQL livre:
  suas dimensões e agregações são uma lista fechada no código. O padrão é FAT
  KG, UF cadastral do cliente quando não for especificado o nível geográfico,
  e três competências fechadas; são aceitas janelas de 3, 6, 9 ou 12 meses.
  Pedido explícito por região usa `Regiao` de `vw_dim_cliente`, derivada de
  `IA_COMUM.ESTADOS.REGIAO` pela UF cadastral. Produtos são Top 20 e produto
  por UF é Top 5 por UF, salvo limite explicitamente solicitado.
- Totais absolutos por região não substituem a comparação regional histórica
  OP16, que compara cada região com a própria média; usam a UF cadastral
  (`c.UF`), não a UF da transação (`f.UFVenda`).

## Cobertura do glossário (19-10)

As 22 perguntas da Fase 1 têm executor (OP01–OP22). As 15 que entraram em 19-10
(OP02–OP10, OP15, OP16, OP19–OP22) compartilham `application/operations/analytics.py`:

- **Cálculo puro** (`abc_curve`, `frequency_class`, `classify_ticket`,
  `seasonal_profile`, `growth_criteria`, `turnover_status`, `product_trend_status`…):
  recebe números e devolve números ou rótulos, sem banco. O SQL de cada operação
  só agrega.
- **Série mensal genérica** (`monthly_query` + `pivot`): FAT R$ e FAT KG por chave
  e competência no universo comum, com mês sem movimento valendo zero.
- **Regra não fechada com a área comercial:** a operação anexa
  `open_rule_notice(...)`, aviso `REGRA_EM_ABERTO` ("Regra ainda não fechada por
  completo… O resultado é informativo até a homologação"). Hoje: tolerância de
  estabilidade (OP04, OP16), ±2% e metades do ticket (OP07), índice sazonal sem
  validação com casos reais (OP08), fórmula de tendência (OP19), canal = segmento
  (OP20), medida de giro (OP21) e mapa de complementares (OP22). Valor líquido
  negativo fora da curva ABC recebe `VALOR_NEGATIVO` (P-NEGATIVO).
- O motivo da ausência de itens (OP10) e a cobertura "20% → 60%" (OP22) ficam
  fora: o primeiro é Fase 2/3 do glossário; o segundo foi descartado em 22-07.

## Nova operação

1. Cadastrar a operação e os parâmetros no catálogo (`AGT_OPERACAO`, `AGT_OPERACAO_PARAMETRO`).
2. Criar a classe em `application/operations/`, reaproveitando `common.py` e
   `analytics.py`; a regra de classificação vai como função pura em `analytics.py`.
3. Registrá-la em `application/operations/__init__.py`.
4. Cobrir com teste em `tests/`: funções puras em `test_analytics.py`, operação
   em `test_operations_fase1.py` (ou arquivo próprio), com funções de teste soltas
   e o banco falso `fake_fetcher` do `conftest.py`, que confere `?` × parâmetros.

## Testes

```bash
uv run pytest apps/agent/tests
```

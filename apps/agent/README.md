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
| `application/operations/` | Uma classe por operação do catálogo, com o SQL fixo e a regra de negócio |
| `infrastructure/catalog.py` | Leitura do catálogo `IA_COMERCIAL.AGT_*`, com cache |
| `infrastructure/gemini.py` | Provedor Gemini: classificar, extrair parâmetros, redigir |

## O que fica na API

Autenticação, resolução da alçada (`ScopeResolver`), conexão com o Fabric, Key Vault,
Blob Storage, rotas HTTP e o registro de consumo. O agente não lê variável de ambiente
nem abre conexão: recebe tudo pelo construtor de `AnswerQuestion`.

## Regras do fluxo

- A LLM escolhe uma **operação** de uma lista fechada e propõe parâmetros. Ela não
  escreve SQL e não produz número.
- Todo SQL está no código das operações, parametrizado, sobre as views `vw_*`. As
  junções e as regras de negócio vivem nas views e nas operações.
- Sem alçada resolvida, não há consulta.
- O texto da resposta é redigido depois, a partir do resultado.

## Nova operação

1. Cadastrar a operação e os parâmetros no catálogo (`AGT_OPERACAO`, `AGT_OPERACAO_PARAMETRO`).
2. Criar a classe em `application/operations/`, reaproveitando `common.py`.
3. Registrá-la em `application/operations/__init__.py`.
4. Cobrir com teste em `tests/`.

## Testes

```bash
uv run pytest apps/agent/tests
```

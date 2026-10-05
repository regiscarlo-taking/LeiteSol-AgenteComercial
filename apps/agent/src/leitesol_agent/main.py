"""O agente é uma biblioteca: a API o importa e injeta banco, alçada e LLM.

Rodar o módulo lista as operações que têm execução nesta versão.
"""

from leitesol_agent.application.operations import OPERATION_HANDLERS


def main() -> None:
    for operation_id in sorted(OPERATION_HANDLERS):
        print(operation_id, type(OPERATION_HANDLERS[operation_id]).__name__)


if __name__ == "__main__":
    main()

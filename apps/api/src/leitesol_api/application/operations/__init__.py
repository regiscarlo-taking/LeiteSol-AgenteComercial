from leitesol_api.application.operations.base import OperationHandler
from leitesol_api.application.operations.compare_previous_year import CompareWithPreviousYear

# Operações do catálogo com executor implementado. As demais são reconhecidas
# pelo classificador, mas respondem que ainda não estão disponíveis.
OPERATION_HANDLERS: dict[str, OperationHandler] = {
    handler.operation_id: handler for handler in (CompareWithPreviousYear(),)
}

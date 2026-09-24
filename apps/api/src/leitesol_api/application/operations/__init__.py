from leitesol_api.application.operations.base import OperationHandler
from leitesol_api.application.operations.compare_previous_year import CompareWithPreviousYear
from leitesol_api.application.operations.monthly_series import MonthlySeries
from leitesol_api.application.operations.rank_clients import RankClients
from leitesol_api.application.operations.returning_clients import ReturningClients
from leitesol_api.application.operations.sellers_below_average import SellersBelowAverage

# Operações do catálogo com executor implementado. As demais são reconhecidas
# pelo classificador, mas respondem que ainda não estão disponíveis.
OPERATION_HANDLERS: dict[str, OperationHandler] = {
    handler.operation_id: handler
    for handler in (
        ReturningClients(),
        CompareWithPreviousYear(),
        RankClients(),
        MonthlySeries(),
        SellersBelowAverage(),
    )
}

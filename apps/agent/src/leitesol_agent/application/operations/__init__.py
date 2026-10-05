from leitesol_agent.application.operations.base import OperationHandler
from leitesol_agent.application.operations.compare_previous_year import CompareWithPreviousYear
from leitesol_agent.application.operations.monthly_series import MonthlySeries
from leitesol_agent.application.operations.rank_clients import RankClients
from leitesol_agent.application.operations.returning_clients import ReturningClients
from leitesol_agent.application.operations.sellers_below_average import SellersBelowAverage

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

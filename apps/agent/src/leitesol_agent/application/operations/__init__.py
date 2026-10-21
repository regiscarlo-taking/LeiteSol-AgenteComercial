from leitesol_agent.application.operations.abc_curve import AbcCurve
from leitesol_agent.application.operations.average_price_per_kg import AveragePricePerKg
from leitesol_agent.application.operations.base import OperationHandler
from leitesol_agent.application.operations.channel_performance import ChannelPerformance
from leitesol_agent.application.operations.client_product_trend import ClientProductTrend
from leitesol_agent.application.operations.client_vs_average import CompareClientsWithAverage
from leitesol_agent.application.operations.compare_previous_year import CompareWithPreviousYear
from leitesol_agent.application.operations.growth_candidates import GrowthCandidates
from leitesol_agent.application.operations.low_turnover import LowTurnover
from leitesol_agent.application.operations.mix_expansion import MixExpansion
from leitesol_agent.application.operations.monthly_series import MonthlySeries
from leitesol_agent.application.operations.non_positivated import ListNonPositivated
from leitesol_agent.application.operations.product_absence import MissingItems, ProductChurn
from leitesol_agent.application.operations.product_mix import ProductMix
from leitesol_agent.application.operations.purchase_frequency import PurchaseFrequency
from leitesol_agent.application.operations.rank_clients import RankClients
from leitesol_agent.application.operations.rank_representatives import RankRepresentatives
from leitesol_agent.application.operations.regional_performance import RegionalPerformance
from leitesol_agent.application.operations.returning_clients import ReturningClients
from leitesol_agent.application.operations.sales_breakdowns import SalesBreakdowns
from leitesol_agent.application.operations.seasonality import Seasonality
from leitesol_agent.application.operations.seller_evolution import SellerEvolution
from leitesol_agent.application.operations.sellers_below_average import SellersBelowAverage
from leitesol_agent.application.operations.ticket_trend import TicketTrend

# Operações do catálogo com executor implementado: as 22 da Fase 1 do
# glossário (OP01-OP22) e as duas análises locais da aplicação. Operação sem
# executor continua respondendo que ainda não está disponível.
OPERATION_HANDLERS: dict[str, OperationHandler] = {
    handler.operation_id: handler
    for handler in (
        ReturningClients(),
        CompareClientsWithAverage(),
        ListNonPositivated(),
        ClientProductTrend(),
        AbcCurve(),
        PurchaseFrequency(),
        TicketTrend(),
        Seasonality(),
        ProductChurn(),
        MissingItems(),
        ProductMix(),
        CompareWithPreviousYear(),
        RankClients(),
        RankRepresentatives(),
        SellerEvolution(),
        RegionalPerformance(),
        MonthlySeries(),
        SellersBelowAverage(),
        GrowthCandidates(),
        ChannelPerformance(),
        LowTurnover(),
        MixExpansion(),
        SalesBreakdowns(),
        AveragePricePerKg(),
    )
}

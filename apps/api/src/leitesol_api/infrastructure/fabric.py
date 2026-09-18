from collections.abc import Mapping
import logging
from typing import Any

from leitesol_api.domain.measure import Measure

logger = logging.getLogger("leitesol.api.fabric")


class FabricConnectionError(RuntimeError):
    pass


class FabricSqlConnection:
    def __init__(
        self,
        *,
        server: str,
        database: str,
        driver: str,
        authentication: str,
        client_id: str,
        tenant_id: str,
        client_secret: str,
        timeout: int,
    ) -> None:
        self._server = server
        self._database = database
        self._driver = driver
        self._authentication = authentication
        self._client_id = client_id
        self._tenant_id = tenant_id
        # O compose usa $$ para preservar cifrões no .env; normalize antes do ODBC.
        self._client_secret = client_secret.replace("$$", "$")
        self._timeout = timeout

    def _connection_string(self) -> str:
        return (
            f"DRIVER={{{self._driver}}};"
            f"SERVER={self._server};"
            f"DATABASE={self._database};"
            f"Authentication={self._authentication};"
            f"UID={self._client_id}@{self._tenant_id};"
            f"PWD={self._client_secret};"
            "Encrypt=yes;TrustServerCertificate=no;"
        )

    def list_top(self, limit: int = 100) -> list[Measure]:
        limit = min(max(limit, 1), 100)
        try:
            import pyodbc

            connection = pyodbc.connect(self._connection_string(), timeout=self._timeout)
        except Exception as error:
            logger.exception(
                "Fabric connection failed server=%s database=%s driver=%s",
                self._server,
                self._database,
                self._driver,
            )
            raise FabricConnectionError("Unable to connect to the Fabric warehouse.") from error

        query = f"""
            SELECT TOP {limit}
                medida_id, nome_amigavel, nome_dax, tipo, unidade,
                regra_funcional, expressao_dax, objeto_base, dependencias,
                origem_bi, visivel_agente
            FROM [IA_COMERCIAL].[AGT_MEDIDA]
        """

        try:
            with connection:
                cursor = connection.cursor()
                cursor.execute(query)
                columns = [column[0] for column in cursor.description]
                return [self._to_measure(dict(zip(columns, row))) for row in cursor.fetchall()]
        except Exception as error:
            logger.exception(
                "Fabric query failed database=%s table=IA_COMERCIAL.AGT_MEDIDA",
                self._database,
            )
            raise FabricConnectionError("Unable to query measures from the Fabric warehouse.") from error

    @staticmethod
    def _to_measure(row: Mapping[str, Any]) -> Measure:
        return Measure(
            measure_id=row["medida_id"],
            friendly_name=row["nome_amigavel"],
            dax_name=row["nome_dax"],
            measure_type=row["tipo"],
            unit=row["unidade"],
            functional_rule=row["regra_funcional"],
            dax_expression=row["expressao_dax"],
            base_object=row["objeto_base"],
            dependencies=row["dependencias"],
            bi_source=row["origem_bi"],
            agent_visible=row["visivel_agente"],
        )
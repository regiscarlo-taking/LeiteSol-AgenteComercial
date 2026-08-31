from collections.abc import Mapping
import struct
from typing import Any

from leitesol_api.domain.measure import Measure
from leitesol_api.infrastructure.entra_id import AccessTokenProvider


class FabricConnectionError(RuntimeError):
    pass


class FabricSqlConnection:
    def __init__(
        self,
        *,
        server: str,
        database: str,
        driver: str,
        timeout: int,
        access_token_provider: AccessTokenProvider,
    ) -> None:
        self._server = server
        self._database = database
        self._driver = driver
        self._timeout = timeout
        self._access_token_provider = access_token_provider

    def _connection_string(self) -> str:
        return (
            f"DRIVER={{{self._driver}}};"
            f"SERVER={self._server};"
            f"DATABASE={self._database};"
            "Encrypt=yes;TrustServerCertificate=no;"
        )

    def _access_token_attributes(self) -> dict[int, bytes]:
        token = self._access_token_provider.get_token().encode("utf-16-le")
        return {1256: struct.pack(f"<I{len(token)}s", len(token), token)}

    def list_top(self, limit: int = 100) -> list[Measure]:
        limit = min(max(limit, 1), 100)
        try:
            import pyodbc

            connection = pyodbc.connect(
                self._connection_string(),
                attrs_before=self._access_token_attributes(),
                timeout=self._timeout,
            )
        except Exception as error:
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
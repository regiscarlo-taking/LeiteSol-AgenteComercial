from collections.abc import Mapping
import logging
from typing import Any

from leitesol_api.domain.measure import Measure
from leitesol_api.domain.sql_result import CatalogEntity, SqlResult

logger = logging.getLogger("leitesol.api.fabric")


class FabricConnectionError(RuntimeError):
    pass


class EntityNotAllowedError(FabricConnectionError):
    pass


def _table_entities(names: tuple[str, ...]) -> tuple[CatalogEntity, ...]:
    return tuple(
        CatalogEntity(name.lower(), "IA_COMERCIAL", name, "table")
        for name in names
    )


def _view_entities(names: tuple[str, ...]) -> tuple[CatalogEntity, ...]:
    return tuple(
        CatalogEntity(name.removeprefix("vw_").lower(), "IA_COMERCIAL", name, "view")
        for name in names
    )


# Entidades declaradas em 01_ddl_catalogo_agente.sql.
RUNTIME_TABLES = (
    "AGT_SKILL",
    "AGT_OPERACAO",
    "AGT_OPERACAO_PARAMETRO",
    "AGT_MEDIDA",
    "AGT_DIMENSAO",
    "AGT_RELACIONAMENTO",
    "AGT_REGRA_TEMPO",
    "AGT_REGRA_TRANSVERSAL",
    "AGT_MAPA_CAMPO",
    "AGT_GLOSSARIO",
    "AGT_INTENCAO_EXEMPLO",
    "AGT_PARAM_FECHAMENTO",
)

MANAGEMENT_TABLES = (
    "AGT_GESTAO_SKILL",
    "AGT_GESTAO_OPERACAO",
    "AGT_GESTAO_MEDIDA",
    "AGT_GESTAO_DIMENSAO",
    "AGT_GESTAO_RELACIONAMENTO",
    "AGT_GESTAO_MAPA_CAMPO",
    "AGT_GESTAO_PENDENCIA",
)

# Views declaradas em 02_views_analiticas.sql.
ANALYTICAL_VIEWS = (
    "vw_dim_calendario",
    "vw_dim_cliente",
    "vw_dim_produto",
    "vw_dim_representante",
    "vw_dim_supervisor",
    "vw_hierarquia_equipe",
    "vw_rls_alcance",
    "vw_dim_segmento",
    "vw_dim_geografia",
    "vw_dim_filial",
    "vw_fato_faturamento",
    "vw_fato_produto",
)

CATALOG_ENTITIES = (
    *_table_entities(RUNTIME_TABLES),
    *_table_entities(MANAGEMENT_TABLES),
    *_view_entities(ANALYTICAL_VIEWS),
)
ENTITY_BY_NAME = {entity.name: entity for entity in CATALOG_ENTITIES}


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

    def list_entities(self) -> list[CatalogEntity]:
        return list(CATALOG_ENTITIES)

    def query_entity(self, entity: str, limit: int = 100) -> SqlResult:
        selected_entity = ENTITY_BY_NAME.get(entity.strip().lower())
        if selected_entity is None:
            raise EntityNotAllowedError(f"Entity is not allowed: {entity}")

        bounded_limit = min(max(limit, 1), 100)
        sql = (
            f"SELECT TOP {bounded_limit} * "
            f"FROM {selected_entity.qualified_name}"
        )

        try:
            import pyodbc

            with pyodbc.connect(self._connection_string(), timeout=self._timeout) as connection:
                cursor = connection.cursor()
                cursor.execute(sql)
                columns = [column[0] for column in cursor.description]
                rows = [
                    {column: self._json_value(value) for column, value in zip(columns, row)}
                    for row in cursor.fetchall()
                ]
        except Exception as error:
            logger.exception(
                "Fabric entity query failed database=%s entity=%s",
                self._database,
                selected_entity.name,
            )
            raise FabricConnectionError("Unable to query the Fabric entity.") from error

        return SqlResult(
            entity=selected_entity.name,
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )

    @staticmethod
    def _json_value(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "as_tuple"):
            return float(value)
        return value

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
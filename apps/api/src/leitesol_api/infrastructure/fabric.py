import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from leitesol_api.domain.measure import Measure
from leitesol_api.domain.sql_result import CatalogEntity, SqlResult

if TYPE_CHECKING:
    from leitesol_api.infrastructure.settings import Settings

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

# As AGT_GESTAO_* ficam fora do agente (D-A15): 14_permissao_agente.sql
# aplica DENY nelas para a identidade do agente. Não reintroduzir aqui.

# Views declaradas em 02_views_analiticas.sql. As views de segurança
# (vw_hierarquia_equipe, vw_rls_alcance) cruzam e-mail x equipe e servem só
# para resolver a alçada no backend; nunca são consultáveis por rota ou LLM.
ANALYTICAL_VIEWS = (
    "vw_dim_calendario",
    "vw_dim_cliente",
    "vw_dim_produto",
    "vw_dim_representante",
    "vw_dim_supervisor",
    "vw_dim_segmento",
    "vw_dim_geografia",
    "vw_dim_filial",
    "vw_fato_faturamento",
    "vw_fato_produto",
)

CATALOG_ENTITIES = (
    *_table_entities(RUNTIME_TABLES),
    *_view_entities(ANALYTICAL_VIEWS),
)
ENTITY_BY_NAME = {entity.name: entity for entity in CATALOG_ENTITIES}


def build_fabric_connection(settings: "Settings") -> "FabricSqlConnection":
    return FabricSqlConnection(
        server=settings.fabric_server,
        database=settings.fabric_database,
        driver=settings.fabric_driver,
        authentication=settings.fabric_authentication,
        client_id=settings.entra_client_id,
        tenant_id=settings.entra_tenant_id,
        client_secret=settings.entra_client_secret,
        timeout=settings.fabric_connection_timeout,
    )


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
                return [
                    self._to_measure(dict(zip(columns, row, strict=True)))
                    for row in cursor.fetchall()
                ]
        except Exception as error:
            logger.exception(
                "Fabric query failed database=%s table=IA_COMERCIAL.AGT_MEDIDA",
                self._database,
            )
            raise FabricConnectionError(
                "Unable to query measures from the Fabric warehouse."
            ) from error

    def list_entities(self) -> list[CatalogEntity]:
        return list(CATALOG_ENTITIES)

    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Executa SQL fixo do backend com parâmetros posicionais (?).

        Só para consultas escritas no código (catálogo, alçada, operações):
        o texto do SQL nunca vem do usuário nem da LLM, e todo valor variável
        entra como parâmetro do driver.
        """
        try:
            import pyodbc

            with pyodbc.connect(self._connection_string(), timeout=self._timeout) as connection:
                cursor = connection.cursor()
                cursor.execute(sql, params)
                columns = [column[0] for column in cursor.description]
                return [
                    {
                        column: self._json_value(value)
                        for column, value in zip(columns, row, strict=True)
                    }
                    for row in cursor.fetchall()
                ]
        except Exception as error:
            logger.exception("Fabric fixed query failed database=%s", self._database)
            raise FabricConnectionError("Unable to query the Fabric warehouse.") from error

    def describe_entity(self, entity: str) -> list[str]:
        selected_entity = self._get_entity(entity)
        sql = f"SELECT TOP 0 * FROM {selected_entity.qualified_name}"

        try:
            import pyodbc

            with pyodbc.connect(self._connection_string(), timeout=self._timeout) as connection:
                cursor = connection.cursor()
                cursor.execute(sql)
                return [column[0] for column in cursor.description]
        except Exception as error:
            logger.exception(
                "Fabric entity metadata lookup failed database=%s entity=%s",
                self._database,
                selected_entity.name,
            )
            raise FabricConnectionError("Unable to inspect the Fabric entity.") from error

    def query_entity(
        self,
        entity: str,
        limit: int = 100,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> SqlResult:
        selected_entity = self._get_entity(entity)
        bounded_limit = min(max(limit, 1), 100)

        try:
            import pyodbc

            with pyodbc.connect(self._connection_string(), timeout=self._timeout) as connection:
                cursor = connection.cursor()
                available_columns = self._get_columns(cursor, selected_entity)
                sql = self._build_entity_query(
                    selected_entity,
                    bounded_limit,
                    order_by,
                    order_direction,
                    available_columns,
                )
                cursor.execute(sql)
                columns = [column[0] for column in cursor.description]
                rows = [
                    {
                        column: self._json_value(value)
                        for column, value in zip(columns, row, strict=True)
                    }
                    for row in cursor.fetchall()
                ]
        except EntityNotAllowedError:
            raise
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
    def _get_entity(entity: str) -> CatalogEntity:
        selected_entity = ENTITY_BY_NAME.get(entity.strip().lower())
        if selected_entity is None:
            raise EntityNotAllowedError(f"Entity is not allowed: {entity}")
        return selected_entity

    @staticmethod
    def _get_columns(cursor: Any, entity: CatalogEntity) -> dict[str, str]:
        cursor.execute(f"SELECT TOP 0 * FROM {entity.qualified_name}")
        return {column[0].casefold(): column[0] for column in cursor.description}

    @staticmethod
    def _build_entity_query(
        entity: CatalogEntity,
        limit: int,
        order_by: str | None,
        order_direction: str | None,
        available_columns: dict[str, str],
    ) -> str:
        sql = f"SELECT TOP {limit} * FROM {entity.qualified_name}"
        if order_by is None:
            return sql

        column = available_columns.get(order_by.casefold())
        if column is None:
            raise EntityNotAllowedError(f"Ordering column is not available: {order_by}")
        direction = (order_direction or "ASC").upper()
        if direction not in {"ASC", "DESC"}:
            raise EntityNotAllowedError(f"Ordering direction is not allowed: {order_direction}")
        return f"{sql} ORDER BY [{column.replace(']', ']]')}] {direction}"

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

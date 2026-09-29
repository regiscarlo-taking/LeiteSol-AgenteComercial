"""Resolução de alçada: usuário autenticado -> carteira de vendedores (RT34).

Roda ANTES de qualquer consulta de dado. A concessão é a lista explícita de
IA_COMUM.RLS_USUARIO_EQUIPE (via vw_rls_usuario_equipe), não o fecho da
árvore do gestor logado (P-RLSGRANT).
"""

from typing import Any, Protocol

from leitesol_api.domain.agent import Scope

# O próprio código da equipe entra como vendedor: vw_hierarquia_equipe só
# ancora (Nivel 0) supervisores que têm subordinado, e uma equipe concedida
# que é um gestor autossupervisionado (ex.: 967) ficaria vazia sem isso.
SCOPE_SQL = """
    SELECT u.EquipeId, h.RepresentanteId
    FROM [IA_COMERCIAL].[vw_rls_usuario_equipe] u
    LEFT JOIN [IA_COMERCIAL].[vw_hierarquia_equipe] h ON h.GestorId = u.EquipeId
    WHERE u.Email = ?
"""


class SqlFetcher(Protocol):
    def fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...


class ScopeResolver:
    def __init__(self, fetcher: SqlFetcher) -> None:
        self._fetcher = fetcher

    def resolve(self, *, email: str | None, full_access: bool) -> Scope | None:
        """Devolve a alçada, ou None quando o usuário não tem nenhuma (sem_alcada)."""
        if full_access:
            return Scope(sees_everything=True)
        if not email:
            return None

        rows = self._fetcher.fetch(SCOPE_SQL, (email.strip().lower(),))
        teams = frozenset(str(row["EquipeId"]).strip() for row in rows if row["EquipeId"])
        if not teams:
            return None
        sellers = {str(row["RepresentanteId"]).strip() for row in rows if row["RepresentanteId"]}
        return Scope(sees_everything=False, sellers=frozenset(sellers | teams), teams=teams)

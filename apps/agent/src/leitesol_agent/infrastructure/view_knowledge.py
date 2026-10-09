"""Contexto recuperável das views, baseado no mapeamento comercial 24-09-2026."""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ViewKnowledge:
    name: str
    purpose: str
    relationship: str
    fields: str
    caveats: str
    keywords: tuple[str, ...]


VIEW_KNOWLEDGE = (
    ViewKnowledge(
        "vw_fato_faturamento",
        "Faturamento consolidado por cliente, produto, vendedor que faturou e mês.",
        "Base das consultas; une cliente por ClienteId, produto por ProdutoId e calendário "
        "por Data.",
        "Data, ClienteId, ProdutoId, VendedorId, UFVenda, Vendas_R, Dev_R, Vendas_Kg, "
        "Bonif_Kg, Dev_Kg, "
        "FlagCompraValida.",
        "FAT R$ = Vendas_R - Dev_R; FAT KG = Vendas_Kg + Bonif_Kg - Dev_Kg; "
        "FAT TONS = FAT KG / 1000. "
        "Grão mensal; a base começa em janeiro de 2025 e exclui cargas sinistradas "
        "faturadas para transportadora.",
        ("faturamento", "venda", "vendas", "volume", "valor", "kg", "tons", "receita"),
    ),
    ViewKnowledge(
        "vw_dim_cliente",
        "Cadastro atual do cliente/loja, rede, segmento, localização e responsável atual "
        "pela carteira.",
        "Relaciona-se à fato por ClienteId.",
        "ClienteId, ClienteCodigo, Loja, RazaoSocial, CNPJ, CNPJRaiz, Rede, RedeNome, "
        "SegmentoCodigo, "
        "SegmentoDescricao, RCAAtual, UF, Regiao, Municipio, CepId, ClienteAtivo, "
        "FlagExterior.",
        "Rede agrupa lojas do mesmo grupo de venda ou raiz de CNPJ. "
        "UF/região/município são do cadastro "
        "atual, não necessariamente da venda. RCAAtual é o vendedor a quem a venda é "
        "atribuída, como no Power BI. "
        "Exterior é excluído.",
        (
            "cliente",
            "clientes",
            "loja",
            "rede",
            "carteira",
            "cnpj",
            "segmento",
            "uf",
            "região",
            "regiao",
            "município",
            "municipio",
            "rca",
            "responsável",
            "responsavel",
        ),
    ),
    ViewKnowledge(
        "vw_dim_produto",
        "Cadastro de produtos e hierarquia comercial.",
        "Relaciona-se à fato por ProdutoId.",
        "ProdutoId, Produto, Subtotal > Grupamento > Familia, Marca, TipoEmbalagem, "
        "PesoVolumeUnitario, "
        "FlagProdutoAcabado.",
        "Agrupar pelo código do produto, não por descrição. Consultas de faturamento "
        "incluem somente produto "
        "acabado; a hierarquia é subtotal, grupamento e família.",
        (
            "produto",
            "produtos",
            "item",
            "itens",
            "família",
            "familia",
            "grupamento",
            "subtotal",
            "marca",
            "embalagem",
            "mix",
            "gramatura",
        ),
    ),
    ViewKnowledge(
        "vw_produto_termo",
        "Vocabulário controlado de termos de negócio associados a produtos.",
        "Relaciona termos ao produto por ProdutoId.",
        "Termo, TermoNormalizado (maiúsculas sem acento), Dominio (por exemplo marca, "
        "embalagem, gramatura), ProdutoId, Produto.",
        "Um termo de produto só vira filtro se estiver cadastrado. "
        "Termo desconhecido exige esclarecimento; "
        "não adivinhar nem ampliar a lista.",
        (
            "produto",
            "produtos",
            "item",
            "itens",
            "marca",
            "embalagem",
            "gramatura",
            "termo",
        ),
    ),
    ViewKnowledge(
        "vw_dim_representante",
        "Vendedor atual do cliente (a quem a venda é atribuída), papel comercial, gestor "
        "e situação cadastral.",
        "RepresentanteId liga-se ao RCAAtual de vw_dim_cliente.",
        "RepresentanteId, Representante, PapelComercial (RCA, gestor que vende ou sem "
        "gestor), GestorId, Gestor, UF, Ativo.",
        "Toda análise por vendedor usa o RCAAtual do cliente, como no Power BI; quando o "
        "cliente muda de carteira, o histórico dele vai para o novo vendedor. VendedorId da "
        "fato é só quem faturou.",
        (
            "vendedor",
            "vendedores",
            "representante",
            "representantes",
            "rca",
            "gestor",
            "equipe",
            "vendeu",
        ),
    ),
    ViewKnowledge(
        "vw_dim_supervisor",
        "Cadastro de gestores/supervisores comerciais.",
        "GestorId identifica o gestor relacionado à hierarquia da equipe.",
        "GestorId e nome do gestor.",
        "Um gestor pode aparecer em diversos níveis da hierarquia; não somar totais "
        "hierárquicos como se fossem equipes disjuntas.",
        ("gestor", "supervisor", "equipe", "hierarquia"),
    ),
    ViewKnowledge(
        "vw_hierarquia_equipe",
        "Representantes abaixo de cada gestor e nível hierárquico.",
        "RepresentanteId identifica quem vendeu; GestorId ancora cada equipe.",
        "GestorId, RepresentanteId, Representante, Nivel (0 é o próprio gestor), "
        "NivelHierarquia.",
        "A equipe inclui todos os níveis. Um representante pode aparecer para cada gestor "
        "acima dele; totais por gestor não são aditivos.",
        ("gestor", "supervisor", "equipe", "hierarquia", "alçada", "alcada", "carteira"),
    ),
    ViewKnowledge(
        "vw_dim_calendario",
        "Calendário comercial e estado de fechamento mensal.",
        "Data relaciona-se à Data da fato.",
        "Data, AnoMes, Mes, Ano, MesFechado (mês homologado), MesAtual (mês em andamento).",
        "Faturamento é mensal, nunca diário. Mês em andamento só entra quando pedido e "
        "deve ser sinalizado como parcial. A base começa em janeiro de 2025.",
        (
            "mês",
            "mes",
            "ano",
            "período",
            "periodo",
            "comparação",
            "comparacao",
            "histórico",
            "historico",
            "evolução",
            "evolucao",
            "fechado",
            "parcial",
            "competência",
            "competencia",
        ),
    ),
    ViewKnowledge(
        "vw_dim_geografia",
        "Dimensão de UF, região e país.",
        "Complementa os atributos geográficos do cliente.",
        "UF, região e país.",
        "Para filtro e agrupamento de vendas, priorizar UF/Regiao/Municipio cadastrais "
        "em vw_dim_cliente; não confundir com UFVenda na fato.",
        ("região", "regiao", "geografia", "país", "pais", "uf", "estado"),
    ),
    ViewKnowledge(
        "vw_dim_cep",
        "Coordenadas e qualidade de geolocalização do CEP.",
        "CepId relaciona-se a vw_dim_cliente.CepId.",
        "Latitude, Longitude, FlagGeolocalizado, MotivoSemGeolocalizacao.",
        "Nem todo cliente tem coordenadas. Respostas de mapa precisam informar cobertura "
        "e motivo de ausências.",
        ("cep", "mapa", "mapas", "coordenada", "coordenadas", "geolocalização", "geolocalizacao"),
    ),
    ViewKnowledge(
        "vw_dim_segmento",
        "Descrição do segmento comercial.",
        "SegmentoCodigo relaciona-se a vw_dim_cliente.SegmentoCodigo.",
        "SegmentoCodigo e Segmento.",
        "O segmento na dimensão de cliente é o cadastro atual e se aplica ao histórico; "
        "mudanças cadastrais podem reclassificar o passado.",
        ("segmento", "canal", "canais"),
    ),
    ViewKnowledge(
        "vw_rls_usuario_equipe",
        "Concessões de acesso de usuário a equipes.",
        "Email identifica o usuário; EquipeId ancora a hierarquia concedida.",
        "Email, EquipeId.",
        "A alçada vem da concessão explícita. Não inferir acesso pela região/UF; respeitar "
        "sempre o recorte já resolvido pela aplicação.",
        ("acesso", "usuário", "usuario", "alçada", "alcada", "carteira", "equipe"),
    ),
)

COMMON_RULES = (
    "Faturamento: somente produto acabado, clientes não exteriores, fórmulas do catálogo "
    "e mês como grão. "
    "O acesso é a carteira resolvida antes da consulta (ou visão completa autorizada); "
    "filtros da pergunta "
    "são sempre adicionais, nunca substituem esse recorte."
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def retrieve_view_context(question: str, operation: str = "", limit: int = 6) -> str:
    """Seleciona descrições relevantes da documentação local, sem consultar o Warehouse."""
    query = _normalize(f"{question} {operation}")
    words = set(re.findall(r"[a-z0-9]+", query))

    def matches(keyword: str) -> bool:
        normalized = _normalize(keyword)
        if " " in normalized:
            return normalized in query
        return normalized in words

    ranked = [
        (
            sum(1 for keyword in view.keywords if matches(keyword)),
            index,
            view,
        )
        for index, view in enumerate(VIEW_KNOWLEDGE)
    ]
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [view for score, _, view in ranked if score > 0][:limit]
    if not any(view.name == "vw_fato_faturamento" for view in selected):
        selected.append(VIEW_KNOWLEDGE[0])
    sections = [
        f"{view.name}: {view.purpose} Relação: {view.relationship} "
        f"Campos: {view.fields} Cuidados: {view.caveats}"
        for view in selected
    ]
    return f"{COMMON_RULES}\n" + "\n".join(sections)

"""
Carrega produtos do grupo PROMOCAO (venda orientada) por unidade/loja via API Degust PRD.
Usado pelo dashboard hierárquico para exibir tabela estilo Retaguarda.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from typing import Any

import requests

BASE_PRD = "https://lx-degust-api-integracao-prd.azurewebsites.net"

CREDENCIAIS = {
    "usuario": "06266555794",
    "senha": "250913",
}

COLUNAS_RETAGUARDA = [
    "Produto",
    "Descrição do produto",
    "Grupo",
    "Descrição do Grupo",
    "Descrição Monitor",
    "domingo",
    "segunda",
    "terca",
    "quarta",
    "quinta",
    "sexta",
    "sabado",
    "restricaoHorario",
    "valorMix",
    "valorPromocionalMix",
]

_URL_VO = "/api/venda-orientada/consultar-produto-por-grupo-venda-orientada"
_GRUPO_VO = "PROMOCAO"


def _autenticar(base_url: str, codfranqueador: int, session: requests.Session) -> str | None:
    url = f"{base_url.rstrip('/')}/api/usuario/autenticar"
    body = {
        "usuario": CREDENCIAIS["usuario"],
        "senha": CREDENCIAIS["senha"],
        "codigoFranqueador": int(codfranqueador),
    }
    try:
        resp = session.post(url, json=body, timeout=15)
        if resp.status_code == 200:
            return resp.json()["acesso"]["token"]
    except Exception:
        pass
    return None


def _listar_lojas(base_url: str, token: str, codfranqueador: int, session: requests.Session) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/loja/listarLojasFranquia"
    params = {"codigoFranquia": int(codfranqueador)}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = session.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 200:
            lojas = resp.json()
            return lojas if isinstance(lojas, list) else []
    except Exception:
        pass
    return []


def _extrair_lista_produtos(dados: Any) -> list[dict] | None:
    if dados is None:
        return None
    if isinstance(dados, list):
        return dados if dados else None
    if isinstance(dados, dict):
        for chave in ("data", "produtos", "itens", "items", "resultado", "content"):
            val = dados.get(chave)
            if isinstance(val, list) and val:
                return val
        if dados and not any(
            isinstance(dados.get(k), list)
            for k in ("data", "produtos", "itens", "items", "resultado", "content")
        ):
            return [dados]
    return None


def _padroes_venda_orientada(loja: dict) -> list[str]:
    nome_loja = str(loja.get("nomeLoja") or "").upper().strip()
    padroes: list[str] = []
    for key in ("codigoVendaOrientada", "vendaOrientada", "nomeVendaOrientada"):
        val = loja.get(key)
        if val is not None and str(val).strip():
            padroes.append(str(val).strip())
    vo_nome = f"OUT_2025 EC {nome_loja}"
    if vo_nome not in padroes:
        padroes.append(vo_nome)
    return padroes


def _montar_bodies_teste(codfranqueador: int, codigo_loja: int, padroes_vo: list[str]) -> list[tuple[dict, str]]:
    bases = [
        {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": _GRUPO_VO},
        {"codigoFranqueador": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": _GRUPO_VO},
        {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "Promoção"},
        {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "PROMOÇÃO"},
    ]
    bodies: list[tuple[dict, str]] = [(b, f"POST nomeGrupo={b.get('nomeGrupoVendaOrientada')}") for b in bases]
    for padrao in padroes_vo:
        if not padrao:
            continue
        for b in bases:
            for chave_vo in ("codigoVendaOrientada", "vendaOrientada", "nomeVendaOrientada"):
                novo = dict(b)
                novo[chave_vo] = padrao
                bodies.append((novo, f"POST {chave_vo}={padrao}"))
    return bodies


def _consultar_produtos_vo_loja(
    base_url: str,
    token: str,
    codfranqueador: int,
    loja: dict,
    session: requests.Session,
) -> tuple[list[dict], str | None, str]:
    url = f"{base_url.rstrip('/')}{_URL_VO}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    codigo_loja = int(loja["codigoLoja"])
    padroes = _padroes_venda_orientada(loja)
    vo_descoberta = padroes[0] if padroes else ""
    metodo = ""

    for body, rotulo in _montar_bodies_teste(codfranqueador, codigo_loja, padroes):
        try:
            resp = session.post(url, json=body, headers=headers, timeout=15)
            if resp.status_code in (401, 403):
                continue
            if resp.status_code == 200:
                lista = _extrair_lista_produtos(resp.json())
                if lista:
                    metodo = rotulo
                    for chave in ("codigoVendaOrientada", "vendaOrientada", "nomeVendaOrientada"):
                        if chave in body:
                            vo_descoberta = str(body[chave])
                            break
                    return lista, vo_descoberta, metodo
        except Exception:
            continue

    try:
        params = {
            "codigoFranquia": codfranqueador,
            "codigoLoja": codigo_loja,
            "nomeGrupoVendaOrientada": _GRUPO_VO,
        }
        resp = session.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 200:
            lista = _extrair_lista_produtos(resp.json())
            if lista:
                return lista, vo_descoberta, "GET nomeGrupo=PROMOCAO"
    except Exception:
        pass

    return [], vo_descoberta or None, metodo


def _valor_campo(item: dict, *chaves: str, default: str = "") -> str:
    for chave in chaves:
        val = item.get(chave)
        if val is not None and str(val).strip() not in ("", "None", "N/A"):
            return str(val).strip()
    return default


def _linha_retaguarda(item: dict) -> dict:
    produto = _valor_campo(
        item,
        "produto",
        "codigoProduto",
        "idProduto",
        "codigo",
        "id",
        default="",
    )
    descricao = _valor_campo(
        item,
        "descricao do produto",
        "descricaoProduto",
        "nomeProduto",
        "descricao",
        default="",
    )
    grupo = _valor_campo(item, "grupo", "nomeGrupoVendaOrientada", "grupoVendaOrientada", default=_GRUPO_VO)
    desc_grupo = _valor_campo(item, "descricaoGrupo", "descricao do grupo", default="PROMOÇÕES DA UNIDADE")
    monitor = _valor_campo(item, "descricaoMonitor", "Descrição Monitor", "descricaoMonitor", default=descricao)

    linha = {
        "Produto": produto,
        "Descrição do produto": descricao,
        "Grupo": grupo,
        "Descrição do Grupo": desc_grupo,
        "Descrição Monitor": monitor,
    }
    for dia in ("domingo", "segunda", "terca", "quarta", "quinta", "sexta", "sabado"):
        linha[dia] = _valor_campo(item, dia, default="")
    linha["restricaoHorario"] = _valor_campo(item, "restricaoHorario", default="")
    linha["valorMix"] = _valor_campo(item, "valorMix", default="")
    linha["valorPromocionalMix"] = _valor_campo(item, "valorPromocionalMix", default="")
    return linha


def _processar_loja(
    base_url: str,
    token: str,
    codfranqueador: int,
    loja: dict,
) -> dict | None:
    thread_local = threading.local()

    def _session() -> requests.Session:
        if not hasattr(thread_local, "session"):
            thread_local.session = requests.Session()
        return thread_local.session

    session = _session()
    produtos, vo, metodo = _consultar_produtos_vo_loja(base_url, token, codfranqueador, loja, session)
    linhas = [_linha_retaguarda(p) for p in produtos if isinstance(p, dict)]
    if not linhas:
        return None

    nome_loja = loja.get("nomeLoja") or "N/A"
    rotulo_vo = vo or _padroes_venda_orientada(loja)[0] if _padroes_venda_orientada(loja) else "N/A"
    return {
        "codigo_loja": int(loja["codigoLoja"]),
        "nome_loja": nome_loja,
        "linhas_retaguarda": linhas,
        "venda_orientada": vo or rotulo_vo,
        "venda_orientada_rotulo": rotulo_vo,
        "metodo_venda_orientada": metodo or "N/A",
    }


def carregar_todas_unidades_marca(
    base_url: str,
    codfranqueador: int,
    max_vo: int = 80,
) -> dict:
    """
    Carrega produtos PROMOCAO (venda orientada) de todas as lojas da marca.

    Retorna {"unidades": [dict, ...]} onde cada unidade contém linhas_retaguarda.
    """
    with requests.Session() as session:
        token = _autenticar(base_url, codfranqueador, session)
        if not token:
            return {"unidades": []}

        lojas = _listar_lojas(base_url, token, codfranqueador, session)
        if not lojas:
            return {"unidades": []}

        limite = max(1, int(max_vo or 80))
        lojas = lojas[:limite]

        unidades: list[dict] = []
        workers = min(8, max(1, len(lojas)))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futuros = {
                executor.submit(_processar_loja, base_url, token, codfranqueador, loja): loja
                for loja in lojas
            }
            for futuro in as_completed(futuros):
                try:
                    resultado = futuro.result()
                    if resultado:
                        unidades.append(resultado)
                except Exception:
                    continue

    unidades.sort(key=lambda u: int(u.get("codigo_loja") or 0))
    return {"unidades": unidades}

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows
import io
import json

# Configuração da página
st.set_page_config(
    page_title="Dashboard de Promoções",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS customizado para melhorar a aparência
st.markdown("""
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stButton>button {
        width: 100%;
        background-color: #4CAF50;
        color: white;
        font-weight: bold;
        border-radius: 5px;
        border: none;
        padding: 10px;
    }
    .stButton>button:hover {
        background-color: #45a049;
    }
    h1 {
        color: #2c3e50;
        text-align: center;
    }
    .dataframe {
        font-size: 12px;
    }
    
    /* Estilos para layout hierárquico */
    .promocao-header {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
        border-left: 4px solid #4CAF50;
    }
    
    .produto-row {
        background-color: #fafafa;
        padding: 8px;
        margin: 2px 0;
        border-radius: 3px;
        border-left: 2px solid #ddd;
    }
    
    .expander-content {
        margin-left: 20px;
    }
    </style>
""", unsafe_allow_html=True)

# Configurações das marcas
MARCAS_CONFIG = {
    "Promoções Bendito": {
        "codfranqueador": 3082,
        "cor": "#FF6B6B"
    },
    "Promoções Espetto": {
        "codfranqueador": 3078,
        "cor": "#4ECDC4"
    },
    "Promoções Mané": {
        "codfranqueador": 1428,
        "cor": "#95E1D3"
    },
    "Promoções Buteco Seu Rufino": {
        "codfranqueador": 3081,
        "cor": "#FFA500"
    }
}

CREDENCIAIS = {
    "usuario": "06266555794",
    "senha": "250913"
}

DEGUST_API_BASE = "https://lx-degust-api-integracao-prd.azurewebsites.net"


def _formatar_data_br(valor):
    """Formata data para exibição: dd/mm/aaaa."""
    if valor is None:
        return ""
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)

def _agora_brasilia_str(fmt="%d/%m/%Y %H:%M:%S"):
    """Data/hora atual em Brasília (America/Sao_Paulo) para exibição."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime(fmt)
    except Exception:
        from datetime import timezone
        return datetime.now(timezone(timedelta(hours=-3))).strftime(fmt)



def _eh_promocoes_rede(nome_grupo):
    return "PROMOCOES REDE" in _normalizar_grupo(nome_grupo)


def listar_nomes_promocao_rede(df_marca):
    """Lista nomePromocao distintos onde o grupo é PROMOÇÕES REDE."""
    if df_marca.empty or "nomeGrupo" not in df_marca.columns:
        return []
    sub = df_marca[df_marca["nomeGrupo"].apply(_eh_promocoes_rede)]
    if sub.empty or "nomePromocao" not in sub.columns:
        return []
    return sorted(sub["nomePromocao"].dropna().astype(str).unique().tolist())


def codigos_produtos_promocao_rede(df_marca, nome_promocao):
    """Códigos de produto agregados da ação: PROMOÇÕES REDE + nomePromocao."""
    if df_marca.empty:
        return set()
    mask = (
        df_marca["nomeGrupo"].apply(_eh_promocoes_rede)
        & (df_marca["nomePromocao"].astype(str) == str(nome_promocao))
    )
    if "codigoProduto" not in df_marca.columns:
        return set()
    cods = df_marca.loc[mask, "codigoProduto"].dropna().unique()
    out = set()
    for c in cods:
        try:
            out.add(int(float(c)))
        except (TypeError, ValueError):
            continue
    return out


def gerar_blocos_30_dias(data_inicio, data_fim):
    """
    Parte o intervalo em blocos de até 30 dias (API relatorio-vendas).
    Cada bloco: [início, fim] inclusive, no máximo 30 dias corridos.
    """
    if data_fim < data_inicio:
        return []
    blocos = []
    cur = data_inicio
    while cur <= data_fim:
        fim_bloco = min(cur + timedelta(days=29), data_fim)
        blocos.append((cur, fim_bloco))
        cur = fim_bloco + timedelta(days=1)
    return blocos


def _venda_nao_cancelada(venda):
    c = venda.get("cancelada")
    if c is None or c == "":
        return True
    return str(c).upper() not in ("S", "SIM", "1", "Y", "YES", "TRUE")


def _item_conta_para_clique(item):
    c = item.get("cancelado")
    if c is None or c == "":
        return True
    return str(c).upper() not in ("S", "SIM", "1", "Y", "YES", "TRUE")


def somar_cliques_em_vendas(vendas, produtos_set):
    """Soma quantidade dos itens cujo codProduto está em produtos_set (clique = venda)."""
    total = 0.0
    for v in vendas or []:
        if not _venda_nao_cancelada(v):
            continue
        for it in v.get("itens") or []:
            if not _item_conta_para_clique(it):
                continue
            cod = it.get("codProduto")
            if cod is None:
                continue
            try:
                c = int(cod)
            except (TypeError, ValueError):
                continue
            if c not in produtos_set:
                continue
            q = it.get("quantidade")
            try:
                total += float(q or 0)
            except (TypeError, ValueError):
                pass
    return total


def consultar_relatorio_vendas_sum(session, token, cod_franqueador, cod_loja, d_ini, d_fim, produtos_set):
    """POST /api/venda/relatorio-vendas — retorna soma de cliques ou None se falhar."""
    url = f"{DEGUST_API_BASE}/api/venda/relatorio-vendas"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "codFranqueador": int(cod_franqueador),
        "codLoja": int(cod_loja),
        "dataInicial": d_ini.isoformat(),
        "dataFinal": d_fim.isoformat(),
        "tipoData": "C",
        "exibirVendasCanceladas": False,
    }
    try:
        r = session.post(url, json=body, headers=headers, timeout=120)
        if r.status_code != 200:
            return None
        vendas = r.json()
        if not isinstance(vendas, list):
            return None
        return somar_cliques_em_vendas(vendas, produtos_set)
    except Exception:
        return None


def montar_tabela_cliques_promocao_rede(codfranqueador, df_marca, nome_promocao, data_inicio, data_fim, max_workers=6, progress_bar=None, status_label=None):
    """
    Por loja: colunas = um bloco de até 30 dias cada + Acumulado (cliques).
    Retorna (DataFrame, mensagem_erro). mensagem_erro só se falha grosseira.
    """
    produtos_set = codigos_produtos_promocao_rede(df_marca, nome_promocao)
    if not produtos_set:
        return None, "Nenhum produto encontrado para essa promoção em PROMOÇÕES REDE."

    if "codigoLoja" not in df_marca.columns or "nomeLoja" not in df_marca.columns:
        return None, "DataFrame sem codigoLoja ou nomeLoja."

    lojas_df = df_marca[["codigoLoja", "nomeLoja"]].drop_duplicates().sort_values("codigoLoja")
    blocos = gerar_blocos_30_dias(data_inicio, data_fim)
    if not blocos:
        return None, "Intervalo de datas inválido."

    col_labels = [
        f"{_formatar_data_br(a)} a {_formatar_data_br(b)}" for a, b in blocos
    ]

    rows_by_cod = {}
    for _, r in lojas_df.iterrows():
        cod_loja_row = int(r["codigoLoja"])
        rows_by_cod[cod_loja_row] = {"codigoLoja": cod_loja_row, "nomeLoja": r.get("nomeLoja", "N/A")}
        for lbl in col_labels:
            rows_by_cod[cod_loja_row][lbl] = 0.0

    total_ops = len(blocos) * len(lojas_df)
    done = 0
    thread_local = threading.local()

    def _sess():
        if not hasattr(thread_local, "session"):
            thread_local.session = requests.Session()
        return thread_local.session

    with requests.Session() as main_session:
        token = autenticar(codfranqueador, session=main_session)
        if not token:
            return None, "Falha na autenticação."

        for bidx, (di, df_end) in enumerate(blocos):
            lbl = col_labels[bidx]

            def _work(cod_loja):
                loja_cod = int(cod_loja)
                soma = consultar_relatorio_vendas_sum(
                    _sess(), token, codfranqueador, loja_cod, di, df_end, produtos_set
                )
                return loja_cod, soma if soma is not None else 0.0

            workers = max(1, min(max_workers, len(lojas_df)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futs = [
                    executor.submit(_work, r["codigoLoja"]) for _, r in lojas_df.iterrows()
                ]
                for fut in as_completed(futs):
                    loja_cod, soma = fut.result()
                    rows_by_cod[loja_cod][lbl] = soma
                    done += 1
                    if progress_bar is not None:
                        progress_bar.progress(min(done / max(total_ops, 1), 1.0))
                    if status_label is not None:
                        status_label.text(
                            f"Relatório de vendas: bloco {bidx + 1}/{len(blocos)} "
                            f"({lbl}) — {done}/{total_ops}"
                        )

    for c in rows_by_cod:
        acc = sum(rows_by_cod[c][lbl] for lbl in col_labels)
        rows_by_cod[c]["Acumulado (cliques)"] = acc

    ordem = ["codigoLoja", "nomeLoja"] + col_labels + ["Acumulado (cliques)"]
    df_out = pd.DataFrame(list(rows_by_cod.values()))[ordem]
    df_out = df_out.sort_values(
        by="Acumulado (cliques)", ascending=False, ignore_index=True
    )

    # Linha de totais gerais (soma por coluna de período + acumulado).
    linha_total = {"codigoLoja": "", "nomeLoja": "TOTAL"}
    for lbl in col_labels:
        linha_total[lbl] = float(df_out[lbl].sum())
    linha_total["Acumulado (cliques)"] = float(df_out["Acumulado (cliques)"].sum())
    df_out = pd.concat([df_out, pd.DataFrame([linha_total])], ignore_index=True)

    return df_out, None

def _session_flag_true_callback(flag_key: str):
    """on_click do Streamlit: define flag antes do rerun (evita expander fechado no mobile)."""
    def _on_click():
        st.session_state[flag_key] = True
    return _on_click


def _normalizar_grupo(valor):
    """Normaliza nome de grupo para comparação consistente."""
    texto = str(valor or "").strip().upper()
    return (
        texto
        .replace("Ç", "C")
        .replace("Ã", "A")
        .replace("Á", "A")
        .replace("Â", "A")
        .replace("À", "A")
        .replace("É", "E")
        .replace("Ê", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ô", "O")
        .replace("Õ", "O")
        .replace("Ú", "U")
    )

def _grupo_deve_exibir_sequencia(nome_grupo):
    grupo = _normalizar_grupo(nome_grupo)
    return (
        "HAPPY HOUR" in grupo
        or "PROMOCOES DA UNIDADE" in grupo
        or "PROMOCOES REDE" in grupo
    )

def _extrair_sequencia_promocao(row, nome_grupo):
    """Retorna sequência quando o grupo exige exibição da ordem da promoção."""
    if not _grupo_deve_exibir_sequencia(nome_grupo):
        return None
    sequencia = row.get("sequencia", None)
    return sequencia if sequencia not in ("", "None") else None

def autenticar(codfranqueador, session=None):
    """Realiza autenticação na API do Degust"""
    url_auth = "https://lx-degust-api-integracao-prd.azurewebsites.net/api/usuario/autenticar"
    
    credenciais = {
        "usuario": CREDENCIAIS["usuario"],
        "senha": CREDENCIAIS["senha"],
        "codigoFranqueador": codfranqueador
    }
    cliente_http = session or requests
    
    try:
        response = cliente_http.post(url_auth, json=credenciais, timeout=10)
        if response.status_code == 200:
            token = response.json()["acesso"]["token"]
            return token
        else:
            st.error(f"❌ Erro ao autenticar: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"❌ Erro de conexão: {str(e)}")
        return None

def _loja_degust_ativa(loja):
    """
    Fallback quando GET /api/loja/loja nao retorna dadosGerais.ativo de forma conclusiva.
    listarLojasFranquia pode trazer situacao / situacaoLoja.
    """
    for key in ("situacaoLoja", "situacao"):
        val = loja.get(key)
        if val is None:
            continue
        s = str(val).strip().upper()
        if s and "INATIV" in s:
            return False
    return True


def _interpretar_campo_ativo_cadastro(val):
    """
    dadosGerais.ativo em LojaResult (GET /api/loja/loja). String no Swagger.
    Retorna True (ativa), False (inativa) ou None (indeterminado).
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    s = str(val).strip().upper()
    if not s:
        return None
    if s in ("S", "SIM", "1", "T", "TRUE", "Y", "YES", "ATIVO", "ATIVA"):
        return True
    if s in ("N", "NAO", "NÃO", "0", "F", "FALSE", "INATIVO", "INATIVA"):
        return False
    if "INATIV" in s:
        return False
    if "ATIV" in s:
        return True
    return None


def _consultar_ativo_cadastro_loja(cliente_http, token, codfranqueador, codigo_loja):
    """GET /api/loja/loja - campo dadosGerais.ativo (cadastro retaguarda)."""
    url = f"{DEGUST_API_BASE}/api/loja/loja"
    params = {"CodigoFranqueador": int(codfranqueador), "CodigoLoja": int(codigo_loja)}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = cliente_http.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        dg = data.get("dadosGerais") or {}
        if not isinstance(dg, dict):
            return None
        return _interpretar_campo_ativo_cadastro(dg.get("ativo"))
    except Exception:
        return None


def _manter_loja_apos_consulta_cadastro(loja, ativo_cadastro):
    if ativo_cadastro is False:
        return False
    if ativo_cadastro is True:
        return True
    return _loja_degust_ativa(loja)


def _filtrar_lojas_por_cadastro_degust(lojas, token, codfranqueador, session_shared=None, max_workers=8):
    """Mantem lojas com dadosGerais.ativo ativa; fallback em situacao da listagem."""
    if not lojas:
        return []

    def processar(loja, http):
        cod = loja.get("codigoLoja")
        try:
            c = int(cod) if cod is not None else None
        except (TypeError, ValueError):
            c = None
        if c is None:
            return _manter_loja_apos_consulta_cadastro(loja, None)
        at = _consultar_ativo_cadastro_loja(http, token, codfranqueador, c)
        return _manter_loja_apos_consulta_cadastro(loja, at)

    if session_shared is not None:
        out = []
        for loja in lojas:
            if processar(loja, session_shared):
                out.append(loja)
        return out

    if len(lojas) == 1:
        loja = lojas[0]
        return [loja] if processar(loja, requests) else []

    thread_local = threading.local()

    def http_por_thread():
        if not hasattr(thread_local, "session"):
            thread_local.session = requests.Session()
        return thread_local.session

    workers = max(1, min(max_workers, len(lojas)))

    def work(loja):
        return loja, processar(loja, http_por_thread())

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pairs = list(executor.map(work, lojas))
    return [loja for loja, ok in pairs if ok]


def obter_lojas(token, codfranqueador, session=None):
    """Obtém lista de lojas da franquia com dados completos"""
    url_lojas = f"https://lx-degust-api-integracao-prd.azurewebsites.net/api/loja/listarLojasFranquia?codigoFranquia={codfranqueador}"
    headers = {"Authorization": f"Bearer {token}"}
    cliente_http = session or requests
    
    try:
        response = cliente_http.get(url_lojas, headers=headers, timeout=10)
        if response.status_code == 200:
            lojas = response.json()
            if not isinstance(lojas, list):
                return []
            return _filtrar_lojas_por_cadastro_degust(lojas, token, codfranqueador, session_shared=session)
        else:
            st.error(f"❌ Erro ao buscar lojas: {response.status_code}")
            return []
    except Exception as e:
        st.error(f"❌ Erro de conexão: {str(e)}")
        return []

def consultar_promocoes(token, codfranqueador, lojas_completas, marca, max_workers=8):
    """Consulta promoções de todas as lojas"""
    url_promocoes = "https://lx-degust-api-integracao-prd.azurewebsites.net/api/produto/consultar-promocoes"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    dados_todas_lojas = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_lojas = len(lojas_completas)

    if total_lojas == 0:
        progress_bar.empty()
        status_text.empty()
        return dados_todas_lojas

    workers = max(1, min(max_workers, total_lojas))
    thread_local = threading.local()

    def _session_thread():
        if not hasattr(thread_local, "session"):
            thread_local.session = requests.Session()
        return thread_local.session

    def _consultar_loja(loja):
        codigo_loja = loja["codigoLoja"]
        nome_loja = loja.get("nomeLoja", "N/A")
        body = {
            "codigoFranquia": codfranqueador,
            "codigoLoja": codigo_loja
        }
        try:
            response = _session_thread().post(url_promocoes, json=body, headers=headers, timeout=10)
            if response.status_code != 200:
                return codigo_loja, nome_loja, []
            dados = response.json() or []
            for item in dados:
                item["codigoLoja"] = codigo_loja
                item["nomeLoja"] = nome_loja
                item["marca"] = marca
            return codigo_loja, nome_loja, dados
        except Exception as e:
            return codigo_loja, nome_loja, e

    concluidas = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = [executor.submit(_consultar_loja, loja) for loja in lojas_completas]
        for futuro in as_completed(futuros):
            codigo_loja, nome_loja, resultado = futuro.result()
            concluidas += 1
            status_text.text(f"🔄 Carregando promoções ({concluidas}/{total_lojas}): {nome_loja}")
            progress_bar.progress(concluidas / total_lojas)

            if isinstance(resultado, Exception):
                st.warning(f"⚠️ Erro ao buscar promoções da loja {nome_loja} ({codigo_loja}): {str(resultado)}")
                continue
            if resultado:
                dados_todas_lojas.extend(resultado)
    
    progress_bar.empty()
    status_text.empty()
    
    return dados_todas_lojas

def consultar_produtos_grupo_venda_orientada(token, codfranqueador, lojas_completas, marca, nome_grupo="Promoção"):
    """Consulta produtos por grupo de venda orientada de todas as lojas usando autenticação da API
    
    IMPORTANTE: Utiliza as MESMAS credenciais e token da API de promoções.
    O token é obtido através da função autenticar() que usa CREDENCIAIS["usuario"] e CREDENCIAIS["senha"].
    """
    url = "https://lx-degust-api-integracao-prd.azurewebsites.net/api/venda-orientada/consultar-produto-por-grupo-venda-orientada"
    
    # Usar o MESMO token e formato de autenticação da API de promoções
    # O token é obtido da mesma função autenticar() que usa as mesmas credenciais
    headers = {
        "Authorization": f"Bearer {token}",  # Mesmo token usado na API de promoções
        "Content-Type": "application/json"
    }
    
    dados_todas_lojas = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_lojas = len(lojas_completas)
    
    for idx, loja in enumerate(lojas_completas):
        codigo_loja = loja["codigoLoja"]
        nome_loja = loja.get("nomeLoja", "N/A")
        # Código venda orientada: usar do objeto loja se a API retornar, ou tentar padrão "OUT_2025 EC {NOME_LOJA}"
        cod_venda_orientada_loja = loja.get("codigoVendaOrientada") or loja.get("vendaOrientada") or loja.get("nomeVendaOrientada")
        padroes_venda_orientada = []
        if cod_venda_orientada_loja:
            padroes_venda_orientada.append(str(cod_venda_orientada_loja).strip())
        vo_nome = "OUT_2025 EC " + nome_loja.upper().strip()
        if vo_nome not in padroes_venda_orientada:
            padroes_venda_orientada.append(vo_nome)
        
        status_text.text(f"Carregando produtos do grupo '{nome_grupo}' da loja {idx + 1}/{total_lojas}: {nome_loja}")
        
        nome_grupo_upper = nome_grupo.upper()
        
        if 'BALDES' in nome_grupo_upper:
            bases = [
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "BALDES"},
                {"codigoFranqueador": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "BALDES"},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": nome_grupo},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": nome_grupo.upper()},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "baldes"},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "Baldes"}
            ]
        else:
            bases = [
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "PROMOCAO"},
                {"codigoFranqueador": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "PROMOCAO"},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": nome_grupo},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": nome_grupo.upper()},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "Promoção"},
                {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "PROMOÇÃO"}
            ]
        # Montar bodies: bases; depois com codigoVendaOrientada, vendaOrientada e nomeVendaOrientada (API pode usar qualquer um)
        bodies_teste = list(bases)
        for padrao in padroes_venda_orientada:
            if not padrao:
                continue
            for b in bases:
                for chave_vo in ("codigoVendaOrientada", "vendaOrientada", "nomeVendaOrientada"):
                    novo = dict(b)
                    novo[chave_vo] = padrao
                    bodies_teste.append(novo)
        
        dados_retornados = None
        for body in bodies_teste:
            try:
                # Usar o MESMO token de autenticação obtido da função autenticar()
                # que utiliza as MESMAS credenciais (CREDENCIAIS["usuario"] e CREDENCIAIS["senha"])
                # usadas na API de promoções
                response = requests.post(url, json=body, headers=headers, timeout=10)
            
                # Verificar se houve erro de autenticação
                if response.status_code == 401:
                    continue  # Tentar próximo body
                elif response.status_code == 403:
                    continue  # Tentar próximo body
                
                if response.status_code == 200:
                    dados = response.json()
                    # Extrair lista de produtos: API pode retornar lista direta ou objeto com chave (data, produtos, itens, etc.)
                    lista_produtos = None
                    if dados is not None:
                        if isinstance(dados, list):
                            lista_produtos = dados if len(dados) > 0 else None
                        elif isinstance(dados, dict):
                            for chave in ("data", "produtos", "itens", "items", "resultado", "content"):
                                if chave in dados and isinstance(dados[chave], list) and len(dados[chave]) > 0:
                                    lista_produtos = dados[chave]
                                    break
                            # Só tratar como objeto único se não for um wrapper com lista vazia
                            if lista_produtos is None and dados and not any(
                                isinstance(dados.get(k), list) for k in ("data", "produtos", "itens", "items", "resultado", "content")
                            ):
                                lista_produtos = [dados]
                    if lista_produtos:
                        dados_retornados = lista_produtos
                        if 'BALDES' in str(body.get('nomeGrupoVendaOrientada', '')).upper():
                            st.info(f"Encontrados {len(dados_retornados)} produtos do grupo 'BALDES' na loja {nome_loja}")
                        break
            except Exception as e:
                continue
        
        # Se POST não retornou dados, tentar GET com query params (algumas APIs aceitam GET)
        if dados_retornados is None:
            try:
                params = {
                    "codigoFranquia": codfranqueador,
                    "codigoLoja": codigo_loja,
                    "nomeGrupoVendaOrientada": "PROMOCAO" if "PROMOCAO" in nome_grupo_upper or "PROMO" in nome_grupo_upper else (nome_grupo if "BALDES" in nome_grupo_upper else "PROMOCAO"),
                }
                if "BALDES" in nome_grupo_upper:
                    params["nomeGrupoVendaOrientada"] = "BALDES"
                resp_get = requests.get(url, params=params, headers=headers, timeout=10)
                if resp_get.status_code == 200:
                    dados = resp_get.json()
                    if isinstance(dados, list) and len(dados) > 0:
                        dados_retornados = dados
                    elif isinstance(dados, dict):
                        for chave in ("data", "produtos", "itens", "items", "resultado", "content"):
                            if chave in dados and isinstance(dados[chave], list) and len(dados[chave]) > 0:
                                dados_retornados = dados[chave]
                                break
            except Exception:
                pass
        
        # Processar dados retornados se encontrou
        if dados_retornados:
            for item in dados_retornados:
                # Normalizar campos da API "Produto por Grupo de Venda Orientada" para o formato do app
                if "codigoProduto" not in item or item.get("codigoProduto") is None:
                    item["codigoProduto"] = (item.get("produto") or item.get("codigoProduto") or item.get("idProduto") or
                                             item.get("id") or item.get("codigo") or "N/A")
                if "descricaoProduto" not in item or item.get("descricaoProduto") is None or item.get("descricaoProduto") == "":
                    item["descricaoProduto"] = (item.get("descricao do produto") or item.get("descricaoProduto") or
                                                item.get("nomeProduto") or item.get("descricao") or "N/A")
                for campo in ("domingo", "segunda", "terca", "quarta", "quinta", "sexta", "sabado", "restricaoHorario", "valorMix", "valorPromocionalMix"):
                    if campo not in item:
                        item[campo] = "N/A"
                item["codigoLoja"] = codigo_loja
                item["nomeLoja"] = nome_loja
                item["marca"] = marca
                # Identificar o grupo de venda orientada baseado no nome_grupo passado como parâmetro
                # ou no nome do grupo retornado pela API
                grupo_identificado = "PROMOCAO"  # Padrão
                nome_grupo_display = "PROMOÇÕES DA UNIDADE"  # Padrão
                
                # Usar o nome_grupo passado como parâmetro (mais confiável)
                nome_grupo_param = str(nome_grupo).upper()
                # Verificar também campos retornados pela API que possam indicar o grupo
                nome_grupo_api = str(item.get('nomeGrupoVendaOrientada', '') or 
                                     item.get('grupoVendaOrientada', '') or 
                                     item.get('nomeGrupo', '') or 
                                     nome_grupo_param).upper()
                
                # Verificar se é "BALDES" - priorizar o parâmetro passado
                if 'BALDES' in nome_grupo_param:
                    grupo_identificado = "BALDES"
                    nome_grupo_display = "BALDES"
                elif 'BALDES' in nome_grupo_api:
                    grupo_identificado = "BALDES"
                    nome_grupo_display = "BALDES"
                elif 'PROMOCAO' in nome_grupo_param or 'PROMOÇÃO' in nome_grupo_param:
                    grupo_identificado = "PROMOCAO"
                    nome_grupo_display = "PROMOÇÕES DA UNIDADE"
                elif 'PROMOCAO' in nome_grupo_api or 'PROMOÇÃO' in nome_grupo_api:
                    grupo_identificado = "PROMOCAO"
                    nome_grupo_display = "PROMOÇÕES DA UNIDADE"
                
                item["grupoVendaOrientada"] = grupo_identificado
                item["nomeGrupo"] = nome_grupo_display
                # Armazenar o nome original do grupo para referência futura
                item["nomeGrupoVendaOrientadaOriginal"] = nome_grupo_api
                item["promocaoAtiva"] = "Sim"
                if "produtoPromocaoAtivo" not in item:
                    item["produtoPromocaoAtivo"] = "Sim"
            dados_todas_lojas.extend(dados_retornados)
        else:
            # Debug temporário: verificar se a API está retornando algo
            # (remover depois de identificar o problema)
            pass
        
        progress_bar.progress((idx + 1) / total_lojas)
    
    progress_bar.empty()
    status_text.empty()
    
    return dados_todas_lojas


def _extrair_lista_resposta(resp):
    """Extrai lista de produtos da resposta da API (lista direta ou dentro de chave)."""
    if resp.status_code != 200:
        return None, 0
    try:
        dados = resp.json()
        if isinstance(dados, list) and len(dados) > 0:
            return dados, len(dados)
        if isinstance(dados, dict):
            for chave in ("data", "produtos", "itens", "items", "resultado", "content"):
                if chave in dados and isinstance(dados[chave], list) and len(dados[chave]) > 0:
                    return dados[chave], len(dados[chave])
    except Exception:
        pass
    return None, 0


def diagnosticar_api_grupo_venda_orientada(marca, codfranqueador, codigo_loja, nome_loja, codigo_venda_orientada=None):
    """
    Faz uma chamada de teste à API consultar-produto-por-grupo-venda-orientada.
    Se codigo_venda_orientada for informado, testa com codigoVendaOrientada, vendaOrientada e nomeVendaOrientada.
    """
    url = "https://lx-degust-api-integracao-prd.azurewebsites.net/api/venda-orientada/consultar-produto-por-grupo-venda-orientada"
    token = autenticar(codfranqueador)
    if not token:
        return {"erro": "Falha ao autenticar", "status_code": None, "request_body": None, "response_text": None, "tentativas": []}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    valor_vo = str(codigo_venda_orientada).strip() if codigo_venda_orientada else None

    # Tentar com diferentes nomes do parâmetro de venda orientada
    chaves_vo = ["codigoVendaOrientada", "vendaOrientada", "nomeVendaOrientada"]
    tentativas = []
    body_usado = None
    response_text = "[]"
    resp_len = 0
    status_code = None

    bodies = []
    base = {"codigoFranquia": codfranqueador, "codigoLoja": codigo_loja, "nomeGrupoVendaOrientada": "PROMOCAO"}
    if valor_vo:
        for chave in chaves_vo:
            b = dict(base)
            b[chave] = valor_vo
            bodies.append(b)
    else:
        bodies = [base]

    try:
        for body in bodies:
            r = requests.post(url, json=body, headers=headers, timeout=15)
            lista, n = _extrair_lista_resposta(r)
            tentativas.append({"body": dict(body), "status": r.status_code, "itens": n})
            if n > 0:
                body_usado = body
                status_code = r.status_code
                resp_len = n
                try:
                    response_text = json.dumps(r.json(), indent=2, ensure_ascii=False)[:8000]
                except Exception:
                    response_text = r.text[:8000]
                break
            if body_usado is None:
                body_usado = body
                status_code = r.status_code
                try:
                    response_text = json.dumps(r.json(), indent=2, ensure_ascii=False)[:8000]
                except Exception:
                    response_text = r.text[:8000] if r.text else "[]"
        return {
            "erro": None,
            "status_code": status_code,
            "request_body": body_usado or base,
            "response_text": response_text,
            "response_length": resp_len,
            "tentativas": tentativas,
        }
    except Exception as e:
        return {"erro": str(e), "status_code": None, "request_body": base, "response_text": None, "tentativas": tentativas}


def criar_excel_formatado(df):
    """Cria um arquivo Excel formatado a partir de um DataFrame"""
    # Criar workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Promoções"
    
    # Adicionar dados do DataFrame
    for r in dataframe_to_rows(df, index=False, header=True):
        ws.append(r)
    
    # Formatar cabeçalho
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment
    
    # Ajustar larguras das colunas
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        
        # Limitar largura máxima e mínima
        adjusted_width = min(max(max_length + 2, 10), 50)
        ws.column_dimensions[column_letter].width = adjusted_width
    
    # Congelar primeira linha
    ws.freeze_panes = "A2"
    
    # Formatar células de dados (alinhamento)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    
    # Salvar em buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    
    return buffer

def analisar_promocoes_por_cobertura(df_marca):
    """Analisa promoções por cobertura de lojas"""
    if df_marca.empty or "nomePromocao" not in df_marca.columns or "codigoLoja" not in df_marca.columns:
        return {}
    
    # Contar quantas lojas cada promoção aparece
    promocao_por_loja = df_marca.groupby("nomePromocao")["codigoLoja"].nunique()
    total_lojas = df_marca["codigoLoja"].nunique()
    
    # Calcular percentual de cobertura
    promocao_cobertura = promocao_por_loja / total_lojas * 100
    
    # Categorizar promoções
    promocoes_100 = promocao_por_loja[promocao_por_loja == total_lojas]
    promocoes_80_plus = promocao_por_loja[promocao_por_loja >= total_lojas * 0.8]
    promocoes_50_plus = promocao_por_loja[promocao_por_loja >= total_lojas * 0.5]
    
    # Top 10 promoções mais comuns
    top_10 = promocao_por_loja.nlargest(10)
    
    # Criar DataFrame com análise
    df_analise = pd.DataFrame({
        'Promoção': promocao_por_loja.index,
        'Lojas': promocao_por_loja.values,
        'Cobertura (%)': promocao_cobertura.values.round(1)
    }).sort_values('Cobertura (%)', ascending=False)
    
    # Adicionar status das promoções
    if "promocaoAtiva" in df_marca.columns:
        status_promocoes = df_marca.groupby("nomePromocao")["promocaoAtiva"].first()
        df_analise['Status'] = df_analise['Promoção'].map(status_promocoes).fillna('N/A')
    
    return {
        'total_lojas': total_lojas,
        'total_promocoes': len(promocao_por_loja),
        'promocoes_100': promocoes_100,
        'promocoes_80_plus': promocoes_80_plus,
        'promocoes_50_plus': promocoes_50_plus,
        'top_10': top_10,
        'df_analise': df_analise,
        'media_cobertura': promocao_cobertura.mean(),
        'mediana_cobertura': promocao_cobertura.median()
    }

@st.cache_data(ttl=300)  # Cache por 5 minutos
def carregar_dados_marca(marca):
    """Carrega dados de uma marca específica, incluindo promoções e produtos do grupo de venda orientada"""
    config = MARCAS_CONFIG[marca]
    codfranqueador = config["codfranqueador"]
    
    # Validar código do franqueador
    if not codfranqueador or codfranqueador == 0:
        st.warning(f"⚠️ Código do franqueador não configurado para {marca}. Por favor, atualize o código em MARCAS_CONFIG.")
        return pd.DataFrame()
    
    with requests.Session() as session:
        # Autenticar
        token = autenticar(codfranqueador, session=session)
        if not token:
            return pd.DataFrame()
        
        # Obter lojas com dados completos
        lojas_completas = obter_lojas(token, codfranqueador, session=session)
        if not lojas_completas:
            return pd.DataFrame()
        
        # Consultar promoções normais (API consultar-promocoes)
        dados = consultar_promocoes(token, codfranqueador, lojas_completas, marca)
    
    # Lógica de listar produtos das categorias "PROMOCAO" e "BALDES" (API grupo venda orientada) foi desativada.
    
    if not dados:
        dados = []
    
    if dados:
        df = pd.DataFrame(dados)
        return df
    else:
        return pd.DataFrame()

def agrupar_por_loja_e_promocao(df):
    """Agrupa dados por loja e depois por promoção, incluindo categorias de grupo de venda orientada"""
    if df.empty:
        return {}
    
    # Primeiro agrupar por loja
    grupos_lojas = {}
    
    # Separar produtos do grupo de venda orientada
    produtos_grupo_venda = []
    produtos_normais = []
    
    # Coletar todas as lojas únicas para garantir que todas tenham a categoria
    lojas_unicas = set()
    
    for _, row in df.iterrows():
        codigo_loja = row.get('codigoLoja', 'N/A')
        nome_loja = row.get('nomeLoja', 'N/A')
        chave_loja = f"{codigo_loja} - {nome_loja}"
        lojas_unicas.add(chave_loja)
        
        # Verificar se é produto do grupo de venda orientada
        # Pode ser "PROMOCAO", "PROMOÇÃO" ou "BALDES"
        grupo_venda = row.get('grupoVendaOrientada')
        if grupo_venda:
            grupo_venda_str = str(grupo_venda).strip().upper()
            # Aceitar "PROMOCAO", "PROMOÇÃO" ou "BALDES"
            if grupo_venda_str in ['PROMOCAO', 'PROMOÇÃO', 'BALDES']:
                produtos_grupo_venda.append(row)
            else:
                produtos_normais.append(row)
        else:
            produtos_normais.append(row)
    
    # Processar produtos normais primeiro
    # Para TODAS as marcas: produtos normais com "PROMOÇÕES" vão para "PROMOÇÕES - {NOME_LOJA}"
    for row in produtos_normais:
        codigo_loja = row.get('codigoLoja', 'N/A')
        nome_loja = row.get('nomeLoja', 'N/A')
        chave_loja = f"{codigo_loja} - {nome_loja}"
        marca_row = row.get('marca', '')
        
        if chave_loja not in grupos_lojas:
            grupos_lojas[chave_loja] = {
                'info_loja': {
                    'codigoLoja': codigo_loja,
                    'nomeLoja': nome_loja,
                    'marca': marca_row
                },
                'promocoes': {}
            }
        
        # Agrupar promoções dentro da loja
        nome_promocao = row.get('nomePromocao', 'Sem Nome')
        nome_grupo_row = row.get('nomeGrupo', 'N/A')
        sequencia_row = _extrair_sequencia_promocao(row, nome_grupo_row)
        
        # Para TODAS as marcas: se o nome da promoção contém "PROMOÇÕES", garantir que existe
        # e que os produtos normais vão para a seção "PROMOÇÕES - {NOME_LOJA}"
        nome_promocao_normalizado = nome_promocao.upper().replace('Ç', 'C').replace('Õ', 'O').replace('Ã', 'A')
        if 'PROMOCOES' in nome_promocao_normalizado or 'PROMOÇÕES' in nome_promocao_normalizado:
            # Garantir que a promoção "PROMOÇÕES - {NOME_LOJA}" existe
            nome_promocao_base = f"PROMOÇÕES - {nome_loja.upper()}"
            if nome_promocao_base not in grupos_lojas[chave_loja]['promocoes']:
                grupos_lojas[chave_loja]['promocoes'][nome_promocao_base] = {
                    'info_promocao': {
                        'nomePromocao': nome_promocao_base,
                        'promocaoAtiva': 'Sim',
                        'nomeGrupo': 'PROMOÇÕES DA UNIDADE',
                        'sequencia': sequencia_row
                    },
                    'produtos': [],
                    'categorias': {}
                }
            nome_promocao = nome_promocao_base
        
        if nome_promocao not in grupos_lojas[chave_loja]['promocoes']:
            nome_grupo = nome_grupo_row
            sequencia = sequencia_row
            
            grupos_lojas[chave_loja]['promocoes'][nome_promocao] = {
                'info_promocao': {
                    'nomePromocao': nome_promocao,
                    'promocaoAtiva': row.get('promocaoAtiva', 'N/A'),
                    'nomeGrupo': nome_grupo,
                    'sequencia': sequencia
                },
                'produtos': [],
                'categorias': {}  # Nova estrutura para categorias de grupo de venda orientada
            }
        else:
            # Garantir que a estrutura de categorias existe mesmo se a promoção já foi criada
            if 'categorias' not in grupos_lojas[chave_loja]['promocoes'][nome_promocao]:
                grupos_lojas[chave_loja]['promocoes'][nome_promocao]['categorias'] = {}
            # Se a promoção já existe e ainda não tem sequência, preencher quando houver no dado atual.
            info_promocao_existente = grupos_lojas[chave_loja]['promocoes'][nome_promocao]['info_promocao']
            if info_promocao_existente.get('sequencia') in (None, "", "None") and sequencia_row is not None:
                info_promocao_existente['sequencia'] = sequencia_row
        
        # Adicionar produto
        produto = {
            'codigoProduto': row.get('codigoProduto', 'N/A'),
            'descricaoProduto': row.get('descricaoProduto', 'N/A'),
            'produtoPromocaoAtivo': row.get('produtoPromocaoAtivo', 'N/A'),
            'domingo': row.get('domingo', 'N/A'),
            'segunda': row.get('segunda', 'N/A'),
            'terca': row.get('terca', 'N/A'),
            'quarta': row.get('quarta', 'N/A'),
            'quinta': row.get('quinta', 'N/A'),
            'sexta': row.get('sexta', 'N/A'),
            'sabado': row.get('sabado', 'N/A'),
            'restricaoHorario': row.get('restricaoHorario', 'N/A'),
            'autorizaGerente': row.get('autorizaGerente', 'N/A'),
            'taxaServico': row.get('taxaServico', 'N/A'),
            'valorMix': row.get('valorMix', 'N/A'),
            'valorPromocionalMix': row.get('valorPromocionalMix', 'N/A')
        }
        
        grupos_lojas[chave_loja]['promocoes'][nome_promocao]['produtos'].append(produto)
    
    # Garantir que todas as lojas tenham a estrutura de categorias (para compatibilidade)
    # NOTA: Os produtos do grupo de venda orientada agora são adicionados diretamente
    # em 'produtos' da promoção, mas mantemos a estrutura de 'categorias' para não quebrar
    # funcionalidades existentes que possam depender dela
    for chave_loja in lojas_unicas:
        if chave_loja not in grupos_lojas:
            # Se a loja não foi criada ainda, criar estrutura básica
            codigo_loja, nome_loja = chave_loja.split(' - ', 1) if ' - ' in chave_loja else (chave_loja, 'N/A')
            grupos_lojas[chave_loja] = {
                'info_loja': {
                    'codigoLoja': codigo_loja,
                    'nomeLoja': nome_loja,
                    'marca': 'N/A'
                },
                'promocoes': {}
            }
        
        # Garantir que todas as promoções existentes tenham a estrutura de categorias
        for nome_promocao_existente in grupos_lojas[chave_loja]['promocoes'].keys():
            if 'categorias' not in grupos_lojas[chave_loja]['promocoes'][nome_promocao_existente]:
                grupos_lojas[chave_loja]['promocoes'][nome_promocao_existente]['categorias'] = {}
    
    # Lógica de categorias "PRODUTOS DA CATEGORIA PROMOÇÕES" e "PRODUTOS DA CATEGORIA BALDES" desativada.
    # (Não são mais criadas nem preenchidas; produtos vêm apenas da API consultar-promocoes.)
    
    return grupos_lojas

def exibir_loja_hierarquica(chave_loja, dados_loja, cor_marca):
    """Exibe uma loja e suas promoções no formato hierárquico"""
    
    # Separar promoções ativas e inativas
    promocoes_ativas = {}
    promocoes_inativas = {}
    
    for nome_promocao, dados_promocao in dados_loja['promocoes'].items():
        if dados_promocao['info_promocao']['promocaoAtiva'] == 'Sim':
            promocoes_ativas[nome_promocao] = dados_promocao
        else:
            promocoes_inativas[nome_promocao] = dados_promocao
    
    # Calcular métricas da loja (incluindo produtos de categorias)
    total_produtos_ativos = 0
    for promocao in promocoes_ativas.values():
        total_produtos_ativos += len(promocao.get('produtos', []))
        for categoria in promocao.get('categorias', {}).values():
            total_produtos_ativos += len(categoria.get('produtos', []))
    
    total_produtos_inativos = 0
    for promocao in promocoes_inativas.values():
        total_produtos_inativos += len(promocao.get('produtos', []))
        for categoria in promocao.get('categorias', {}).values():
            total_produtos_inativos += len(categoria.get('produtos', []))
    
    total_promocoes_ativas = len(promocoes_ativas)
    total_promocoes_inativas = len(promocoes_inativas)
    total_produtos = total_produtos_ativos + total_produtos_inativos
    total_promocoes = total_promocoes_ativas + total_promocoes_inativas
    
    # Criar título do expander com métricas
    titulo_expander = f"🏪 {chave_loja} | 🟢 {total_promocoes_ativas} Ativas | 🔴 {total_promocoes_inativas} Inativas | 🎯 {total_produtos} Produtos"
    
    # Expander para a loja inteira
    with st.expander(titulo_expander, expanded=False):
        # Informações gerais da loja
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🟢 Promoções Ativas", total_promocoes_ativas)
        with col2:
            st.metric("🔴 Promoções Inativas", total_promocoes_inativas)
        with col3:
            st.metric("🎯 Total de Produtos", total_produtos)
        with col4:
            st.metric("🏪 Código da Loja", dados_loja['info_loja']['codigoLoja'])
        
        st.markdown("---")
        
        # Exibir promoções ativas primeiro
        if promocoes_ativas:
            st.markdown("**🟢 Promoções Ativas:**")
            for nome_promocao, dados_promocao in promocoes_ativas.items():
                exibir_promocao_dentro_loja(nome_promocao, dados_promocao, cor_marca)
        
        # Exibir promoções inativas consolidadas
        if promocoes_inativas:
            st.markdown("**🔴 Promoções Inativas:**")
            
            # Criar um DataFrame consolidado com todas as promoções inativas
            todas_promocoes_inativas = []
            for nome_promocao, dados_promocao in promocoes_inativas.items():
                for produto in dados_promocao['produtos']:
                    produto_consolidado = {
                        'Promoção': nome_promocao,
                        'Grupo': dados_promocao['info_promocao']['nomeGrupo'],
                        'Status': 'Inativo',
                        **produto
                    }
                    todas_promocoes_inativas.append(produto_consolidado)
            
            if todas_promocoes_inativas:
                df_consolidado = pd.DataFrame(todas_promocoes_inativas)
                
                # Reordenar colunas para melhor visualização
                colunas_ordenadas = [
                    'Promoção', 'Grupo', 'Status',
                    'codigoProduto', 'descricaoProduto',
                    'domingo', 'segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'restricaoHorario',
                    'valorPromocionalMix', 'valorMix'
                ]
                
                # Filtrar apenas colunas que existem
                colunas_existentes = [col for col in colunas_ordenadas if col in df_consolidado.columns]
                df_consolidado_ordenado = df_consolidado[colunas_existentes]
                
                # Exibir tabela consolidada
                st.dataframe(
                    df_consolidado_ordenado,
                    use_container_width=True,
                    height=min(400, len(df_consolidado) * 35 + 50)
                )
            else:
                st.info("Nenhuma promoção inativa encontrada.")

def exibir_promocao_dentro_loja(nome_promocao, dados_promocao, cor_marca):
    """Exibe uma promoção dentro de uma loja, incluindo categorias de grupo de venda orientada"""
    
    # Container para a promoção
    with st.container():
        # Cabeçalho da promoção
        col1, col2, col3, col4 = st.columns([4, 2, 2, 1])
        
        with col1:
            st.markdown(f"**📦 {nome_promocao}**")
        
        with col2:
            status = "🟢 Ativo" if dados_promocao['info_promocao']['promocaoAtiva'] == 'Sim' else "🔴 Inativo"
            st.markdown(status)
        
        with col3:
            nome_grupo = dados_promocao['info_promocao']['nomeGrupo']
            sequencia = dados_promocao['info_promocao'].get('sequencia')
            if sequencia is not None and _grupo_deve_exibir_sequencia(nome_grupo):
                st.markdown(f"**N{sequencia} - Grupo:** {nome_grupo}")
            else:
                st.markdown(f"**Grupo:** {nome_grupo}")
        
        with col4:
            total_produtos = len(dados_promocao.get('produtos', []))
            total_categorias = len(dados_promocao.get('categorias', {}))
            for categoria in dados_promocao.get('categorias', {}).values():
                total_produtos += len(categoria.get('produtos', []))
            st.markdown(f"**{total_produtos} produtos**")
        
        # Exibir produtos normais (se houver)
        if dados_promocao.get('produtos'):
            st.markdown("**📋 Produtos:**")
            # Criar DataFrame dos produtos
            df_produtos = pd.DataFrame(dados_promocao['produtos'])
            
            # Reordenar colunas para melhor visualização
            colunas_ordenadas = [
                'codigoProduto', 'descricaoProduto',
                'domingo', 'segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'restricaoHorario',
                'valorPromocionalMix', 'valorMix'
            ]
            
            # Filtrar apenas colunas que existem
            colunas_existentes = [col for col in colunas_ordenadas if col in df_produtos.columns]
            df_produtos_ordenado = df_produtos[colunas_existentes]
            
            # Exibir tabela de produtos
            st.dataframe(
                df_produtos_ordenado,
                use_container_width=True,
                height=min(400, len(df_produtos) * 35 + 50)
            )
        
        # Exibir categorias de grupo de venda orientada (se houver)
        # Para TODAS as marcas: produtos do grupo de venda orientada aparecem em categoria separada
        categorias = dados_promocao.get('categorias', {})
        if categorias:
            for nome_categoria, dados_categoria in categorias.items():
                produtos_categoria = dados_categoria.get('produtos', [])
                
                # Sempre exibir a categoria, mesmo que esteja vazia
                st.markdown(f"**🏷️ {nome_categoria}**")
                
                if produtos_categoria:
                    # Criar DataFrame dos produtos da categoria
                    df_produtos_categoria = pd.DataFrame(produtos_categoria)
                    
                    # Reordenar colunas para melhor visualização
                    colunas_ordenadas = [
                        'codigoProduto', 'descricaoProduto',
                        'domingo', 'segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'restricaoHorario',
                        'valorPromocionalMix', 'valorMix'
                    ]
                    
                    # Filtrar apenas colunas que existem
                    colunas_existentes = [col for col in colunas_ordenadas if col in df_produtos_categoria.columns]
                    df_produtos_categoria_ordenado = df_produtos_categoria[colunas_existentes]
                    
                    # Exibir tabela de produtos da categoria
                    st.dataframe(
                        df_produtos_categoria_ordenado,
                        use_container_width=True,
                        height=min(400, len(df_produtos_categoria) * 35 + 50)
                    )
                else:
                    # Mostrar mensagem se não houver produtos (mas categoria existe)
                    st.info(f"Nenhum produto encontrado na categoria '{nome_categoria}'.")
        
        # Se não há produtos nem categorias
        if not dados_promocao.get('produtos') and not dados_promocao.get('categorias'):
            st.info("Nenhum produto encontrado para esta promoção.")
        
        st.markdown("---")

def exibir_promocao_inativa_simples(nome_promocao, dados_promocao, cor_marca):
    """Exibe uma promoção inativa sem expansores aninhados"""
    
    # Container para a promoção inativa
    with st.container():
        # Cabeçalho da promoção inativa
        col1, col2, col3, col4 = st.columns([4, 2, 2, 1])
        
        with col1:
            st.markdown(f"**📦 {nome_promocao}**")
        
        with col2:
            st.markdown("🔴 Inativo")
        
        with col3:
            nome_grupo = dados_promocao['info_promocao']['nomeGrupo']
            sequencia = dados_promocao['info_promocao'].get('sequencia')
            if sequencia is not None and _grupo_deve_exibir_sequencia(nome_grupo):
                st.markdown(f"**N{sequencia} - Grupo:** {nome_grupo}")
            else:
                st.markdown(f"**Grupo:** {nome_grupo}")
        
        with col4:
            st.markdown(f"**{len(dados_promocao['produtos'])} produtos**")
        
        # Exibir produtos diretamente sem expander aninhado
        if dados_promocao['produtos']:
            st.markdown("**📋 Produtos:**")
            # Criar DataFrame dos produtos
            df_produtos = pd.DataFrame(dados_promocao['produtos'])
            
            # Reordenar colunas para melhor visualização
            colunas_ordenadas = [
                'codigoProduto', 'descricaoProduto',
                'domingo', 'segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'restricaoHorario',
                'valorPromocionalMix', 'valorMix'
            ]
            
            # Filtrar apenas colunas que existem
            colunas_existentes = [col for col in colunas_ordenadas if col in df_produtos.columns]
            df_produtos_ordenado = df_produtos[colunas_existentes]
            
            # Exibir tabela de produtos
            st.dataframe(
                df_produtos_ordenado,
                use_container_width=True,
                height=min(400, len(df_produtos) * 35 + 50)
            )
        else:
            st.info("Nenhum produto encontrado para esta promoção.")
        
        st.markdown("---")

def main():
    # Título
    st.title("⚡ Dashboard de Promoções")
    st.markdown(
        "<div style='text-align: center;'><strong>Marcas Grupo Impettus Degust = Espetto Carioca, Mané, Buteco Seu Rufino & Bendito</strong></div>",
        unsafe_allow_html=True,
    )
    st.image(
        "assets/logo-impettus.png",
        use_column_width=False,
        width=250,
    )
    st.markdown("---")
    
    # Sidebar com filtros e controles
    with st.sidebar:
        st.header("⚙️ Controles")
        
        # Botão de atualizar
        if st.button("🔄 Atualizar Dados", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.markdown("---")
        st.markdown("---")
        
        # Filtro de marcas
        st.header("🏪 Filtrar por Marca")
        
        filtro_todas = st.checkbox("Todas as Marcas", value=False)
        
        if filtro_todas:
            marcas_selecionadas = list(MARCAS_CONFIG.keys())
        else:
            marcas_selecionadas = []
            for marca in MARCAS_CONFIG.keys():
                if st.checkbox(marca, value=False):
                    marcas_selecionadas.append(marca)
        
        st.markdown("---")
        st.markdown(f"**📅 Última atualização:**  \n{_agora_brasilia_str()}")
    
    # Carregar e exibir dados
    if not marcas_selecionadas:
        st.warning("⚠️ Selecione pelo menos uma marca para visualizar as promoções.")
        return
    
    # Carregar dados de todas as marcas selecionadas
    todos_dados = []
    for marca in marcas_selecionadas:
        with st.spinner(f"Carregando dados de {marca}..."):
            df_marca = carregar_dados_marca(marca)
            if not df_marca.empty:
                todos_dados.append(df_marca)
    
    if not todos_dados:
        st.error("❌ Nenhum dado encontrado para as marcas selecionadas.")
        return
    
    # Combinar todos os dataframes
    df_final = pd.concat(todos_dados, ignore_index=True)
    
    # Botão de download geral (se todas as marcas foram selecionadas)
    if filtro_todas and len(marcas_selecionadas) == len(MARCAS_CONFIG):
        st.markdown("### 📥 Download Geral")
        excel_geral = criar_excel_formatado(df_final)
        st.download_button(
            label="⬇️ Download Todas as Marcas - Todas as Lojas (Excel)",
            data=excel_geral,
            file_name=f"todas_marcas_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_geral"
        )
        st.markdown("---")
    
    # Exibir dados por marca no formato hierárquico
    for marca in marcas_selecionadas:
        df_marca = df_final[df_final["marca"] == marca] if "marca" in df_final.columns else pd.DataFrame()
        
        if not df_marca.empty:
            cor = MARCAS_CONFIG[marca]["cor"]
            
            st.markdown(f"### <span style='color: {cor}'>{marca}</span>", unsafe_allow_html=True)

            # Agrupar dados por loja e promoção
            grupos_lojas = agrupar_por_loja_e_promocao(df_marca)
            
            # Informações da marca
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("🏷️ Marcas", df_marca["marca"].nunique() if "marca" in df_marca.columns else 0)
            with col2:
                st.metric("📦 Total de Lojas", len(grupos_lojas))
            with col3:
                st.metric("📊 Total de Produtos", len(df_marca))
            
            _exp_cliques_key = f"ui_exp_cliques_rede_{marca}"
            _chave_df_cliques = f"cliques_rede_df_{marca}"
            _exp_cliques_aberto = (
                st.session_state.get(_exp_cliques_key, False)
                or (
                    _chave_df_cliques in st.session_state
                    and st.session_state.get(_chave_df_cliques) is not None
                )
            )
            with st.expander(
                "📈 AÇÕES PROMOÇÕES DE REDE - Cliques (Vendas) por loja",
                expanded=_exp_cliques_aberto,
            ):
                st.markdown(
                    "Clique = Quantidade vendida do item no relatório de vendas e apenas produtos classificados como PROMOÇÕES DE REDE."
                )
                st.caption("Períodos respeitam blocos de até **30 dias** (limite da API).")
                promos_rede = listar_nomes_promocao_rede(df_marca)
                if not promos_rede:
                    st.info("Não há promoções do grupo PROMOÇÕES REDE nos dados carregados para esta marca.")
                else:
                    nome_sel = st.selectbox(
                        "Nome da promoção",
                        promos_rede,
                        key=f"sel_promo_rede_{marca}",
                    )
                    c_a, c_b, c_c = st.columns(3)
                    with c_a:
                        d_ini_acao = st.date_input(
                            "Início da ação",
                            value=date.today() - timedelta(days=29),
                            format="DD/MM/YYYY",
                            key=f"dini_acao_{marca}",
                        )
                    with c_b:
                        d_fim_analise = st.date_input(
                            "Último dia da análise",
                            value=date.today(),
                            format="DD/MM/YYYY",
                            key=f"dfim_analise_{marca}",
                        )
                    with c_c:
                        max_wr = st.number_input(
                            "Qtda de consultas por loja ao mesmo tempo (Limite 6)",
                            min_value=1,
                            max_value=6,
                            value=2,
                            key=f"max_wr_cliques_{marca}",
                        )

                    n_prods = len(codigos_produtos_promocao_rede(df_marca, nome_sel))
                    st.caption(f"Produtos agregados nesta ação: **{n_prods}** código(s).")

                    if st.button(
                        "Consultar cliques por loja e período",
                        key=f"btn_cliques_rede_{marca}",
                        on_click=_session_flag_true_callback(_exp_cliques_key),
                        use_container_width=True,
                    ):
                        if d_fim_analise < d_ini_acao:
                            st.error("A data final deve ser maior ou igual à data de início da ação.")
                        else:
                            codfranqueador = MARCAS_CONFIG[marca]["codfranqueador"]
                            prog = st.progress(0)
                            status_txt = st.empty()
                            with st.spinner(
                                "Consultando relatório de vendas por loja (pode levar alguns minutos)…"
                            ):
                                df_cliques, err = montar_tabela_cliques_promocao_rede(
                                    codfranqueador,
                                    df_marca,
                                    nome_sel,
                                    d_ini_acao,
                                    d_fim_analise,
                                    max_workers=int(max_wr),
                                    progress_bar=prog,
                                    status_label=status_txt,
                                )
                            prog.empty()
                            status_txt.empty()
                            if err:
                                st.error(err)
                            elif df_cliques is not None and not df_cliques.empty:
                                st.session_state[f"cliques_rede_df_{marca}"] = df_cliques
                                st.session_state[f"cliques_rede_meta_{marca}"] = {
                                    "promocao": nome_sel,
                                    "inicio": _formatar_data_br(d_ini_acao),
                                    "fim": _formatar_data_br(d_fim_analise),
                                    "gerado_em": _agora_brasilia_str(),
                                }
                                st.success("Consulta concluída.")
                            else:
                                st.warning("Nenhum dado retornado.")

                    chave_df = f"cliques_rede_df_{marca}"
                    if chave_df in st.session_state and st.session_state[chave_df] is not None:
                        meta = st.session_state.get(f"cliques_rede_meta_{marca}", {})
                        if meta:
                            _ge = meta.get("gerado_em")
                            _suf = f" · Consulta gerada em {_ge}" if _ge else ""
                            st.caption(
                                f"Última consulta: **{meta.get('promocao', '')}** — "
                                f"{meta.get('inicio', '')} a {meta.get('fim', '')}{_suf}"
                            )
                        _df_cliq = st.session_state[chave_df].copy()
                        _rank = _df_cliq[_df_cliq["nomeLoja"].astype(str) != "TOTAL"]
                        _top_loja = None
                        if (
                            not _rank.empty
                            and "Acumulado (cliques)" in _rank.columns
                            and "nomeLoja" in _rank.columns
                        ):
                            _acc = pd.to_numeric(
                                _rank["Acumulado (cliques)"], errors="coerce"
                            ).fillna(0)
                            _top_loja = str(_rank.loc[_acc.idxmax(), "nomeLoja"])
                        if _top_loja:
                            st.markdown(
                                f"Loja com mais aderência na ação até o momento: **{_top_loja}** 🏆"
                            )
                        _cols_show = [c for c in _df_cliq.columns if c != "codigoLoja"]
                        st.dataframe(
                            _df_cliq[_cols_show],
                            use_container_width=True,
                            hide_index=True,
                        )
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                            st.session_state[chave_df].to_excel(writer, index=False, sheet_name="Cliques")
                        buf.seek(0)
                        st.download_button(
                            label="⬇️ Baixar tabela de cliques (Excel)",
                            data=buf,
                            file_name=f"cliques_rede_{marca.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_cliques_rede_{marca}",
                        )

            # Análise de Promoções de Rede
            if f'show_modal_{marca}' in st.session_state and st.session_state[f'show_modal_{marca}']:
                with st.expander(f"📊 Promoções de Rede - {marca}", expanded=True):
                    st.markdown(f"### 📊 Análise de Promoções por Cobertura - {marca}")
                    
                    # Realizar análise
                    analise = analisar_promocoes_por_cobertura(df_marca)
                    
                    if analise:
                        # Métricas principais
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("🏪 Total de Lojas", analise['total_lojas'])
                        with col2:
                            st.metric("📦 Total de Promoções", analise['total_promocoes'])
                        with col3:
                            st.metric("📊 Média de Cobertura", f"{analise['media_cobertura']:.1f}%")
                        with col4:
                            st.metric("📈 Mediana de Cobertura", f"{analise['mediana_cobertura']:.1f}%")
                        
                        st.markdown("---")
                        
                        # Promoções por categoria de cobertura
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.markdown("#### 🎯 Promoções em TODAS as Lojas (100%)")
                            if len(analise['promocoes_100']) > 0:
                                for promocao, count in analise['promocoes_100'].items():
                                    st.markdown(f"✅ **{promocao}** ({count} lojas)")
                            else:
                                st.info("Nenhuma promoção aparece em todas as lojas")
                        
                        with col2:
                            st.markdown("#### 🚀 Promoções em 80%+ das Lojas")
                            promocoes_80 = analise['promocoes_80_plus']
                            if len(promocoes_80) > 0:
                                for promocao, count in promocoes_80.items():
                                    percentual = (count / analise['total_lojas']) * 100
                                    st.markdown(f"🟢 **{promocao}** ({count}/{analise['total_lojas']} - {percentual:.1f}%)")
                            else:
                                st.info("Nenhuma promoção com 80%+ de cobertura")
                        
                        with col3:
                            st.markdown("#### 📈 Promoções em 50%+ das Lojas")
                            promocoes_50 = analise['promocoes_50_plus']
                            if len(promocoes_50) > 0:
                                for promocao, count in promocoes_50.items():
                                    percentual = (count / analise['total_lojas']) * 100
                                    st.markdown(f"🟡 **{promocao}** ({count}/{analise['total_lojas']} - {percentual:.1f}%)")
                            else:
                                st.info("Nenhuma promoção com 50%+ de cobertura")
                        
                        st.markdown("---")
                        
                        # Top 10 promoções mais comuns
                        st.markdown("#### 🏆 Top 10 Promoções Mais Comuns")
                        if len(analise['top_10']) > 0:
                            for i, (promocao, count) in enumerate(analise['top_10'].items(), 1):
                                percentual = (count / analise['total_lojas']) * 100
                                st.markdown(f"{i:2d}. **{promocao}** - {count}/{analise['total_lojas']} lojas ({percentual:.1f}%)")
                        
                        st.markdown("---")
                        
                        # Tabela completa
                        st.markdown("#### 📋 Tabela Completa de Promoções")
                        st.dataframe(
                            analise['df_analise'],
                            use_container_width=True,
                            height=400
                        )
                        
                        # Botão para fechar análise
                        if st.button("❌ Fechar Análise", key=f"close_modal_{marca}"):
                            st.session_state[f'show_modal_{marca}'] = False
                            st.rerun()
                    else:
                        st.error("❌ Não foi possível analisar as promoções. Verifique se os dados estão corretos.")
                        if st.button("❌ Fechar Análise", key=f"close_modal_{marca}"):
                            st.session_state[f'show_modal_{marca}'] = False
                            st.rerun()
            
            st.markdown("---")
            
            # Inicializar seleção de lojas para exibição
            lojas_selecionadas_busca = []
            lojas_selecionadas_download = []
            
            # Campo de busca e seletor de lojas para download
            if "nomeLoja" in df_marca.columns and "codigoLoja" in df_marca.columns:
                lojas_info = df_marca[["codigoLoja", "nomeLoja"]].drop_duplicates().sort_values("codigoLoja")
                
                # Criar lista de lojas formatadas para seleção
                lojas_formatadas = []
                for _, loja in lojas_info.iterrows():
                    lojas_formatadas.append(f"{loja['codigoLoja']} - {loja['nomeLoja']}")

                # Seletor de lojas para exibição (substitui busca por digitação)
                st.markdown("**🔍 Buscar Lojas:**")
                lojas_selecionadas_busca = st.multiselect(
                    "Selecione as lojas para exibir (deixe vazio para exibir todas):",
                    options=lojas_formatadas,
                    default=[],
                    key=f"busca_loja_{marca}",
                    help="Seleção de lojas para filtrar a visualização na tela"
                )
                
                # Seletor de lojas para download
                st.markdown("**📥 Selecionar Lojas para Download:**")
                lojas_selecionadas_download = st.multiselect(
                    "Escolha as lojas para download (deixe vazio para todas as lojas da marca):",
                    options=lojas_formatadas,
                    default=[],
                    key=f"lojas_download_{marca}",
                    help="Se nenhuma loja for selecionada, o download incluirá todas as lojas da marca"
                )
                
                # Preparar dados para download baseado na seleção
                df_download = df_marca.copy()
                
                # Se lojas foram selecionadas, filtrar apenas essas lojas
                if lojas_selecionadas_download:
                    # Extrair códigos das lojas selecionadas
                    codigos_selecionados = []
                    for loja_str in lojas_selecionadas_download:
                        codigo = loja_str.split(" - ")[0]
                        try:
                            codigos_selecionados.append(int(codigo))
                        except:
                            codigos_selecionados.append(codigo)
                    
                    # Filtrar DataFrame
                    df_download = df_download[df_download["codigoLoja"].isin(codigos_selecionados)]
                    
                    # Label do botão de download
                    if len(lojas_selecionadas_download) == 1:
                        label_download = f"⬇️ Download {marca} - Loja Selecionada (Excel)"
                    else:
                        label_download = f"⬇️ Download {marca} - {len(lojas_selecionadas_download)} Lojas Selecionadas (Excel)"
                else:
                    # Todas as lojas da marca
                    label_download = f"⬇️ Download {marca} - Todas as Lojas (Excel)"
                
                # Botão de download (Excel formatado)
                excel_file = criar_excel_formatado(df_download)
                st.download_button(
                    label=label_download,
                    data=excel_file,
                    file_name=f"{marca.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_{marca}"
                )
                
                st.markdown("---")
            
            # Exibir lojas e suas promoções no formato hierárquico
            if grupos_lojas:
                st.markdown(f"**📋 Lojas de {marca}:**")
                
                # Filtrar lojas a serem exibidas se houver busca
                grupos_lojas_filtrados = grupos_lojas.copy()
                if lojas_selecionadas_busca and "nomeLoja" in df_marca.columns and "codigoLoja" in df_marca.columns:
                    lojas_escolhidas_set = set(lojas_selecionadas_busca)
                    grupos_lojas_filtrados = {
                        chave: dados for chave, dados in grupos_lojas.items()
                        if chave in lojas_escolhidas_set
                    }
                
                for chave_loja, dados_loja in grupos_lojas_filtrados.items():
                    # Container para cada loja
                    with st.container():
                        exibir_loja_hierarquica(chave_loja, dados_loja, cor)
                
                st.markdown("---")
            else:
                st.info(f"Nenhuma loja encontrada para {marca}")

if __name__ == "__main__":
    main()

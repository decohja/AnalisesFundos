import streamlit as st
import pandas as pd
import requests
import os

HIST_FILE = "historico_buscas.csv"

# ------------------------
# Funções auxiliares
# ------------------------

@st.cache_data
def carregar_fundos_b3():
    """Baixa lista completa de FIIs da B3"""
    url = "https://sistemaswebb3-listados.b3.com.br/fundsProxy/fundsCall/GetListFundCarteira?PageNumber=1&PageSize=2000"
    r = requests.get(url)
    data = r.json()
    fundos = []
    for f in data.get("value", []):
        fundos.append({
            "Ticker": f.get("codNegociacao"),
            "CNPJ": f.get("cnpj"),
            "Nome": f.get("denomSocial")
        })
    return pd.DataFrame(fundos)

@st.cache_data
def get_info_fundo(cnpj):
    """Consulta dados de um fundo na B3 pelo CNPJ"""
    url = f"https://sistemaswebb3-listados.b3.com.br/fundsProxy/fundsCall/GetFundInfo?cnpj={cnpj}"
    r = requests.get(url)
    if r.status_code != 200:
        return {}
    return r.json()

def analisar_fundo(info):
    """Extrai principais métricas"""
    if not info:
        return {}

    return {
        "Nome": info.get("denomSocial"),
        "CNPJ": info.get("cnpj"),
        "Patrimônio Líquido": info.get("vlPatrimonioLiquido"),
        "Nº Cotistas": info.get("qtCotasEmitidas"),
        "Liquidez Diária": info.get("vlVolumeNegociado"),
        "P/VP": info.get("pvpa"),
        "Dividend Yield (12m)": info.get("dy12Meses"),
        "Rentabilidade (12m)": info.get("rentab12Meses")
    }

def recomendacao(dados):
    """Define se vale a pena ou não"""
    try:
        dy = float(dados.get("Dividend Yield (12m)", 0) or 0)
        pvp = float(dados.get("P/VP", 0) or 0)
    except:
        return "⚪ Sem dados suficientes"

    if dy > 10 and pvp < 1:
        return "🟢 Bom ponto de entrada"
    elif dy > 8 and pvp <= 1.05:
        return "🟡 Razoável, mas atenção"
    elif pvp > 1.1:
        return "🔴 Caro no momento"
    else:
        return "⚪ Neutro"

def salvar_historico(df_novo):
    """Salva ou atualiza histórico de buscas"""
    if os.path.exists(HIST_FILE):
        df_hist = pd.read_csv(HIST_FILE)
        df_final = pd.concat([df_hist, df_novo]).drop_duplicates(subset=["CNPJ"], keep="last")
    else:
        df_final = df_novo
    df_final.to_csv(HIST_FILE, index=False)

def carregar_historico():
    if os.path.exists(HIST_FILE):
        return pd.read_csv(HIST_FILE)
    return pd.DataFrame()

# ------------------------
# Interface do site
# ------------------------

st.set_page_config(page_title="Análises de FIIs", layout="wide")
st.title("📊 Analisador de Fundos Imobiliários (FIIs)")

# Carregar mapa FII ↔ CNPJ
df_fundos = carregar_fundos_b3()

# Seleção de fundos
tickers = df_fundos["Ticker"].dropna().unique()
escolhidos = st.multiselect("Selecione os fundos:", options=sorted(tickers), default=["MXRF11", "VGHF11"])

# Mostrar análises
analises = {}
for t in escolhidos:
    cnpj = df_fundos.loc[df_fundos["Ticker"] == t, "CNPJ"].values[0]
    info = get_info_fundo(cnpj)
    dados = analisar_fundo(info)
    if dados:
        dados["Recomendação"] = recomendacao(dados)
        analises[t] = dados

if analises:
    st.subheader("🔎 Análise dos Fundos")
    df_result = pd.DataFrame(analises).T
    st.dataframe(df_result, use_container_width=True)

    # Salvar histórico
    salvar_historico(df_result.reset_index(drop=True))

    # Comparação simples
    if len(analises) > 1:
        st.subheader("⚖️ Comparação")
        st.dataframe(df_result.T, use_container_width=True)

# Histórico de buscas
st.subheader("📜 Histórico de Fundos Pesquisados")
df_hist = carregar_historico()
if not df_hist.empty:
    st.dataframe(df_hist, use_container_width=True)
else:
    st.info("Nenhum histórico salvo ainda.")

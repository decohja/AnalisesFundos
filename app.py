import streamlit as st
import pandas as pd
import requests
import os

HIST_FILE = "historico_buscas.csv"
MAPA_FILE = "mapa_fundos.csv"

# ------------------------
# Funções auxiliares
# ------------------------

def carregar_mapa():
    if os.path.exists(MAPA_FILE):
        return pd.read_csv(MAPA_FILE, dtype=str)
    else:
        st.error("❌ Arquivo mapa_fundos.csv não encontrado.")
        return pd.DataFrame(columns=["Ticker", "CNPJ", "Nome"])

def get_info_fundo(cnpj):
    """Consulta dados públicos da B3 para um fundo via endpoint detalhado"""
    url = f"https://sistemaswebb3-listados.b3.com.br/fundsProxy/fundsCall/GetFundDetail?cnpj={cnpj}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        data = r.json()
    except Exception:
        return {}

    value = data.get("value", {})
    return {
        "Nome": value.get("denomSocial"),
        "CNPJ": value.get("cnpj"),
        "Patrimônio Líquido": value.get("vlPatrimonioLiquido"),
        "Nº Cotistas": value.get("qtCotasEmitidas"),
        "Liquidez Diária": value.get("vlVolumeNegociado"),
        "P/VP": value.get("pvpa"),
        "Dividend Yield (12m)": value.get("dy12Meses"),
        "Rentabilidade (12m)": value.get("rentab12Meses"),
    }

def recomendacao(dados):
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

st.set_page_config(page_title="Analisador de FIIs", layout="wide")
st.title("📊 Analisador de Fundos Imobiliários (FIIs)")

mapa = carregar_mapa()
if not mapa.empty:
    tickers = mapa["Ticker"].dropna().unique()
    escolhidos = st.multiselect("Selecione os fundos:", options=sorted(tickers), default=["MXRF11", "VGHF11"])

    analises = {}
    for t in escolhidos:
        cnpj = mapa.loc[mapa["Ticker"] == t, "CNPJ"].values[0]
        dados = get_info_fundo(cnpj)
        if dados:
            dados["Recomendação"] = recomendacao(dados)
            analises[t] = dados

    if analises:
        st.subheader("🔎 Análise dos Fundos")
        df_result = pd.DataFrame(analises).T
        st.dataframe(df_result, use_container_width=True)

        salvar_historico(df_result.reset_index(drop=True))

        if len(analises) > 1:
            st.subheader("⚖️ Comparação")
            st.dataframe(df_result.T, use_container_width=True)

st.subheader("📜 Histórico de Fundos Pesquisados")
df_hist = carregar_historico()
if not df_hist.empty:
    st.dataframe(df_hist, use_container_width=True)
else:
    st.info("Nenhum histórico salvo ainda.")

import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="Analisador de FIIs", layout="wide")

# 🔑 Token da brapi
BRAPI_TOKEN = st.secrets.get("BRAPI_TOKEN", os.environ.get("BRAPI_TOKEN", ""))

# Função para buscar dados na brapi
def buscar_fii(ticker):
    try:
        url = f"https://brapi.dev/api/quote/{ticker}.SA?modules=defaultKeyStatistics,dividends"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {BRAPI_TOKEN}"
        }
        r = requests.get(url, headers=headers)

        if r.status_code != 200:
            return {"Ticker": ticker, "Erro": f"{r.status_code} {r.reason}"}

        data = r.json().get("results", [])
        if not data:
            return {"Ticker": ticker, "Erro": "Sem resultados"}

        data = data[0]
        return {
            "Ticker": ticker.upper(),
            "Preço Atual (R$)": data.get("regularMarketPrice"),
            "P/VP": data.get("defaultKeyStatistics", {}).get("priceToBook"),
            "Dividend Yield (12m %)": data.get("dividends", {}).get("yield12m"),
            "Liquidez Diária": data.get("regularMarketVolume"),
        }
    except Exception as e:
        return {"Ticker": ticker, "Erro": str(e)}

# Função de recomendação
def recomendar(pvp):
    if pvp is None:
        return "⚠️ Sem dados", "gray"
    if pvp < 1:
        return "✅ Barato", "green"
    elif 1 <= pvp <= 1.1:
        return "🟡 Neutro", "orange"
    else:
        return "❌ Caro", "red"

# Layout
st.title("📊 Analisador de Fundos Imobiliários (FIIs) — dados ao vivo")

entrada = st.text_input("Digite 1 ou mais FIIs (separados por vírgula):", "MXRF11, HGLG11")

if st.button("🔎 Buscar"):
    lista = [t.strip().upper() for t in entrada.split(",")]
    resultados = [buscar_fii(t) for t in lista]
    df = pd.DataFrame(resultados)

    # Cards individuais
    st.subheader("📌 Resultados Individuais")
    for _, row in df.iterrows():
        pvp = row.get("P/VP")
        rec_text, color = recomendar(pvp)
        st.markdown(
            f"""
            <div style="border-radius:10px; padding:15px; margin:10px 0;
                        background-color:{color}; color:white">
                <h3>{row['Ticker']}</h3>
                <b>Preço Atual:</b> {row.get('Preço Atual (R$)', '-')}<br>
                <b>P/VP:</b> {pvp if pvp is not None else '-'}<br>
                <b>DY 12m:</b> {row.get('Dividend Yield (12m %)', '-')}%<br>
                <b>Liquidez Diária:</b> {row.get('Liquidez Diária', '-')}<br>
                <b>Recomendação:</b> {rec_text}
            </div>
            """,
            unsafe_allow_html=True
        )

    # Tabela comparativa
    st.subheader("📈 Comparação")
    if "P/VP" not in df.columns:
        df["P/VP"] = None
    df["Recomendação"], _ = zip(*df["P/VP"].apply(recomendar))
    st.dataframe(df, use_container_width=True)

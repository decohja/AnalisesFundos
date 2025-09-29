import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="Analisador de Fundos Imobiliários (FIIs)", layout="wide")

# 🔑 pega token do secrets ou variável de ambiente
BRAPI_TOKEN = st.secrets.get("BRAPI_TOKEN", os.environ.get("BRAPI_TOKEN", ""))

# DEBUG → só pra você ver se o token está sendo lido (pode remover depois)
if not BRAPI_TOKEN:
    st.error("❌ Nenhum token encontrado! Verifique se o secrets.toml está configurado.")
else:
    st.success("✅ Token carregado com sucesso.")

# Função para buscar dados na brapi
def buscar_fii(ticker):
    try:
        url = f"https://brapi.dev/api/quote/{ticker}?modules=defaultKeyStatistics,dividends"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {BRAPI_TOKEN}"
        }
        r = requests.get(url, headers=headers)

        if r.status_code != 200:
            return {"Ticker": ticker, "Erro": f"{r.status_code} {r.reason}"}

        data = r.json().get("results", [])[0]

        return {
            "Ticker": ticker.upper(),
            "Preço Atual (R$)": data.get("regularMarketPrice"),
            "P/VP": data.get("defaultKeyStatistics", {}).get("priceToBook", None),
            "Dividend Yield (12m %)": data.get("dividends", {}).get("yield12m", None),
            "Liquidez Diária": data.get("regularMarketVolume"),
        }
    except Exception as e:
        return {"Ticker": ticker, "Erro": str(e)}


# Layout principal
st.title("📊 Analisador de Fundos Imobiliários (FIIs) — dados ao vivo")

st.expander("ℹ️ Como funciona").write(
    "Digite 1 ou mais tickers de FIIs (ex.: MXRF11, HGLG11) e veja os principais indicadores em tempo real via brapi.dev."
)

entrada = st.text_input("Digite 1 ou mais FIIs (separados por vírgula):", "MXRF11, HGLG11")

if st.button("🔎 Buscar"):
    lista = [t.strip().upper() for t in entrada.split(",")]
    resultados = []

    for ticker in lista:
        dados = buscar_fii(ticker)
        resultados.append(dados)

    df = pd.DataFrame(resultados)
    st.subheader("Resultado")
    st.dataframe(df, use_container_width=True)

    if "Erro" not in df.columns:
        # Recomendação simples
        df["Recomendação"] = df.apply(
            lambda row: "✅ Barato" if row["P/VP"] and row["P/VP"] < 1
            else "⚠️ Neutro" if row["P/VP"] and 1 <= row["P/VP"] <= 1.1
            else "❌ Caro",
            axis=1
        )
        st.subheader("📈 Análise com recomendação")
        st.dataframe(df, use_container_width=True)

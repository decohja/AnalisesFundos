import streamlit as st
import requests
import pandas as pd

st.set_page_config(page_title="Analisador de FIIs", layout="wide")

# Função para buscar dados do StatusInvest
def buscar_dados_statusinvest(ticker: str):
    try:
        url = f"https://statusinvest.com.br/fii/{ticker.lower()}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            return None

        # API interna JSON
        api_url = f"https://statusinvest.com.br/fii/ticker/{ticker}"
        r2 = requests.get(api_url, headers=headers)
        if r2.status_code == 200:
            data = r2.json()
            return {
                "Ticker": ticker.upper(),
                "Preço atual (R$)": data.get("price"),
                "Preço teto (R$)": data.get("priceTarget"),
                "Dividend Yield 12m (%)": data.get("dividendYield"),
                "P/VP": data.get("pvp"),
                "Setor": data.get("sector"),
            }
        return None
    except Exception as e:
        st.error(f"Erro ao buscar {ticker}: {e}")
        return None


# Layout do app
st.title("📊 Analisador de FIIs (StatusInvest)")

tickers = st.text_input("Digite os tickers separados por vírgula (ex.: MXRF11, HGLG11)", "MXRF11, HGLG11")

if st.button("Buscar dados"):
    lista = [t.strip().upper() for t in tickers.split(",")]
    resultados = []
    for t in lista:
        dados = buscar_dados_statusinvest(t)
        if dados:
            resultados.append(dados)

    if resultados:
        df = pd.DataFrame(resultados)
        st.dataframe(df)

        # análise simples: se preço atual <= preço teto, vale a pena
        df["Vale a pena?"] = df.apply(
            lambda row: "✅ SIM (barato)" if row["Preço atual (R$)"] <= row["Preço teto (R$)"]
            else "❌ NÃO (caro)", axis=1
        )

        st.subheader("📈 Análise com regra simples")
        st.dataframe(df[["Ticker", "Preço atual (R$)", "Preço teto (R$)", "P/VP", "Dividend Yield 12m (%)", "Vale a pena?"]])
    else:
        st.warning("Nenhum dado encontrado.")

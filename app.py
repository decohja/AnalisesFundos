import os
import time
import json
import re
import requests
import pandas as pd
import streamlit as st

# ---------- CONFIG BÁSICA ----------
st.set_page_config(page_title="Analisador de FIIs (ao vivo)", layout="wide")
st.title("📊 Analisador de Fundos Imobiliários (FIIs) — dados ao vivo")

# Lê token da brapi (adicione em .streamlit/secrets.toml: BRAPI_TOKEN="seu_token")
BRAPI_TOKEN = st.secrets.get("BRAPI_TOKEN", os.environ.get("BRAPI_TOKEN", ""))

# ---------- HELPERS ----------
def _pt_number(x: str):
    """Converte '1.234,56' -> 1234.56 e '—'/'-' -> None"""
    if x is None:
        return None
    s = str(x).strip().replace(".", "").replace(" ", "").replace("\xa0", "")
    s = s.replace(",", ".")
    try:
        return float(re.sub(r"[^0-9\.\-]", "", s))
    except Exception:
        return None

def regra_recomendacao(pvp, dy12):
    """
    Regras simples inspiradas no que você pediu:
      - P/VP <= 1.00  => +2 pts (barato vs VP)
      - 1.00 < P/VP <= 1.03 => +1 pt (ok, mas no teto)
      - P/VP > 1.05   => -2 pts (caro)
      - DY 12m >= 12% => +2 pts (renda forte)
      - 8% <= DY <12% => +1 pt (renda ok)
      - DY 12m < 6%   => -1 pt (renda fraca)
    """
    score = 0
    if pvp is not None:
        if pvp <= 1.00:
            score += 2
        elif pvp <= 1.03:
            score += 1
        elif pvp > 1.05:
            score -= 2
    if dy12 is not None:
        if dy12 >= 12:
            score += 2
        elif dy12 >= 8:
            score += 1
        elif dy12 < 6:
            score -= 1

    if score >= 3:
        return "✅ Interessante", score
    if score >= 1:
        return "🟨 Neutro", score
    return "❌ Caro", score

def buscar_brapi(ticker: str):
    """
    Busca dados do FII na brapi:
      - regularMarketPrice
      - defaultKeyStatistics.priceToBook (P/VP)
      - defaultKeyStatistics.dividendYield (DY TTM em %)
    Também puxa 'dividends=true' pra ter um fallback se precisar.
    """
    base = "https://brapi.dev/api/quote"
    params = {
        "modules": "defaultKeyStatistics",
        "dividends": "true"
    }
    headers = {}
    if BRAPI_TOKEN:
        headers["Authorization"] = f"Bearer {BRAPI_TOKEN}"
    url = f"{base}/{ticker.upper()}"
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json().get("results", [])
    if not data:
        raise ValueError("Sem resultados da brapi para o ticker.")

    item = data[0]
    price = item.get("regularMarketPrice")

    pvp = None
    dy12 = None

    # defaultKeyStatistics geralmente traz isto para FIIs:
    dks = item.get("defaultKeyStatistics") or {}
    # priceToBook == P/VP (para FIIs funciona como “P/VP do patrimônio”)
    pvp = dks.get("priceToBook")
    # dividendYield já vem em percentuais (ex.: 12.34)
    dy12 = dks.get("dividendYield")

    # Fallback de DY: somar últimos 12 meses de proventos / preço
    if dy12 is None:
        divs = item.get("dividendsData") or []
        # pega últimos 12 meses
        df_divs = pd.DataFrame(divs)
        if not df_divs.empty and "value" in df_divs:
            # filtra últimos 365 dias a partir do "paymentDate" (quando existe)
            df_divs["paymentDate"] = pd.to_datetime(df_divs.get("paymentDate", pd.NaT), errors="coerce")
            limite = pd.Timestamp.utcnow() - pd.Timedelta(days=365)
            df_divs = df_divs[df_divs["paymentDate"] >= limite]
            total = df_divs["value"].sum()
            if price:
                dy12 = (total / float(price)) * 100.0

    return {
        "Ticker": ticker.upper(),
        "Preço (R$)": price,
        "P/VP": pvp,
        "Dividend Yield 12m (%)": dy12,
    }

# ---------- UI ----------
with st.expander("Como funciona", expanded=False):
    st.markdown(
        """
        - Fonte **brapi.dev** (dados da B3/CVM). Para FIIs, usamos *priceToBook* como **P/VP** e *dividendYield* como **DY 12m**.
        - Coloque seu token em **.streamlit/secrets.toml**:
          ```
          BRAPI_TOKEN="SEU_TOKEN_AQUI"
          ```
        - Regras de avaliação (simplificadas):
            - **P/VP ≤ 1,00** ajuda bastante; **> 1,05** pesa contra.
            - **DY ≥ 12%** é forte; **8–12%** ok; **< 6%** fraco.
        """
    )

tickers_input = st.text_input(
    "Digite 1 ou mais FIIs (separados por vírgula):",
    value="MXRF11, HGLG11"
)

colA, colB = st.columns([1, 4])
with colA:
    start = st.button("🔎 Buscar")
with colB:
    st.caption("Ex.: MXRF11, HGLG11, KNRI11, CPTS11…")

# Área de resultados
placeholder = st.empty()

# Histórico na sessão
if "historico" not in st.session_state:
    st.session_state.historico = []

if start:
    tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
    resultados = []
    for tk in tickers:
        try:
            dados = buscar_brapi(tk)
            rec, score = regra_recomendacao(dados.get("P/VP"), dados.get("Dividend Yield 12m (%)"))
            dados["Recomendação"] = rec
            dados["Score"] = score
            resultados.append(dados)
            time.sleep(0.15)  # evita rate-limit
        except Exception as e:
            resultados.append({
                "Ticker": tk,
                "Erro": str(e)
            })

    df = pd.DataFrame(resultados)

    # salva no histórico da sessão (apenas linhas válidas)
    validos = df[df["Erro"].isna()] if "Erro" in df.columns else df
    if not validos.empty:
        st.session_state.historico.append(validos.copy())

    # Exibição
    st.subheader("Resultado")
    if not df.empty:
        # formata
        def fmt_pct(v):
            return "" if pd.isna(v) else f"{v:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")
        def fmt_num(v):
            return "" if pd.isna(v) else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        show = df.copy()
        if "Preço (R$)" in show.columns:
            show["Preço (R$)"] = show["Preço (R$)"].map(fmt_num)
        if "P/VP" in show.columns:
            show["P/VP"] = show["P/VP"].map(fmt_num)
        if "Dividend Yield 12m (%)" in show.columns:
            show["Dividend Yield 12m (%)"] = show["Dividend Yield 12m (%)"].map(fmt_pct)
        st.dataframe(show, use_container_width=True)

    # Comparador simples
    if not validos.empty and len(validos) >= 2:
        st.subheader("Comparação rápida")
        cols = ["Ticker", "Preço (R$)", "P/VP", "Dividend Yield 12m (%)", "Recomendação"]
        comp = validos[cols].sort_values("P/VP")
        st.dataframe(comp, use_container_width=True)

# Histórico + download
st.subheader("Histórico desta sessão")
if st.session_state.historico:
    hist = pd.concat(st.session_state.historico, ignore_index=True)
    st.dataframe(hist, use_container_width=True)
    csv = hist.to_csv(index=False, sep=";").encode("utf-8")
    st.download_button("⬇️ Baixar histórico (CSV)", data=csv, file_name="historico_fiis.csv", mime="text/csv")
else:
    st.caption("Sem buscas ainda.")

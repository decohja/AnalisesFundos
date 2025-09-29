import streamlit as st
import requests, re
from bs4 import BeautifulSoup
import pandas as pd
import os
from datetime import datetime

st.set_page_config(page_title="Analisador de FIIs", page_icon="📊", layout="wide")

# ======== COLETORES ========
@st.cache_data(show_spinner=False, ttl=3600)
def fetch_investidor10(ticker: str) -> dict:
    url = f"https://investidor10.com.br/fiis/{ticker.lower()}/"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return {}
    soup = BeautifulSoup(r.text, "html.parser")

    def find_value(label_patterns):
        # procura um nó cujo texto case com algum dos padrões e tenta extrair o número próximo
        label_node = None
        for pat in label_patterns:
            el = soup.find(string=re.compile(pat, re.I))
            if el:
                label_node = el
                break
        if not label_node:
            return None
        try:
            parent = label_node.parent
            # tenta pegar números (inclui % e vírgulas/pontos brasileiros)
            text = parent.get_text(" ").strip()
            nums = re.findall(r'[-+]?\d[\d\.\,]*%?', text)
            if nums:
                return nums[-1]
            sib = parent.find_next()
            if sib:
                txt = sib.get_text(" ").strip()
                nums = re.findall(r'[-+]?\d[\d\.\,]*%?', txt)
                if nums:
                    return nums[0]
        except Exception:
            pass
        return None

    data = {
        "Fonte": "Investidor10",
        "Ticker": ticker.upper(),
        "Dividend Yield 12m": find_value(["Dividend\\s*Yield", r"\bDY\b", "Dividendos"]),
        "P/VP": find_value([r"P\/?\s*VP", "P/VPA"]),
        "Patrimônio líquido": find_value(["Patrim[oô]nio.*l[ií]quido"]),
        "Nº de cotistas": find_value(["Cotistas", "Número de cotistas"]),
        "Liquidez diária": find_value(["Liquidez.*di[aá]ria", "Volume m[eé]dio"]),
    }
    # remove chaves vazias
    return {k: v for k, v in data.items() if v}

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_statusinvest(ticker: str) -> dict:
    url = f"https://statusinvest.com.br/fundos-imobiliarios/{ticker.lower()}"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return {}
    soup = BeautifulSoup(r.text, "html.parser")

    def pick(title):
        el = soup.find("strong", {"title": title})
        return el.get_text(strip=True) if el else None

    data = {
        "Fonte": "StatusInvest",
        "Ticker": ticker.upper(),
        "Dividend Yield 12m": pick("Dividend Yield"),
        "P/VP": pick("P/VP"),
        "Patrimônio líquido": pick("Patrimônio líquido"),
        "Nº de cotistas": pick("Número de cotistas"),
        "Liquidez diária": pick("Média volume diário"),
    }
    return {k: v for k, v in data.items() if v}

# ======== HISTÓRICO ========
def load_history() -> pd.DataFrame:
    cols = ["Data","Ticker","Dividend Yield 12m","P/VP","Patrimônio líquido","Nº de cotistas","Liquidez diária","Fonte","Notas"]
    path = "data/analises.csv"
    if os.path.exists(path):
        df = pd.read_csv(path)
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        return df[cols]
    return pd.DataFrame(columns=cols)

def save_history(df: pd.DataFrame):
    os.makedirs("data", exist_ok=True)
    df.to_csv("data/analises.csv", index=False)

# ======== UI ========
st.title("📊 Analisador de FIIs")
st.caption("Busque automaticamente (Investidor10/StatusInvest), edite e salve sua análise para comparar depois.")

ticker = st.text_input("Ticker do FII (ex.: MXRF11)").strip().upper()
col_pref1, col_pref2 = st.columns(2)
with col_pref1:
    fonte_pref = st.selectbox("Fonte preferida", ["Investidor10", "StatusInvest"])

if st.button("Buscar dados"):
    data = {}
    if fonte_pref == "Investidor10":
        data = fetch_investidor10(ticker) or fetch_statusinvest(ticker)
    else:
        data = fetch_statusinvest(ticker) or fetch_investidor10(ticker)
    if not data:
        st.error("Não consegui coletar automaticamente. Preencha manualmente abaixo e salve.")
        data = {"Ticker": ticker}
    st.session_state["draft"] = data

draft = st.session_state.get("draft", {"Ticker": ticker} if ticker else {})

with st.form("form_save"):
    st.subheader("📝 Revisar/editar dados antes de salvar")
    c1, c2 = st.columns(2)
    with c1:
        dy = st.text_input("Dividend Yield 12m", draft.get("Dividend Yield 12m", ""))
        pvp = st.text_input("P/VP", draft.get("P/VP", ""))
        pl = st.text_input("Patrimônio líquido", draft.get("Patrimônio líquido", ""))
    with c2:
        cot = st.text_input("Nº de cotistas", draft.get("Nº de cotistas", ""))
        liq = st.text_input("Liquidez diária", draft.get("Liquidez diária", ""))
        fonte = st.text_input("Fonte", draft.get("Fonte", ""))
    notas = st.text_area("Notas (opcional)", "")
    submitted = st.form_submit_button("Salvar análise")
    if submitted:
        if not ticker:
            st.warning("Informe o ticker.")
        else:
            df = load_history()
            row = {
                "Data": datetime.now().strftime("%Y-%m-%d"),
                "Ticker": ticker,
                "Dividend Yield 12m": dy,
                "P/VP": pvp,
                "Patrimônio líquido": pl,
                "Nº de cotistas": cot,
                "Liquidez diária": liq,
                "Fonte": fonte,
                "Notas": notas
            }
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            save_history(df)
            st.success("Salvo!")

st.subheader("📂 Histórico de análises")
df = load_history()
st.dataframe(df, use_container_width=True)

st.download_button("⬇️ Baixar CSV", data=df.to_csv(index=False), file_name="analises.csv", mime="text/csv")

uploaded = st.file_uploader("Subir CSV para restaurar/mesclar histórico", type=["csv"])
if uploaded is not None:
    df_up = pd.read_csv(uploaded)
    df = pd.concat([df, df_up], ignore_index=True).drop_duplicates(subset=["Data","Ticker"], keep="last")
    save_history(df)
    st.success("Histórico atualizado a partir do CSV.")

st.subheader("⚖️ Comparar FIIs salvos")
if len(df) >= 2:
    c1, c2 = st.columns(2)
    with c1:
        f1 = st.selectbox("Fundo A", sorted(df["Ticker"].unique()))
    with c2:
        f2 = st.selectbox("Fundo B", sorted([t for t in df["Ticker"].unique() if t != f1]))
    if st.button("Comparar agora"):
        comp = df[df["Ticker"].isin([f1, f2])]
        st.table(comp[["Ticker","Dividend Yield 12m","P/VP","Patrimônio líquido","Nº de cotistas","Liquidez diária","Fonte","Data"]])

        def to_float(x):
            if pd.isna(x): return None
            x = str(x).replace("%","").replace(".","").replace(",",".")
            try: return float(x)
            except: return None

        # Score simples (DY maior é melhor; P/VP mais próximo de 1 e <=1 é melhor)
        a, b = comp.iloc[0], comp.iloc[1]
        scoreA = scoreB = 0
        dy1, dy2 = to_float(a["Dividend Yield 12m"]), to_float(b["Dividend Yield 12m"])
        pvp1, pvp2 = to_float(a["P/VP"]), to_float(b["P/VP"])

        if dy1 is not None and dy2 is not None:
            if dy1 > dy2: scoreA += 1
            elif dy2 > dy1: scoreB += 1

        def pvp_penalty(p):  # quanto menor, melhor; preferimos <=1
            if p is None: return 10
            return abs(1 - p)

        if pvp1 is not None and pvp2 is not None:
            if pvp1 <= 1 < pvp2: scoreA += 1
            elif pvp2 <= 1 < pvp1: scoreB += 1
            else:
                if pvp_penalty(pvp1) < pvp_penalty(pvp2): scoreA += 1
                elif pvp_penalty(pvp2) < pvp_penalty(pvp1): scoreB += 1

        st.markdown(f"**Placar:** {a['Ticker']} {scoreA} × {scoreB} {b['Ticker']}")

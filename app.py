import streamlit as st
import requests, re
from bs4 import BeautifulSoup
import pandas as pd
import os
from datetime import datetime

st.set_page_config(page_title="Analisador de FIIs", page_icon="📊", layout="wide")

# ----------------- Helpers -----------------
def to_float_br(s):
    if s is None: return None
    s = str(s)
    s = s.replace("\xa0"," ").replace("%","").strip()
    # remove separador de milhar e troca vírgula por ponto
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.count(",") == 1 and s.count(".") >= 1:
        # padrão brasileiro (1.234,56)
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def plausibility_check(d):
    """Descarta valores absurdos e retorna None quando inválido."""
    out = dict(d)
    dy = to_float_br(out.get("Dividend Yield 12m"))
    if dy is None or dy < 0 or dy > 40:  # FIIs normalmente < 30–35%/a
        out["Dividend Yield 12m"] = None

    pvp = to_float_br(out.get("P/VP"))
    if pvp is None or pvp < 0.4 or pvp > 1.8:
        out["P/VP"] = None

    pl = to_float_br(out.get("Patrimônio líquido"))
    # muitas fontes trazem PL em bilhões/mi; aqui aceito qualquer número > 10
    if pl is None or pl <= 10:
        out["Patrimônio líquido"] = None

    cot = to_float_br(out.get("Nº de cotistas"))
    if cot is None or cot < 200:
        out["Nº de cotistas"] = None

    liq = to_float_br(out.get("Liquidez diária"))
    if liq is None:
        out["Liquidez diária"] = None

    return out

def merge_sources(primary, fallback):
    """Prefere primary; completa campos faltantes com fallback."""
    keys = ["Ticker","Dividend Yield 12m","P/VP","Patrimônio líquido","Nº de cotistas","Liquidez diária","Fonte"]
    result = {k: primary.get(k) for k in keys}
    for k in keys:
        if (result.get(k) in [None, "", "N/A"]) and fallback:
            result[k] = fallback.get(k)
    return result

# ----------------- Scrapers -----------------
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

    raw = {
        "Fonte": "StatusInvest",
        "Ticker": ticker.upper(),
        "Dividend Yield 12m": pick("Dividend Yield"),
        "P/VP": pick("P/VP"),
        "Patrimônio líquido": pick("Patrimônio líquido"),
        "Nº de cotistas": pick("Número de cotistas"),
        "Liquidez diária": pick("Média volume diário"),
    }
    return plausibility_check(raw)

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_investidor10(ticker: str) -> dict:
    # scraping mais "flexível" — pode quebrar se layout mudar
    url = f"https://investidor10.com.br/fiis/{ticker.lower()}/"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ").strip()

    def find_after(label_regex, want_percent=False):
        m = re.search(label_regex, text, re.I)
        if not m: return None
        # pega uma janela de 120 chars depois do rótulo e busca o primeiro número
        window = text[m.end(): m.end()+120]
        if want_percent:
            n = re.search(r"[-+]?\d[\d\.\,]*\s?%", window)
        else:
            n = re.search(r"[-+]?\d[\d\.\,]*", window)
        return n.group(0).strip() if n else None

    raw = {
        "Fonte": "Investidor10",
        "Ticker": ticker.upper(),
        "Dividend Yield 12m": find_after(r"Dividend\s*Yield|DY\s*12", want_percent=True),
        "P/VP": find_after(r"P\/?\s*VP|P\/VPA"),
        "Patrimônio líquido": find_after(r"Patrim[oô]nio\s*l[ií]quido|PL\s*\(R\$"),
        "Nº de cotistas": find_after(r"(N[uú]mero\s*de\s*)?cotistas"),
        "Liquidez diária": find_after(r"Liquidez\s*di[aá]ria|Volume\s*m[eé]dio"),
    }
    return plausibility_check(raw)

# ----------------- Storage -----------------
def load_history() -> pd.DataFrame:
    cols = ["Data","Ticker","Dividend Yield 12m","P/VP",
            "Patrimônio líquido","Nº de cotistas","Liquidez diária","Fonte","Notas"]
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

# ----------------- UI -----------------
st.title("📊 Analisador de FIIs")
st.caption("Busca automática (StatusInvest → Investidor10 com validação), edição e histórico para comparação.")

ticker = st.text_input("Ticker do FII (ex.: MXRF11)").strip().upper()
pref = st.selectbox("Fonte preferida", ["Automático (recomendado)", "StatusInvest", "Investidor10"])

if st.button("Buscar dados"):
    if not ticker:
        st.warning("Informe o ticker.")
    else:
        if pref.startswith("Automático"):
            a = fetch_statusinvest(ticker)
            b = fetch_investidor10(ticker)
            data = merge_sources(a, b)
            if not a and b:
                st.info("StatusInvest falhou; usei Investidor10.")
            elif a and any(v is None for k,v in a.items() if k not in ["Fonte","Ticker"]):
                st.info("Completei campos ausentes com Investidor10.")
        elif pref == "StatusInvest":
            data = fetch_statusinvest(ticker) or fetch_investidor10(ticker)
        else:
            data = fetch_investidor10(ticker) or fetch_statusinvest(ticker)

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
        if not draft.get("Ticker"):
            st.warning("Busque primeiro ou informe o ticker.")
        else:
            df = load_history()
            row = {
                "Data": datetime.now().strftime("%Y-%m-%d"),
                "Ticker": draft.get("Ticker", ticker),
                "Dividend Yield 12m": dy,
                "P/VP": pvp,
                "Patrimônio líquido": pl,
                "Nº de cotistas": cot,
                "Liquidez diária": liq,
                "Fonte": fonte or pref,
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

        def nf(x):
            try:
                v = to_float_br(x)
                return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if v is not None else "-"
            except:
                return x

        a, b = comp.iloc[0], comp.iloc[1]
        st.markdown(f"**Resumo:** DY {a['Ticker']} = {nf(a['Dividend Yield 12m'])}% | P/VP = {nf(a['P/VP'])}  •  "
                    f"DY {b['Ticker']} = {nf(b['Dividend Yield 12m'])}% | P/VP = {nf(b['P/VP'])}")

        # Score simples (DY maior vence; P/VP <= 1 preferido; se os dois >1, vale o mais próximo de 1)
        scoreA = scoreB = 0
        dy1, dy2 = to_float_br(a["Dividend Yield 12m"]), to_float_br(b["Dividend Yield 12m"])
        pvp1, pvp2 = to_float_br(a["P/VP"]), to_float_br(b["P/VP"])
        if dy1 is not None and dy2 is not None:
            scoreA += dy1 > dy2
            scoreB += dy2 > dy1
        def pvp_penalty(p): return 10 if p is None else abs(1 - p)
        if pvp1 is not None and pvp2 is not None:
            if pvp1 <= 1 < pvp2: scoreA += 1
            elif pvp2 <= 1 < pvp1: scoreB += 1
            else:
                scoreA += pvp_penalty(pvp1) < pvp_penalty(pvp2)
                scoreB += pvp_penalty(pvp2) < pvp_penalty(pvp1)
        st.markdown(f"**Placar:** {a['Ticker']} {int(scoreA)} × {int(scoreB)} {b['Ticker']}")

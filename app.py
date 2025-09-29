import streamlit as st
import pandas as pd
import requests, re, os
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry

# =================== Config ===================
st.set_page_config(page_title="Analisador de FIIs", page_icon="📊", layout="wide")
HIST_FILE = "historico_buscas.csv"
MAPA_FILE = "mapa_fundos.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    retries = Retry(total=5, backoff_factor=0.6,
                    status_forcelist=[429,500,502,503,504],
                    allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s

# =================== Utils ===================
def clean_num_pt(s):
    if not s: return None
    s = str(s).replace("%","").replace("\xa0"," ").strip()
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.count(",") == 1 and s.count(".") >= 1:
        s = s.replace(".","").replace(",",".")
    elif s.count(",") == 1:
        s = s.replace(",",".")
    try: return float(s)
    except: return None

def text_near_label(soup, patterns):
    for pat in patterns:
        node = soup.find(string=re.compile(pat, re.I))
        if not node: continue
        chunk = node.parent.get_text(" ", strip=True)
        nums = re.findall(r"[-+]?\d[\d\.\,]*%?", chunk)
        if nums: return nums[-1]
    return ""

# =================== Scraping Investidor10 ===================
def fetch_details(session, tk):
    url = f"https://investidor10.com.br/fiis/{tk.lower()}/"
    r = session.get(url, timeout=20)
    if r.status_code != 200: return {}
    soup = BeautifulSoup(r.text, "lxml")
    return {
        "Ticker": tk,
        "Dividend Yield (12m)": text_near_label(soup, ["Dividend","DY"]),
        "P/VP": text_near_label(soup, ["P/VP","P/VPA"]),
        "Cotistas": text_near_label(soup, ["Cotistas"]),
        "Liquidez Diária": text_near_label(soup, ["Liquidez","Volume"]),
    }

# =================== Regras ===================
def recomendacao(d):
    dy = clean_num_pt(d.get("Dividend Yield (12m)"))
    pvp = clean_num_pt(d.get("P/VP"))
    if dy is None or pvp is None: return "⚪ Sem dados"
    if dy > 10 and pvp < 1: return "🟢 Bom ponto"
    if dy > 8 and pvp <= 1.05: return "🟡 Razoável"
    if pvp > 1.1: return "🔴 Caro"
    return "⚪ Neutro"

# =================== Histórico ===================
def save_history(df_new):
    if os.path.exists(HIST_FILE):
        old = pd.read_csv(HIST_FILE)
        df_final = pd.concat([old, df_new], ignore_index=True).drop_duplicates("Ticker", keep="last")
    else:
        df_final = df_new
    df_final.to_csv(HIST_FILE, index=False, encoding="utf-8-sig")

# =================== UI ===================
st.title("📊 Analisador de FIIs")

if not os.path.exists(MAPA_FILE):
    st.error("❌ O arquivo mapa_fundos.csv não foi encontrado. Coloque-o na mesma pasta do app.py.")
else:
    mapa = pd.read_csv(MAPA_FILE, dtype=str).fillna("")
    tickers = sorted(mapa["Ticker"].unique())

    escolhidos = st.multiselect("Escolha FIIs para analisar", tickers, default=tickers[:2])

    if escolhidos:
        session = make_session()
        rows = []
        for tk in escolhidos:
            d = fetch_details(session, tk)
            if d:
                d["Recomendação"] = recomendacao(d)
                rows.append(d)
        if rows:
            dfres = pd.DataFrame(rows)
            st.dataframe(dfres, use_container_width=True)
            save_history(dfres[["Ticker","Dividend Yield (12m)","P/VP"]])

    st.subheader("📜 Histórico de buscas")
    if os.path.exists(HIST_FILE):
        dfh = pd.read_csv(HIST_FILE)
        st.dataframe(dfh.tail(50), use_container_width=True)
        if st.button("🧹 Limpar histórico"):
            os.remove(HIST_FILE)
            st.success("Histórico apagado. Recarregue a página.")

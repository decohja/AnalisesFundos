import streamlit as st
import pandas as pd
import requests, re, os
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
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
def only_digits(s):
    return re.sub(r"\D", "", s or "")

def extract_cnpj(text):
    m = re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", text)
    if m: return only_digits(m.group(0))
    m = re.search(r"\b\d{14}\b", text)
    if m: return m.group(0)
    return ""

def extract_name(soup):
    h1 = soup.find("h1")
    if h1: return h1.get_text(strip=True)
    t = soup.find("title")
    if t: return t.get_text(" ", strip=True).split("|")[0].strip()
    return ""

def text_near_label(soup, patterns):
    for pat in patterns:
        node = soup.find(string=re.compile(pat, re.I))
        if not node: continue
        chunk = node.parent.get_text(" ", strip=True)
        nums = re.findall(r"[-+]?\d[\d\.\,]*%?", chunk)
        if nums: return nums[-1]
    return ""

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

# =================== B3 tickers ===================
def list_all_fiis_from_b3(session):
    url = "https://arquivos.b3.com.br/api/download/requestname?fileName=InstrumentsConsolidatedFile&fileType=csv"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    lines = r.text.splitlines()
    tickers = []
    for line in lines:
        parts = line.split(";")
        if len(parts) > 4:
            code = parts[4].strip().upper()
            if code.endswith("11") and len(code) <= 7:  # padrão FII
                tickers.append(code)
    return sorted(set(tickers))

# =================== Scraping Investidor10 ===================
def fetch_cnpj_name(session, tk):
    url = f"https://investidor10.com.br/fiis/{tk.lower()}/"
    r = session.get(url, timeout=20)
    if r.status_code != 200:
        return {"Ticker": tk, "CNPJ": "", "Nome": ""}
    soup = BeautifulSoup(r.text, "lxml")
    full_text = soup.get_text(" ", strip=True)
    return {
        "Ticker": tk,
        "CNPJ": extract_cnpj(full_text),
        "Nome": extract_name(soup)
    }

def build_mapa(max_workers=16):
    session = make_session()
    tickers = list_all_fiis_from_b3(session)
    if not tickers:
        st.error("Não consegui obter tickers da B3.")
        return pd.DataFrame(columns=["Ticker","CNPJ","Nome"])
    st.info(f"Encontrados {len(tickers)} tickers da B3. Buscando dados no Investidor10...")
    results = []
    progress = st.progress(0)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_cnpj_name, session, tk): tk for tk in tickers}
        done = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            progress.progress(done/len(tickers))
    df = pd.DataFrame(results).drop_duplicates("Ticker").sort_values("Ticker")
    df.to_csv(MAPA_FILE, index=False, encoding="utf-8-sig")
    return df

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
tab_analisar, tab_mapa = st.tabs(["🔎 Analisar","🗺️ Mapa"])

with tab_mapa:
    if st.button("🚀 Gerar mapa completo (B3 + Investidor10)"):
        with st.spinner("Gerando mapa..."):
            dfmap = build_mapa()
        if not dfmap.empty:
            st.success(f"Mapa criado: {len(dfmap)} fundos")
            st.dataframe(dfmap.head(20))
            st.download_button("⬇️ Baixar mapa_fundos.csv", dfmap.to_csv(index=False).encode("utf-8-sig"),
                               file_name="mapa_fundos.csv")

with tab_analisar:
    if os.path.exists(MAPA_FILE):
        mapa = pd.read_csv(MAPA_FILE, dtype=str).fillna("")
        tickers = sorted(mapa["Ticker"].unique())
    else:
        mapa = pd.DataFrame(); tickers = []
    if not tickers:
        st.warning("Gere o mapa na aba Mapa.")
    else:
        escolhidos = st.multiselect("Escolha FIIs", tickers, default=tickers[:2])
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
                st.dataframe(dfres)
                save_history(dfres[["Ticker","Dividend Yield (12m)","P/VP"]])

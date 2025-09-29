import streamlit as st
import pandas as pd
import requests, re, time, os
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter, Retry

# =================== Config ===================
st.set_page_config(page_title="Analisador de FIIs", page_icon="📊", layout="wide")
HIST_FILE = "historico_buscas.csv"
MAPA_FILE = "mapa_fundos.csv"
INV10_LIST_URL = "https://investidor10.com.br/fiis/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    retries = Retry(total=5, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s

# =================== Util ===================
def only_digits(s):
    return re.sub(r"\D", "", s or "")

def extract_cnpj(text):
    # tenta CNPJ formatado
    m = re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", text)
    if m: return only_digits(m.group(0))
    # tenta padrões próximos de "CNPJ:"
    m = re.search(r"CNPJ[:\s]*([0-9.\-/]{14,18})", text, re.I)
    if m: return only_digits(m.group(1))
    # tenta 14 dígitos soltos
    m = re.search(r"\b\d{14}\b", text)
    if m: return m.group(0)
    return ""

def extract_name_from_title(soup):
    # tenta <h1>
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    # tenta <title>
    t = soup.find("title")
    if t:
        title = t.get_text(" ", strip=True)
        title = title.split("|")[0].strip()
        return title
    return ""

def text_near_label(soup, patterns):
    # Procura texto próximo aos rótulos e retorna o último número encontrado
    for pat in patterns:
        node = soup.find(string=re.compile(pat, re.I))
        if not node:
            continue
        # junta texto do pai + vizinho
        chunk = node.parent.get_text(" ", strip=True)
        nums = re.findall(r"[-+]?\d[\d\.\,]*%?", chunk)
        if nums:
            return nums[-1]
        sib = node.find_next()
        if sib:
            chunk2 = sib.get_text(" ", strip=True)
            nums2 = re.findall(r"[-+]?\d[\d\.\,]*%?", chunk2)
            if nums2:
                return nums2[0]
    return ""

def clean_num_pt(s):
    if not s: return None
    s = str(s).replace("\xa0"," ").replace("%","").strip()
    s = re.sub(r"[^\d,.\-]", "", s)
    # padrão pt-BR: 1.234,56
    if s.count(",") == 1 and s.count(".") >= 1:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

# =================== Scraping Investidor10 ===================
def list_all_tickers_from_investidor10(session):
    r = session.get(INV10_LIST_URL, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    tickers = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # padrões: /fiis/mxrf11/  ou /fiis/mxrf11
        m = re.match(r"^/fiis/([a-z0-9\-]+)/?$", href)
        if m:
            code = m.group(1).upper()
            if re.match(r"^[A-Z0-9]{4,6}11$", code):
                tickers.add(code)
    return sorted(tickers)

def fetch_cnpj_name_for_ticker(session, tk):
    url = f"https://investidor10.com.br/fiis/{tk.lower()}/"
    r = session.get(url, timeout=25)
    if r.status_code != 200:
        return {"Ticker": tk, "CNPJ": "", "Nome": ""}
    soup = BeautifulSoup(r.text, "lxml")
    full_text = soup.get_text(" ", strip=True)
    cnpj = extract_cnpj(full_text)
    nome = extract_name_from_title(soup)
    return {"Ticker": tk, "CNPJ": cnpj, "Nome": nome}

def build_mapa_from_investidor10(max_workers=16):
    session = make_session()
    tickers = list_all_tickers_from_investidor10(session)
    if not tickers:
        st.error("Não consegui listar os tickers no Investidor10.")
        return pd.DataFrame(columns=["Ticker","CNPJ","Nome"])

    st.write(f"🔎 Encontrados **{len(tickers)}** tickers no Investidor10.")
    progress = st.progress(0)
    results = []
    total = len(tickers)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_cnpj_name_for_ticker, session, tk): tk for tk in tickers}
        done = 0
        for fut in as_completed(futures):
            row = fut.result()
            results.append(row)
            done += 1
            progress.progress(min(done/total, 1.0))

    df = pd.DataFrame(results).drop_duplicates(subset=["Ticker"]).sort_values("Ticker").reset_index(drop=True)
    # sanity: limpa CNPJ com tamanho != 14
    df["CNPJ"] = df["CNPJ"].apply(lambda x: x if len(only_digits(x))==14 else "")
    # salva
    df.to_csv(MAPA_FILE, index=False, encoding="utf-8-sig")
    return df

def fetch_details_investidor10(session, tk):
    url = f"https://investidor10.com.br/fiis/{tk.lower()}/"
    r = session.get(url, timeout=25)
    if r.status_code != 200:
        return {}
    soup = BeautifulSoup(r.text, "lxml")

    data = {
        "Ticker": tk,
        "Dividend Yield (12m)": text_near_label(soup, ["Dividend\\s*Yield", r"\bDY\b"]),
        "P/VP": text_near_label(soup, [r"P\/?\s*VP", "P/VPA"]),
        "Patrimônio Líquido": text_near_label(soup, ["Patrim[oô]nio\\s*l[ií]quido", r"PL\\s*\\(R\\$"]),
        "Nº Cotistas": text_near_label(soup, ["Cotistas","N[oú]mero de cotistas"]),
        "Liquidez Diária": text_near_label(soup, ["Liquidez.*di[aá]ria","Volume m[eé]dio"]),
        "Taxa de administração": text_near_label(soup, ["Taxa de administra"]),
        "Taxa de performance": text_near_label(soup, ["Taxa de perform"]),
        "Alavancagem (%)": text_near_label(soup, ["Alavancagem"]),
        "Concentração maior ativo (%)": text_near_label(soup, ["Concentra"]),
    }
    # limpeza básica de faixas absurdas
    dy = clean_num_pt(data.get("Dividend Yield (12m)"))
    if dy is not None and not (0 <= dy <= 40): data["Dividend Yield (12m)"] = ""
    pvp = clean_num_pt(data.get("P/VP"))
    if pvp is not None and not (0.4 <= pvp <= 2.5): data["P/VP"] = ""
    return data

# =================== Recomendação ===================
def recomendacao(d):
    dy = clean_num_pt(d.get("Dividend Yield (12m)"))
    pvp = clean_num_pt(d.get("P/VP"))
    if dy is None or pvp is None:
        return "⚪ Sem dados suficientes"
    if dy > 10 and pvp < 1:
        return "🟢 Bom ponto de entrada"
    if dy > 8 and pvp <= 1.05:
        return "🟡 Razoável, atenção"
    if pvp > 1.10:
        return "🔴 Caro no momento"
    return "⚪ Neutro"

# =================== Histórico ===================
def save_history(df_new):
    if os.path.exists(HIST_FILE):
        old = pd.read_csv(HIST_FILE)
        df_final = pd.concat([old, df_new], ignore_index=True).drop_duplicates(subset=["Ticker"], keep="last")
    else:
        df_final = df_new
    df_final.to_csv(HIST_FILE, index=False, encoding="utf-8-sig")

# =================== UI ===================
tab_analisar, tab_mapa = st.tabs(["🔎 Analisar", "🗺️ Mapa (Ticker ↔ CNPJ)"])

with tab_mapa:
    st.subheader("Gerar / Atualizar mapa (Investidor10)")
    st.caption("Cria o arquivo mapa_fundos.csv com **TODOS** os FIIs listados. Usa scraping paralelo com retry.")
    colA, colB = st.columns([1,1])
    with colA:
        if st.button("🚀 Gerar/atualizar mapa agora"):
            with st.spinner("Coletando tickers e CNPJs no Investidor10..."):
                dfmap = build_mapa_from_investidor10()
            if not dfmap.empty:
                st.success(f"Mapa criado com {len(dfmap)} fundos.")
                st.dataframe(dfmap.head(20), use_container_width=True)
                st.download_button("⬇️ Baixar mapa_fundos.csv", data=dfmap.to_csv(index=False).encode("utf-8-sig"),
                                   file_name="mapa_fundos.csv", mime="text/csv")
    with colB:
        if os.path.exists(MAPA_FILE):
            dfmap_local = pd.read_csv(MAPA_FILE, dtype=str)
            st.success(f"Mapa existente: {len(dfmap_local)} fundos")
            st.dataframe(dfmap_local.head(20), use_container_width=True)
            st.download_button("⬇️ Baixar mapa_fundos.csv (atual)", data=dfmap_local.to_csv(index=False).encode("utf-8-sig"),
                               file_name="mapa_fundos.csv", mime="text/csv")
        else:
            st.info("Nenhum mapa_fundos.csv encontrado ainda. Clique no botão para gerar.")

with tab_analisar:
    st.subheader("Seleção de fundos")
    # Carrega mapa
    if os.path.exists(MAPA_FILE):
        mapa = pd.read_csv(MAPA_FILE, dtype=str).fillna("")
        tickers = sorted(mapa["Ticker"].unique().tolist())
    else:
        mapa = pd.DataFrame(columns=["Ticker","CNPJ","Nome"])
        tickers = []

    if not tickers:
        st.warning("Gere o mapa na aba 'Mapa' antes de analisar.")
    else:
        escolhidos = st.multiselect("Escolha 1+ fundos", options=tickers, default=["MXRF11","VGHF11"] if "MXRF11" in tickers and "VGHF11" in tickers else tickers[:2])

        if escolhidos:
            session = make_session()
            rows = []
            prog = st.progress(0)
            for i, tk in enumerate(escolhidos, start=1):
                det = fetch_details_investidor10(session, tk)
                if det:
                    det["Recomendação"] = recomendacao(det)
                    rows.append(det)
                prog.progress(i/len(escolhidos))

            if rows:
                dfres = pd.DataFrame(rows)
                st.subheader("Resultados")
                st.dataframe(dfres, use_container_width=True)

                # salvar histórico (por ticker)
                save_history(dfres[["Ticker","Dividend Yield (12m)","P/VP"]])

                # comparação (pivot)
                if len(rows) > 1:
                    st.subheader("Comparação (lado a lado)")
                    cols_show = ["Dividend Yield (12m)","P/VP","Patrimônio Líquido","Nº Cotistas","Liquidez Diária","Recomendação"]
                    comp = dfres.set_index("Ticker")[cols_show]
                    st.dataframe(comp, use_container_width=True)
        # histórico
        st.subheader("📜 Histórico de buscas")
        if os.path.exists(HIST_FILE):
            dfh = pd.read_csv(HIST_FILE)
            st.dataframe(dfh.tail(50), use_container_width=True)
            if st.button("🧹 Limpar histórico"):
                os.remove(HIST_FILE)
                st.success("Histórico apagado. Recarregue a página.")
        else:
            st.info("Nenhum histórico salvo ainda.")

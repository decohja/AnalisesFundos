import streamlit as st
import requests, re, math, json
from bs4 import BeautifulSoup
import pandas as pd
import os
from datetime import datetime

st.set_page_config(page_title="Analisador de FIIs", page_icon="📊", layout="wide")

# ========================= Utils =========================
def _clean_num(s):
    if s is None: return None
    s = str(s).replace("\xa0"," ").replace("%","").strip()
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.count(",") == 1 and s.count(".") >= 1:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    try:
        return float(s)
    except:
        return None

def _fmt(x, pct=False):
    if x in [None, ""]:
        return ""
    try:
        v = float(x)
        s = f"{v:,.2f}" if not pct else f"{v:,.2f}%"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(x)

def _ok(v):  # campo preenchido de forma útil
    return v not in [None, "", "N/A", "NA"]

def _merge(primary, secondary):
    out = dict(primary)
    for k,v in secondary.items():
        if not _ok(out.get(k)): out[k] = v
    return out

def _clip(value, lo, hi):
    try:
        v = float(value)
        return lo <= v <= hi
    except:
        return False

# =================== Scrapers (robustos) ===================
headers = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fundsexplorer(ticker:str)->dict:
    """
    Fonte principal. Ex.: https://www.fundsexplorer.com.br/funds/mxrf11
    Campos comuns acessíveis: P/VP, Dividend Yield, Liquidez, Nº cotistas, PL, Início, Taxas.
    """
    url = f"https://www.fundsexplorer.com.br/funds/{ticker.lower()}"
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code != 200: return {}

    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text(" ").strip()

    def find_after(regex, percent=False):
        m = re.search(regex, text, re.I)
        if not m: return None
        window = text[m.end(): m.end()+160]
        pat = r"[-+]?\d[\d\.\,]*\s?%" if percent else r"[-+]?\d[\d\.\,]*"
        n = re.search(pat, window)
        return n.group(0).strip() if n else None

    # Alguns valores vêm em blocos identificados
    def by_label(lbls):
        for lbl in lbls:
            el = soup.find(string=re.compile(lbl, re.I))
            if el:
                # tenta achar número próximo
                nums = re.findall(r'[-+]?\d[\d\.\,]*%?', el.parent.get_text(" "), re.I)
                if nums: return nums[-1]
                nxt = el.find_next()
                if nxt:
                    nums = re.findall(r'[-+]?\d[\d\.\,]*%?', nxt.get_text(" "), re.I)
                    if nums: return nums[0]
        return None

    data = {
        "FontePrimária": "FundsExplorer",
        "Gestora": by_label(["Gestor", "Administrador"]),  # nem sempre aparece
        "Ano de início": find_after(r"(Data|In[ií]cio)\s+do\s+fundo|IPO|In[ií]cio", percent=False),
        "Patrimônio líquido (R$ mi/bi)": by_label(["Patrim[oô]nio l[ií]quido", r"PL\s*\(R\$"]),
        "Nº de cotistas": by_label(["Cotistas", "Número de cotistas"]),
        "Liquidez diária (R$ mi)": by_label(["Liquidez.*di[aá]ria", "Volume m[eé]dio"]),
        "Taxa de administração": by_label(["Taxa de administra"]),
        "Taxa de performance": by_label(["Taxa de perform"]),
        "P/VP": by_label([r"P/?VP", "P/VPA"]),
        "Dividend Yield 12m (%)": by_label(["Dividend Yield", r"DY.*12"]),
        # Alguns campos abaixo nem sempre constam; ficam editáveis no formulário
        "Composição CRI (%)": None,
        "Composição cotas FII (%)": None,
        "Composição permutas (%)": None,
        "Composição caixa (%)": None,
        "Classificação de risco": None,
        "Concentração maior ativo (%)": None,
        "Alavancagem (%)": None,
        "Dividend Yield 5a (%)": None,
        "Rentab 2a (%)": None,
        "Rentab 5a (%)": None,
        "Rentab 10a (%)": None,
    }

    # Limpeza / sanity
    # DY plausível
    if not _clip(_clean_num(data.get("Dividend Yield 12m (%)")), 0, 40): data["Dividend Yield 12m (%)"] = None
    if not _clip(_clean_num(data.get("P/VP")), 0.4, 2.2): data["P/VP"] = None
    return data

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_statusinvest(ticker:str)->dict:
    """
    Fallback 1. HTML do StatusInvest traz strong[title=...] com várias métricas.
    """
    url = f"https://statusinvest.com.br/fundos-imobiliarios/{ticker.lower()}"
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code != 200: return {}
    soup = BeautifulSoup(r.text, "lxml")

    def pick(title):
        el = soup.find("strong", {"title": title})
        return el.get_text(strip=True) if el else None

    data = {
        "FonteSecundária": "StatusInvest",
        "Patrimônio líquido (R$ mi/bi)": pick("Patrimônio líquido"),
        "Nº de cotistas": pick("Número de cotistas"),
        "Liquidez diária (R$ mi)": pick("Média volume diário"),
        "P/VP": pick("P/VP"),
        "Dividend Yield 12m (%)": pick("Dividend Yield"),
    }
    # sanity
    if not _clip(_clean_num(data.get("Dividend Yield 12m (%)")), 0, 40): data["Dividend Yield 12m (%)"] = None
    if not _clip(_clean_num(data.get("P/VP")), 0.4, 2.2): data["P/VP"] = None
    return data

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_investidor10(ticker:str)->dict:
    """
    Fallback 2. Texto completo, regex flexível.
    """
    url = f"https://investidor10.com.br/fiis/{ticker.lower()}/"
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code != 200: return {}
    soup = BeautifulSoup(r.text, "lxml")
    text = soup.get_text(" ").strip()

    def find_after(regex, percent=False):
        m = re.search(regex, text, re.I)
        if not m: return None
        window = text[m.end(): m.end()+140]
        pat = r"[-+]?\d[\d\.\,]*\s?%" if percent else r"[-+]?\d[\d\.\,]*"
        n = re.search(pat, window)
        return n.group(0).strip() if n else None

    data = {
        "FonteTerciária": "Investidor10",
        "P/VP": find_after(r"P/?\s*VP|P/VPA"),
        "Dividend Yield 12m (%)": find_after(r"Dividend\s*Yield|DY", percent=True),
        "Patrimônio líquido (R$ mi/bi)": find_after(r"Patrim[oô]nio\s*l[ií]quido|PL\s*\(R\$"),
        "Nº de cotistas": find_after(r"(N[uú]mero\s*de\s*)?cotistas"),
        "Liquidez diária (R\$ mi)": find_after(r"Liquidez\s*di[aá]ria|Volume\s*m[eé]dio"),
    }
    if not _clip(_clean_num(data.get("Dividend Yield 12m (%)")), 0, 40): data["Dividend Yield 12m (%)"] = None
    if not _clip(_clean_num(data.get("P/VP")), 0.4, 2.2): data["P/VP"] = None
    return data

def fetch_all(ticker:str)->dict:
    base  = fetch_fundsexplorer(ticker)
    a = fetch_statusinvest(ticker)
    b = fetch_investidor10(ticker)
    # merge com ordem de confiança: FE > SI > I10
    data = _merge(base, a)
    data = _merge(data, b)
    data["Ticker"] = ticker.upper()
    return data

# =================== Persistência ===================
COLUMNS = [
    "Data","Ticker",
    "Gestora","Ano de início",
    "Patrimônio líquido (R$ mi/bi)","Nº de cotistas","Liquidez diária (R$ mi)",
    "Taxa de administração","Taxa de performance",
    "Composição CRI (%)","Composição cotas FII (%)","Composição permutas (%)","Composição caixa (%)",
    "Classificação de risco","Concentração maior ativo (%)","Alavancagem (%)",
    "Dividend Yield 12m (%)","Dividend Yield 5a (%)",
    "Rentab 2a (%)","Rentab 5a (%)","Rentab 10a (%)",
    "P/VP","FontePrimária","FonteSecundária","FonteTerciária","Notas"
]

def load_history()->pd.DataFrame:
    path = "data/analises.csv"
    if os.path.exists(path):
        df = pd.read_csv(path)
        for c in COLUMNS:
            if c not in df.columns: df[c] = ""
        return df[COLUMNS]
    return pd.DataFrame(columns=COLUMNS)

def save_history(df:pd.DataFrame):
    os.makedirs("data", exist_ok=True)
    df.to_csv("data/analises.csv", index=False)

# =================== Parecer automático ===================
def parecer(row:pd.Series)->dict:
    pvp = _clean_num(row.get("P/VP"))
    dy  = _clean_num(row.get("Dividend Yield 12m (%)"))
    risco = str(row.get("Classificação de risco") or "").lower()
    alav = _clean_num(row.get("Alavancagem (%)"))
    conc = _clean_num(row.get("Concentração maior ativo (%)"))

    msgs = []
    score = 0

    # P/VP
    if pvp is None:
        msgs.append("P/VP indisponível.")
    elif pvp < 0.95:
        score += 2; msgs.append("P/VP < 0,95 → **desconto interessante**.")
    elif 0.95 <= pvp <= 1.05:
        score += 1; msgs.append("P/VP ≈ 1 → **preço justo**.")
    else:
        score -= 1; msgs.append("P/VP > 1,05 → **prêmio**; pode estar **caro**.")

    # DY
    if dy is not None:
        if dy >= 12: score += 2; msgs.append(f"DY {dy:.1f}% a.a. → **renda alta**.")
        elif dy >= 9: score += 1; msgs.append(f"DY {dy:.1f}% a.a. → renda ok.")
        else: score -= 1; msgs.append(f"DY {dy:.1f}% a.a. → renda baixa.")

    # Risco & alavancagem
    if "high yield" in risco or "alto" in risco:
        score -= 1; msgs.append("Classificação **High Yield** → risco elevado.")
    elif "middle" in risco or "médio" in risco:
        msgs.append("Risco **médio** (middle).")
    elif "grade" in risco or "baixo" in risco:
        score += 1; msgs.append("Risco **baixo** (high grade).")

    if alav is not None:
        if alav > 20: score -= 1; msgs.append(f"Alavancagem {alav:.1f}% → cuidado.")
        elif alav > 0: msgs.append(f"Alavancagem {alav:.1f}% → ok.")

    if conc is not None and conc > 10:
        score -= 1; msgs.append(f"Concentração {conc:.1f}% no maior ativo → risco de crédito.")

    # Veredito
    if score >= 3: ver = "✅ Vale a pena (barato/atrativo)"
    elif score >= 1: ver = "🟨 Ok/Neutro (preço justo)"
    else: ver = "❌ Não vale / Cuidado (caro ou arriscado)"

    return {"score": int(score), "veredito": ver, "detalhes": " | ".join(msgs)}

# =================== UI ===================
st.title("📊 Analisador de FIIs")
st.caption("Fonte principal: FundsExplorer • Fallbacks: StatusInvest → Investidor10 • Edite antes de salvar • Compare múltiplos fundos.")

ticker = st.text_input("Ticker do FII (ex.: MXRF11)").strip().upper()

if st.button("Buscar & Preencher"):
    if not ticker:
        st.warning("Informe o ticker.")
    else:
        data = fetch_all(ticker)
        if not data:
            st.error("Não consegui coletar automaticamente. Preencha manualmente abaixo.")
            data = {"Ticker": ticker}
        st.session_state["draft"] = data

draft = st.session_state.get("draft", {"Ticker": ticker} if ticker else {})

with st.form("form_save"):
    st.subheader("📝 Revisar/editar dados antes de salvar")
    # Campos em blocos
    c1,c2,c3 = st.columns(3)
    with c1:
        Gestora = st.text_input("Gestora", draft.get("Gestora",""))
        Ano = st.text_input("Ano de início", draft.get("Ano de início",""))
        PL = st.text_input("Patrimônio líquido (R$ mi/bi)", draft.get("Patrimônio líquido (R$ mi/bi)",""))
        Cot = st.text_input("Nº de cotistas", draft.get("Nº de cotistas",""))
        Liq = st.text_input("Liquidez diária (R$ mi)", draft.get("Liquidez diária (R$ mi)",""))
    with c2:
        TxAdm = st.text_input("Taxa de administração", draft.get("Taxa de administração",""))
        TxPerf = st.text_input("Taxa de performance", draft.get("Taxa de performance",""))
        CompCRI = st.text_input("Composição CRI (%)", draft.get("Composição CRI (%)",""))
        CompFII = st.text_input("Composição cotas FII (%)", draft.get("Composição cotas FII (%)",""))
        CompPerm = st.text_input("Composição permutas (%)", draft.get("Composição permutas (%)",""))
    with c3:
        CompCx = st.text_input("Composição caixa (%)", draft.get("Composição caixa (%)",""))
        Risco = st.text_input("Classificação de risco", draft.get("Classificação de risco",""))
        Conc = st.text_input("Concentração maior ativo (%)", draft.get("Concentração maior ativo (%)",""))
        Alav = st.text_input("Alavancagem (%)", draft.get("Alavancagem (%)",""))
        PVP = st.text_input("P/VP", draft.get("P/VP",""))

    c4,c5,c6 = st.columns(3)
    with c4:
        DY12 = st.text_input("Dividend Yield 12m (%)", draft.get("Dividend Yield 12m (%)",""))
    with c5:
        DY5 = st.text_input("Dividend Yield 5a (%)", draft.get("Dividend Yield 5a (%)",""))
    with c6:
        Rent2 = st.text_input("Rentab 2a (%)", draft.get("Rentab 2a (%)",""))
    c7,c8 = st.columns(2)
    with c7:
        Rent5 = st.text_input("Rentab 5a (%)", draft.get("Rentab 5a (%)",""))
    with c8:
        Rent10 = st.text_input("Rentab 10a (%)", draft.get("Rentab 10a (%)",""))

    fontes = st.columns(3)
    with fontes[0]:
        F1 = st.text_input("FontePrimária", draft.get("FontePrimária",""))
    with fontes[1]:
        F2 = st.text_input("FonteSecundária", draft.get("FonteSecundária",""))
    with fontes[2]:
        F3 = st.text_input("FonteTerciária", draft.get("FonteTerciária",""))

    Notas = st.text_area("Notas", draft.get("Notas",""))

    # Parecer rápido antes de salvar
    row_tmp = pd.Series({
        "P/VP": PVP, "Dividend Yield 12m (%)": DY12,
        "Classificação de risco": Risco, "Alavancagem (%)": Alav,
        "Concentração maior ativo (%)": Conc
    })
    px = parecer(row_tmp)
    st.info(f"**Parecer automático (prévia):** {px['veredito']}  •  {px['detalhes']}  •  **score {px['score']}**")

    submitted = st.form_submit_button("Salvar análise")
    if submitted:
        df = load_history()
        row = {
            "Data": datetime.now().strftime("%Y-%m-%d"),
            "Ticker": draft.get("Ticker", ticker or ""),
            "Gestora": Gestora, "Ano de início": Ano,
            "Patrimônio líquido (R$ mi/bi)": PL, "Nº de cotistas": Cot, "Liquidez diária (R$ mi)": Liq,
            "Taxa de administração": TxAdm, "Taxa de performance": TxPerf,
            "Composição CRI (%)": CompCRI, "Composição cotas FII (%)": CompFII, "Composição permutas (%)": CompPerm, "Composição caixa (%)": CompCx,
            "Classificação de risco": Risco, "Concentração maior ativo (%)": Conc, "Alavancagem (%)": Alav,
            "Dividend Yield 12m (%)": DY12, "Dividend Yield 5a (%)": DY5,
            "Rentab 2a (%)": Rent2, "Rentab 5a (%)": Rent5, "Rentab 10a (%)": Rent10,
            "P/VP": PVP, "FontePrimária": F1, "FonteSecundária": F2, "FonteTerciária": F3,
            "Notas": Notas
        }
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        save_history(df)
        st.success("Análise salva no histórico!")

# Histórico
st.subheader("📂 Histórico de análises")
df = load_history()
st.dataframe(df, use_container_width=True)

# Parecer final para um fundo do histórico
st.subheader("🧭 Parecer final (um fundo)")
if len(df) >= 1:
    tsel = st.selectbox("Escolha o fundo para ver parecer final", sorted(df["Ticker"].unique()))
    row = df[df["Ticker"]==tsel].iloc[-1]
    px = parecer(row)
    st.markdown(f"### {tsel} — {px['veredito']}")
    st.write(px["detalhes"])
    st.caption(f"Score: {px['score']} (quanto maior, melhor)")

# Comparação real entre 2+ fundos
st.subheader("⚖️ Comparar múltiplos fundos")
if len(df) >= 2:
    choices = st.multiselect("Selecione 2 ou mais fundos", sorted(df["Ticker"].unique()))
    if len(choices) >= 2:
        comp = df[df["Ticker"].isin(choices)].groupby("Ticker").last().reset_index()
        show_cols = ["Ticker","P/VP","Dividend Yield 12m (%)","Dividend Yield 5a (%)",
                     "Patrimônio líquido (R$ mi/bi)","Nº de cotistas","Liquidez diária (R$ mi)",
                     "Classificação de risco","Alavancagem (%)","Concentração maior ativo (%)"]
        st.table(comp[show_cols])

        # Placar por critérios
        def score_row(r:pd.Series):
            s = 0
            # DY maior melhor
            dy = _clean_num(r.get("Dividend Yield 12m (%)"))
            if dy is not None: s += dy/5  # pondera
            # P/VP próximo de 1, e <=1 melhor
            p = _clean_num(r.get("P/VP"))
            if p is not None:
                if p <= 1: s += 1.5
                s -= abs(1-(p if p else 1))
            # Penalidades
            al = _clean_num(r.get("Alavancagem (%)"))
            if al and al>20: s -= 0.5
            cc = _clean_num(r.get("Concentração maior ativo (%)"))
            if cc and cc>10: s -= 0.5
            return s

        comp["ScoreComp"] = comp.apply(score_row, axis=1)
        comp_sorted = comp.sort_values("ScoreComp", ascending=False)
        st.markdown("**Ranking (maior score = melhor combinação de preço/qualidade):**")
        st.table(comp_sorted[["Ticker","ScoreComp","P/VP","Dividend Yield 12m (%)","Classificação de risco"]])

# Exportar / importar
cexp, cimp = st.columns(2)
with cexp:
    st.download_button("⬇️ Baixar histórico (CSV)", data=df.to_csv(index=False),
                       file_name="analises.csv", mime="text/csv")
with cimp:
    up = st.file_uploader("Subir CSV para mesclar", type=["csv"])
    if up is not None:
        new = pd.read_csv(up)
        df2 = pd.concat([df, new], ignore_index=True).drop_duplicates(subset=["Data","Ticker"], keep="last")
        save_history(df2)
        st.success("Histórico mesclado. Recarregue a página.")

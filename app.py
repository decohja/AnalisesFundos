import streamlit as st
import requests, re, os
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Analisador de FIIs", page_icon="📊", layout="wide")

# ========== Funções utilitárias ==========
def clean_num(s):
    if not s: return None
    s = str(s).replace(".", "").replace(",", ".").replace("%","").strip()
    try:
        return float(s)
    except:
        return None

def fetch_investidor10(ticker: str) -> dict:
    url = f"https://investidor10.com.br/fiis/{ticker.lower()}/"
    r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"})
    if r.status_code != 200:
        return {}

    soup = BeautifulSoup(r.text, "html.parser")

    def find_val(label):
        el = soup.find(string=re.compile(label, re.I))
        if not el: return None
        nums = re.findall(r"[\d\.,]+%?", el.parent.get_text(" "))
        if nums: return nums[-1]
        return None

    data = {
        "Gestora": find_val("Gestor|Administra"),
        "Ano de início": find_val("Início|Data"),
        "Patrimônio líquido (R$ mi/bi)": find_val("Patrimônio Líquido"),
        "Nº de cotistas": find_val("Cotistas"),
        "Liquidez diária (R$ mi)": find_val("Liquidez|Volume"),
        "Taxa de administração": find_val("Taxa de Administração"),
        "Taxa de performance": find_val("Taxa de Performance"),
        "Composição CRI (%)": find_val("CRI"),
        "Composição cotas FII (%)": find_val("FII"),
        "Composição permutas (%)": find_val("Permuta"),
        "Composição caixa (%)": find_val("Caixa"),
        "Classificação de risco": find_val("Risco|High|Middle|Grade"),
        "Concentração maior ativo (%)": find_val("Concentração"),
        "Alavancagem (%)": find_val("Alavancagem"),
        "Dividend Yield 12m (%)": find_val("Dividend Yield|DY"),
        "Dividend Yield 5a (%)": find_val("5 anos"),
        "Rentab 2a (%)": find_val("2 anos"),
        "Rentab 5a (%)": find_val("5 anos"),
        "Rentab 10a (%)": find_val("10 anos"),
        "P/VP": find_val("P/VP|P/VPA"),
        "Fonte": "Investidor10"
    }
    return data

# ========== Histórico ==========
COLUMNS = [
    "Data","Ticker","Gestora","Ano de início","Patrimônio líquido (R$ mi/bi)","Nº de cotistas","Liquidez diária (R$ mi)",
    "Taxa de administração","Taxa de performance","Composição CRI (%)","Composição cotas FII (%)","Composição permutas (%)",
    "Composição caixa (%)","Classificação de risco","Concentração maior ativo (%)","Alavancagem (%)",
    "Dividend Yield 12m (%)","Dividend Yield 5a (%)","Rentab 2a (%)","Rentab 5a (%)","Rentab 10a (%)","P/VP","Fonte","Notas"
]

def load_history():
    if os.path.exists("analises.csv"):
        return pd.read_csv("analises.csv")
    return pd.DataFrame(columns=COLUMNS)

def save_history(df):
    df.to_csv("analises.csv", index=False)

# ========== Parecer automático ==========
def parecer(row):
    pvp = clean_num(row.get("P/VP"))
    dy = clean_num(row.get("Dividend Yield 12m (%)"))
    risco = str(row.get("Classificação de risco") or "").lower()
    score, msgs = 0, []

    if pvp:
        if pvp < 0.95: score+=2; msgs.append("P/VP < 0,95 → Barato")
        elif pvp <=1.05: score+=1; msgs.append("P/VP ≈ 1 → Justo")
        else: score-=1; msgs.append("P/VP > 1,05 → Caro")
    if dy:
        if dy>=12: score+=2; msgs.append("DY alto")
        elif dy>=9: score+=1; msgs.append("DY ok")
        else: score-=1; msgs.append("DY baixo")
    if "high" in risco: score-=1; msgs.append("Risco alto")
    if "grade" in risco: score+=1; msgs.append("Risco baixo")

    if score>=3: ver="✅ Vale a pena"
    elif score>=1: ver="🟨 Neutro"
    else: ver="❌ Não vale"
    return ver," | ".join(msgs)

# ========== Interface ==========
st.title("📊 Analisador de FIIs (Investidor10)")

ticker = st.text_input("Ticker do FII (ex: MXRF11)").upper()

if st.button("Buscar"):
    if ticker:
        st.session_state["dados"] = fetch_investidor10(ticker)

dados = st.session_state.get("dados", {})

with st.form("form"):
    st.subheader("📝 Revisar/editar dados antes de salvar")
    edits = {}
    for col in COLUMNS[2:-2]:  # pula Data/Ticker/Notas
        edits[col] = st.text_input(col, dados.get(col,""))
    notas = st.text_area("Notas", dados.get("Notas",""))

    ver, msg = parecer(edits)
    st.info(f"Parecer: {ver} • {msg}")

    if st.form_submit_button("Salvar"):
        df = load_history()
        row = {**edits}
        row["Data"]=datetime.now().strftime("%Y-%m-%d")
        row["Ticker"]=ticker
        row["Notas"]=notas
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        save_history(df)
        st.success("Salvo!")

# Histórico
df = load_history()
st.subheader("📂 Histórico")
st.dataframe(df)

# Comparação
st.subheader("⚖️ Comparação entre fundos")
choices = st.multiselect("Selecione fundos", df["Ticker"].unique())
if len(choices)>=2:
    comp = df[df["Ticker"].isin(choices)]
    st.dataframe(comp)

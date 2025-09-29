import streamlit as st
import requests
import os

BRAPI_TOKEN = st.secrets.get("BRAPI_TOKEN", os.environ.get("BRAPI_TOKEN", ""))

st.write("🔑 Token carregado?", bool(BRAPI_TOKEN))

ticker = "MXRF11"

url = f"https://brapi.dev/api/quote/{ticker}.SA?modules=defaultKeyStatistics,dividends"
headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {BRAPI_TOKEN}"
}

r = requests.get(url, headers=headers)

st.write("Status:", r.status_code)
st.write("Resposta bruta:", r.text[:500])  # mostra só o começo do JSON

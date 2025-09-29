def buscar_fii(ticker):
    try:
        # adiciona .SA no final para FIIs
        url = f"https://brapi.dev/api/quote/{ticker}.SA?modules=defaultKeyStatistics,dividends"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {BRAPI_TOKEN}"
        }
        r = requests.get(url, headers=headers)

        if r.status_code != 200:
            return {"Ticker": ticker, "Erro": f"{r.status_code} {r.reason}"}

        data = r.json().get("results", [])[0]

        return {
            "Ticker": ticker.upper(),
            "Preço Atual (R$)": data.get("regularMarketPrice"),
            "P/VP": data.get("defaultKeyStatistics", {}).get("priceToBook", None),
            "Dividend Yield (12m %)": data.get("dividends", {}).get("yield12m", None),
            "Liquidez Diária": data.get("regularMarketVolume"),
        }
    except Exception as e:
        return {"Ticker": ticker, "Erro": str(e)}

import asyncio
import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from bs4 import BeautifulSoup
import pandas as pd
import re
import io

app = FastAPI()

YEARS = list(range(2008, 2026))

class Query(BaseModel):
    last: str
    initial: str

def name_match(last, initial, name):
    return re.search(rf"{initial}.*{last}|{last}.*{initial}", name, re.I)

def extract_laps(html, last, initial, event):
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    results = []

    for table in tables:
        for row in table.find_all("tr"):
            cols = [c.get_text(strip=True) for c in row.find_all("td")]

            if len(cols) < 3:
                continue

            driver = cols[1]

            if not name_match(last, initial, driver):
                continue

            for col in cols:
                if re.match(r"\d+:\d+\.\d+", col):
                    results.append({
                        "Driver": driver,
                        "Event": event,
                        "LapTime": col
                    })

    return results

async def fetch(client, url):
    try:
        r = await client.get(url, timeout=10)
        return r.text
    except:
        return None

async def scrape_event(client, url, last, initial):
    html = await fetch(client, url)
    if not html:
        return []
    return extract_laps(html, last, initial, url)

async def scrape_year(client, year, last, initial):
    base = f"http://racing.natsoft.com.au/results/{year}/"

    html = await fetch(client, base)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    links = [
        base + a.get("href")
        for a in soup.find_all("a")
        if a.get("href") and "event" in a.get("href")
    ]

    tasks = [scrape_event(client, url, last, initial) for url in links]
    results = await asyncio.gather(*tasks)

    flat = []
    for r in results:
        flat.extend(r)

    return flat

@app.get("/")
def home():
    return FileResponse("index.html")

@app.post("/search")
async def search(q: Query):
    async with httpx.AsyncClient() as client:
        tasks = [scrape_year(client, y, q.last, q.initial) for y in YEARS]
        results = await asyncio.gather(*tasks)

    all_data = []
    for r in results:
        all_data.extend(r)

    df = pd.DataFrame(all_data)

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=laps.xlsx"}
    )

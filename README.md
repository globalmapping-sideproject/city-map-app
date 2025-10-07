# Community City Map (Streamlit + Folium)


Free, deployable app where visitors can add themselves to a world map by picking a city
(search box or map click). Stores to CSV by default; optional Supabase backend.


## ✨ Features
- Interactive world map with marker clustering (Folium)
- City search via OpenStreetMap Nominatim (free tier)
- Map click → reverse geocode
- Auto-refresh (toggle) to see new pins live
- Duplicate-prevention (same user+city+country within 24h)
- Stats: counts by continent and country
- CSV download of all entries
- One‑click deploy to Streamlit Community Cloud (free for public repos)


## 🚀 Quickstart (local)
```bash
# 1) Clone
git clone https://github.com/<you>/city-map-app.git
cd city-map-app


# 2) Python env
python -m venv .venv && source .venv/bin/activate # Windows: .venv\Scripts\activate
pip install -r requirements.txt


# 3) (optional) create secrets
mkdir -p .streamlit
printf "GEOPY_USER_AGENT='city-map-app/1.0 (contact: youremail@example.com)'\n" > .streamlit/secrets.toml


# 4) Run
streamlit run app.py

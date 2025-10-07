import os
import time
import uuid
from datetime import datetime
import pandas as pd
import streamlit as st
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.location import Location
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import country_converter as coco

st.set_page_config(page_title="Community City Map", layout="wide")

# ---------- config ----------
APP_TITLE = "Community City Map"
CSV_PATH = os.path.join("data", "entries.csv")

# ---------- setup ----------
os.makedirs("data", exist_ok=True)
if not os.path.exists(CSV_PATH):
    pd.DataFrame(columns=[
        "id","username","city","country","lat","lon",
        "continent","un_region","created_at"
    ]).to_csv(CSV_PATH, index=False)

# ---------- helpers ----------
geolocator = Nominatim(user_agent="city-map-app/1.0 (contact: youremail@example.com)")
geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1)
cc = coco.CountryConverter()

def load_entries():
    try:
        df = pd.read_csv(CSV_PATH)
        for col in ["lat","lon"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame(columns=[
            "id","username","city","country","lat","lon",
            "continent","un_region","created_at"
        ])

def save_entry(row):
    df = load_entries()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)

def country_to_region(country):
    try:
        return cc.convert(country, to="continent"), cc.convert(country, to="UNregion")
    except Exception:
        return "", ""

# ---------- UI ----------
st.title(APP_TITLE)
st.write("### 🌍 Add your city and see where others are from!")

tab1, tab2 = st.tabs(["📍 Add City", "🗺️ Map"])

with tab1:
    name = st.text_input("Your name (optional)", "")
    city = st.text_input("Enter a city (e.g. Paris, Tokyo)", "")
    if st.button("Add City"):
        if not city:
            st.warning("Please type a city name.")
        else:
            loc = geocode(city)
            if loc:
                country = loc.raw.get("address", {}).get("country", "")
                continent, region = country_to_region(country)
                row = dict(
                    id=str(uuid.uuid4()),
                    username=name or "Anonymous",
                    city=city,
                    country=country,
                    lat=loc.latitude,
                    lon=loc.longitude,
                    continent=continent,
                    un_region=region,
                    created_at=datetime.utcnow().isoformat(),
                )
                save_entry(row)
                st.success(f"✅ Added {city}, {country}")
            else:
                st.error("City not found!")

with tab2:
    df = load_entries()
    if df.empty:
        st.info("No entries yet.")
    else:
        m = folium.Map(location=[20, 0], zoom_start=2, tiles="CartoDB positron")
        cluster = MarkerCluster().add_to(m)
        for _, r in df.iterrows():
            popup = f"{r['username']} — {r['city']}, {r['country']}"
            folium.Marker([r["lat"], r["lon"]], popup=popup).add_to(cluster)
        st_folium(m, height=600, width=900)
        st.download_button("⬇️ Download CSV", df.to_csv(index=False).encode("utf-8"),
                           "entries.csv", "text/csv")

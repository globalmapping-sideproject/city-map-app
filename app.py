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
UA = st.secrets.get("GEOPY_USER_AGENT", "city-map-app/1.0 (contact: globalmapping958@gmail.com)")
geolocator = Nominatim(user_agent=UA, timeout=10)
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
    st.subheader("Add yourself to the map")

    # hold results across clicks
    if "candidates_df" not in st.session_state:
        st.session_state["candidates_df"] = None

    name = st.text_input("Your name (optional)", "")
    query = st.text_input("Enter a city (e.g., Paris, Tokyo)", "")

    colA, colB = st.columns([1, 1])
    with colA:
        search = st.button("🔎 Search city")
    with colB:
        clear = st.button("Clear")

    if clear:
        st.session_state["candidates_df"] = None
        st.experimental_rerun()

    # run search
    if search and query.strip():
        try:
            candidates = geocode(
                query.strip(),
                exactly_one=False,
                addressdetails=True,
                limit=8,
            )
            time.sleep(1)  # be polite to OSM
            results = []
            if candidates:
                for loc in candidates:
                    addr = (loc.raw.get("address", {}) or {})
                    results.append({
                        "display_name": loc.address,
                        "lat": float(loc.latitude),
                        "lon": float(loc.longitude),
                        "country": addr.get("country", ""),
                    })
            st.session_state["candidates_df"] = pd.DataFrame(results) if results else None
        except Exception as e:
            st.session_state["candidates_df"] = None
            st.warning("Search failed or rate-limited. Try again in a moment.")

    # selection UI
    df = st.session_state["candidates_df"]
    lat = lon = None
    country = ""
    picked_city_text = ""

    if df is not None and not df.empty:
        choice = st.selectbox("Select a matching location:", df["display_name"])
        sel = df.loc[df["display_name"] == choice].iloc[0]
        lat, lon = sel["lat"], sel["lon"]
        country = sel["country"]
        picked_city_text = choice
        st.success(f"✅ Selected: {choice}")
    elif search:
        st.error("No matches. Try a broader or different spelling (e.g., 'New York, USA').")

    # store selection
    if lat is not None and lon is not None:
        if st.button("➕ Add this location"):
            continent, region = country_to_region(country)
            row = dict(
                id=str(uuid.uuid4()),
                username=name or "Anonymous",
                city=picked_city_text or query.strip(),
                country=country,
                lat=lat,
                lon=lon,
                continent=continent,
                un_region=region,
                created_at=datetime.utcnow().isoformat(),
            )
            save_entry(row)
            st.session_state["candidates_df"] = None
            st.success("Added! Go to the Map tab to see your pin.")


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

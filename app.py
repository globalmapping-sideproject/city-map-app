import os
import time
import uuid
from datetime import datetime
import requests
import pandas as pd
import streamlit as st

# Maps / geocoding
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.location import Location

st.set_page_config(page_title="Community City Map", layout="wide")

# ---------------- Config & paths ----------------
APP_TITLE = "Community City Map"
CSV_PATH = os.path.join("data", "entries.csv")

# Ensure data folder exists
os.makedirs("data", exist_ok=True)
if not os.path.exists(CSV_PATH):
    pd.DataFrame(
        columns=["id","username","city","country","lat","lon","continent","un_region","created_at"]
    ).to_csv(CSV_PATH, index=False)

# ---------------- Secrets ----------------
UA = st.secrets.get("GEOPY_USER_AGENT", "city-map-app/1.0 (contact: your@email.com)")
GEOAPIFY_KEY = st.secrets.get("GEOAPIFY_API_KEY", None)

# ---------------- Geocoders ----------------
# Nominatim (OSM) — polite configuration
_geolocator = Nominatim(user_agent=UA, timeout=10)
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1)
_reverse = RateLimiter(_geolocator.reverse, min_delay_seconds=1)

# ---------------- Storage helpers ----------------
def load_entries() -> pd.DataFrame:
    try:
        df = pd.read_csv(CSV_PATH)
        for col in ["lat", "lon"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for c in ["username","city","country"]:
            if c in df:
                df[c] = df[c].fillna("")
        return df
    except Exception:
        return pd.DataFrame(columns=["id","username","city","country","lat","lon","continent","un_region","created_at"])

def save_entry(row: dict) -> None:
    df = load_entries()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)

# ---------------- Geocoding helpers ----------------
def search_geoapify_autocomplete(text: str, limit: int = 10) -> pd.DataFrame:
    """Type-ahead autocomplete (cities) via Geoapify. Returns display_name, lat, lon, country."""
    if not GEOAPIFY_KEY or not text.strip():
        return pd.DataFrame(columns=["display_name","lat","lon","country"])
    url = "https://api.geoapify.com/v1/geocode/autocomplete"
    params = {
        "text": text.strip(),
        "type": "city",
        "format": "json",
        "limit": limit,
        "apiKey": GEOAPIFY_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json().get("results", [])
        out = []
        for it in data:
            name = it.get("city") or it.get("name") or it.get("formatted") or ""
            country = it.get("country", "")
            lat = it.get("lat")
            lon = it.get("lon")
            display = it.get("formatted") or f"{name}, {country}"
            if lat is not None and lon is not None:
                out.append({"display_name": display, "lat": float(lat), "lon": float(lon), "country": country})
        return pd.DataFrame(out)
    except Exception:
        # silent fail → UI will show a message; fallback exists
        return pd.DataFrame(columns=["display_name","lat","lon","country"])

def search_nominatim_candidates(query: str, limit: int = 10) -> pd.DataFrame:
    """Free OSM search (manual trigger). Returns display_name, lat, lon, country."""
    if not query.strip():
        return pd.DataFrame(columns=["display_name","lat","lon","country"])
    # Retry a couple of times because free OSM can time out
    for _ in range(2):
        try:
            locs = _geolocator.geocode(query.strip(), exactly_one=False, addressdetails=True, limit=limit)
            time.sleep(1)  # be polite
            if not locs:
                return pd.DataFrame(columns=["display_name","lat","lon","country"])
            rows = []
            for loc in locs:
                if isinstance(loc, Location):
                    addr = loc.raw.get("address", {}) or {}
                    rows.append({
                        "display_name": loc.address,
                        "lat": float(loc.latitude),
                        "lon": float(loc.longitude),
                        "country": addr.get("country", ""),
                    })
            return pd.DataFrame(rows)
        except Exception:
            time.sleep(1)
    return pd.DataFrame(columns=["display_name","lat","lon","country"])

# Simple placeholder; you can wire country->continent mapping later
def country_to_region(country: str):
    return "", ""

# ---------------- UI ----------------
st.title(APP_TITLE)
st.write("### 🌍 Add your city and see where others are from!")

if "candidates_df" not in st.session_state:
    st.session_state["candidates_df"] = None

tab1, tab2 = st.tabs(["📍 Add City", "🗺️ Map"])

with tab1:
    st.subheader("Add yourself to the map")

    # Name is REQUIRED (not optional)
    name = st.text_input("Your name (required)", "")
    if not name.strip():
        st.info("Please enter your name.")

    # --- Type-ahead city picker (Geoapify if key present)
    if GEOAPIFY_KEY:
        st.caption("Type to search for cities (powered by Geoapify Autocomplete).")
        typed = st.text_input("Start typing a city name", "", placeholder="e.g., New York, Tokyo, Belgrade")
        df = pd.DataFrame()
        if len(typed.strip()) >= 2:
            df = search_geoapify_autocomplete(typed, limit=12)

        selected = None
        if not df.empty:
            choice = st.selectbox(
                "Select a city",
                options=df["display_name"],
                index=None,
                placeholder="Pick from results",
            )
            if choice:
                sel = df.loc[df["display_name"] == choice].iloc[0]
                selected = {
                    "city": choice,
                    "country": sel["country"],
                    "lat": float(sel["lat"]),
                    "lon": float(sel["lon"]),
                }
        else:
            if len(typed.strip()) >= 2:
                st.warning("No matches yet. Try a different spelling (e.g., 'New York, USA').")

        # Submit
        disabled = not (name.strip() and selected)
        if st.button("➕ Add this location", disabled=disabled):
            continent, region = country_to_region(selected["country"])
            row = dict(
                id=str(uuid.uuid4()),
                username=name.strip(),
                city=selected["city"],
                country=selected["country"],
                lat=selected["lat"],
                lon=selected["lon"],
                continent=continent,
                un_region=region,
                created_at=datetime.utcnow().isoformat(),
            )
            save_entry(row)
            st.success("Added! Go to the Map tab to see your pin.")

        # Optional: small preview map of your pick
        if selected:
            mprev = folium.Map(location=[selected["lat"], selected["lon"]], zoom_start=6, tiles="CartoDB positron")
            folium.Marker([selected["lat"], selected["lon"]], popup=selected["city"]).add_to(mprev)
            st_folium(mprev, height=300, width=600)

    # --- Fallback: Nominatim search + dropdown (no key needed)
    else:
        st.caption("Free OSM search (click Search to query). Add a Geoapify key for live type-ahead.")
        query = st.text_input("Enter a city", "", placeholder="e.g., New York, USA")
        colA, colB = st.columns([1,1])
        with colA:
            do_search = st.button("🔎 Search")
        with colB:
            if st.button("Clear"):
                st.session_state["candidates_df"] = None
                st.experimental_rerun()

        selected = None
        if do_search and query.strip():
            st.session_state["candidates_df"] = search_nominatim_candidates(query, limit=12)

        df = st.session_state["candidates_df"]
        if df is not None:
            if df.empty:
                st.error("No matches. Try a broader spelling (e.g., 'New York, USA').")
            else:
                choice = st.selectbox(
                    "Select a matching location",
                    options=df["display_name"],
                    index=None,
                    placeholder="Pick from results",
                )
                if choice:
                    sel = df.loc[df["display_name"] == choice].iloc[0]
                    selected = {
                        "city": choice,
                        "country": sel["country"],
                        "lat": float(sel["lat"]),
                        "lon": float(sel["lon"]),
                    }

        disabled = not (name.strip() and selected)
        if st.button("➕ Add this location", disabled=disabled):
            continent, region = country_to_region(selected["country"])
            row = dict(
                id=str(uuid.uuid4()),
                username=name.strip(),
                city=selected["city"],
                country=selected["country"],
                lat=selected["lat"],
                lon=selected["lon"],
                continent=continent,
                un_region=region,
                created_at=datetime.utcnow().isoformat(),
            )
            save_entry(row)
            st.success("Added! Go to the Map tab to see your pin.")

with tab2:
    st.subheader("Community Map")
    df = load_entries()
    if df.empty:
        st.info("No entries yet. Add yours in the previous tab!")
    else:
        m = folium.Map(location=[20, 0], zoom_start=2, tiles="CartoDB positron")
        cluster = MarkerCluster().add_to(m)
        for _, r in df.iterrows():
            popup = f"<b>{r['username']}</b><br>{r['city']}<br>{r['country']}"
            folium.Marker([r["lat"], r["lon"]], popup=popup).add_to(cluster)
        st_folium(m, height=600, width=900)
        st.download_button(
            "⬇️ Download entries as CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="entries.csv",
            mime="text/csv"
        )

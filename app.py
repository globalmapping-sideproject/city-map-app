import os
import time
import uuid
from datetime import datetime
import requests
import pandas as pd
import streamlit as st

import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.location import Location

# -------------------- Page config --------------------
st.set_page_config(page_title="RCWG Map", layout="wide")

APP_TITLE = "RCWG Map"
DATA_DIR = "data"
CSV_PATH = os.path.join(DATA_DIR, "entries.csv")

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(CSV_PATH):
    pd.DataFrame(
        columns=["id", "username", "city", "country", "lat", "lon",
                 "continent", "un_region", "created_at"]
    ).to_csv(CSV_PATH, index=False)

# -------------------- Secrets --------------------
UA = st.secrets.get("GEOPY_USER_AGENT", "rcwg-map/1.0 (contact: your@email)")
GEOAPIFY_KEY = st.secrets.get("GEOAPIFY_API_KEY", None)

# -------------------- Geocoders --------------------
_geolocator = Nominatim(user_agent=UA, timeout=10)
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1)
_reverse = RateLimiter(_geolocator.reverse, min_delay_seconds=1)

# -------------------- Data helpers --------------------
@st.cache_data(ttl=30)
def load_entries() -> pd.DataFrame:
    try:
        df = pd.read_csv(CSV_PATH)
        for col in ["lat", "lon"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        for c in ["username", "city", "country"]:
            if c in df:
                df[c] = df[c].fillna("")
        return df
    except Exception:
        return pd.DataFrame(columns=["id","username","city","country","lat","lon","continent","un_region","created_at"])

def refresh_entries_cache():
    load_entries.clear()

def save_entry(row: dict) -> None:
    df = load_entries()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(CSV_PATH, index=False)
    refresh_entries_cache()

def country_to_region(_country: str):
    # (lightweight placeholder, can wire actual mapping later)
    return "", ""

# -------------------- Geocoding helpers --------------------
def geoapify_autocomplete(text: str, limit: int = 10) -> pd.DataFrame:
    if not GEOAPIFY_KEY or not text.strip():
        return pd.DataFrame(columns=["display_name", "lat", "lon", "country"])
    url = "https://api.geoapify.com/v1/geocode/autocomplete"
    params = {"text": text.strip(), "type": "city", "format": "json", "limit": limit, "apiKey": GEOAPIFY_KEY}
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        results = []
        for it in r.json().get("results", []):
            name = it.get("formatted") or it.get("city") or it.get("name") or ""
            country = it.get("country", "")
            lat, lon = it.get("lat"), it.get("lon")
            if lat is not None and lon is not None:
                results.append({"display_name": name, "lat": float(lat), "lon": float(lon), "country": country})
        return pd.DataFrame(results)
    except Exception:
        return pd.DataFrame(columns=["display_name", "lat", "lon", "country"])

def nominatim_candidates(query: str, limit: int = 10) -> pd.DataFrame:
    if not query.strip():
        return pd.DataFrame(columns=["display_name", "lat", "lon", "country"])
    for _ in range(2):
        try:
            locs = _geolocator.geocode(query.strip(), exactly_one=False, addressdetails=True, limit=limit)
            time.sleep(1)
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

# -------------------- UI --------------------
st.title(APP_TITLE)
st.write("### 🌍 Add your city and see where others are from!")

# Session state
if "last_query" not in st.session_state:
    st.session_state.last_query = ""
if "options_df" not in st.session_state:
    st.session_state.options_df = pd.DataFrame()
if "selected_loc" not in st.session_state:
    st.session_state.selected_loc = None  # store last selection for preview

tab_add, tab_map = st.tabs(["📍 Add City", "🗺️ Map"])

with tab_add:
    st.subheader("Add yourself to the map")

    # Username (implied required)
    username = st.text_input("Username", "")

    # ---------- Single type-ahead control ----------
    caption_text = "Type to search for cities (powered by Geoapify Autocomplete)." if GEOAPIFY_KEY \
        else "Free OSM search: type a city then pick from dropdown."
    st.caption(caption_text)

    # One text input (label hidden) + one dropdown (label hidden)
    typed = st.text_input(" ", "", placeholder="e.g., New York City, Tokyo, Belgrade", label_visibility="collapsed")

    # Fetch candidates
    new_df = pd.DataFrame()
    if len(typed.strip()) >= 2:
        if GEOAPIFY_KEY:
            new_df = geoapify_autocomplete(typed, limit=12)
        else:
            new_df = nominatim_candidates(typed, limit=12)

    # Update options only when query changes
    if typed != st.session_state.last_query:
        st.session_state.options_df = new_df
        st.session_state.last_query = typed

    df_opts = st.session_state.options_df
    selected = None
    if not df_opts.empty:
        choice = st.selectbox(" ", df_opts["display_name"], index=None,
                              placeholder="Select a city from results", label_visibility="collapsed")
        if choice:
            sel = df_opts.loc[df_opts["display_name"] == choice].iloc[0]
            selected = {
                "city": choice,
                "country": sel["country"],
                "lat": float(sel["lat"]),
                "lon": float(sel["lon"]),
            }
    else:
        if len(typed.strip()) >= 2:
            st.error("No matches. Try another spelling. Examples: **Recoil Ridge**, **Port City**, **Marin**.")

    # Add button (enabled when username + selection present)
    can_add = bool(username.strip()) and (selected is not None)
    if st.button("➕ Add this location", disabled=not can_add):
        continent, region = country_to_region(selected["country"])
        row = dict(
            id=str(uuid.uuid4()),
            username=username.strip(),
            city=selected["city"],
            country=selected["country"],
            lat=selected["lat"],
            lon=selected["lon"],
            continent=continent,
            un_region=region,
            created_at=datetime.utcnow().isoformat(),
        )
        save_entry(row)
        st.session_state.selected_loc = selected  # show preview below
        st.success("Added!")

    # ---- Preview map of YOUR selected location only ----
    st.write("---")
    st.write("#### 📍 Your selected location (preview)")
    preview = st.session_state.selected_loc
    if preview:
        mprev = folium.Map(location=[preview["lat"], preview["lon"]], zoom_start=6, tiles="CartoDB positron")
        folium.Marker([preview["lat"], preview["lon"]], popup=preview["city"]).add_to(mprev)
        st_folium(mprev, height=400, width=900, key="preview_map")
    else:
        st.info("Pick a city above to see a preview map here.")

with tab_map:
    st.subheader("Community Map")
    entries = load_entries()
    if entries.empty:
        st.info("No entries yet.")
    else:
        m2 = folium.Map(location=[20, 0], zoom_start=2, tiles="CartoDB positron")
        cluster2 = MarkerCluster().add_to(m2)
        for _, r in entries.iterrows():
            popup = f"<b>{r['username']}</b><br>{r['city']}<br>{r['country']}"
            folium.Marker([r["lat"], r["lon"]], popup=popup).add_to(cluster2)
        # Give this a unique key so Streamlit doesn't think it's the same widget
        st_folium(m2, height=700, width=1200, key="community_map")

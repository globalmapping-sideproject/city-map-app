# Streamlit City Map — Full App (with auto-refresh & de-dup)
# -------------------------------------------------------------
# Features
# - Interactive map (Folium + streamlit-folium) with marker clustering
# - City search via OpenStreetMap (Nominatim) geocoding (free)
# - Optional map-click to pick a location (with reverse geocoding)
# - User submissions saved either to Supabase (if configured) or local CSV
# - Live auto-refresh (toggle), duplicate-prevention, basic moderation hooks
# - Stats (by continent, by country), CSV download
# - Works locally and on Streamlit Community Cloud (free for public repos)
# -------------------------------------------------------------


import os
import time
import uuid
from datetime import datetime, timedelta


import pandas as pd
import streamlit as st


# Mapping & geocoding libs
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.location import Location


import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium


import country_converter as coco


# Optional Supabase backend; app still works without it
SUPABASE_AVAILABLE = False
try:
from supabase import create_client
SUPABASE_AVAILABLE = True
except Exception:
SUPABASE_AVAILABLE = False


# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="Community City Map", layout="wide")
APP_TITLE = "Community City Map"
CSV_PATH = os.path.join("data", "entries.csv")
TABLE_NAME = "entries"
DEDUP_WINDOW_HOURS = 24 # prevent identical (username+city+country) within this window


# Read secrets (works on Streamlit Cloud; locally you can set env vars)
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL"))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY"))
USE_SUPABASE = SUPABASE_AVAILABLE and bool(SUPABASE_URL) and bool(SUPABASE_KEY)


# Geopy (OpenStreetMap Nominatim) — be nice to the free service
GEOPY_USER_AGENT = st.secrets.get("GEOPY_USER_AGENT", os.getenv("GEOPY_USER_AGENT", "city-map-app/1.0 (contact: youremail@example.com)"))
_geolocator = Nominatim(user_agent=GEOPY_USER_AGENT, timeout=10)
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1)
_reverse = RateLimiter(_geolocator.reverse, min_delay_seconds=1)


cc = coco.CountryConverter()


# ----------------------------
# Storage Backends
# ----------------------------
st.sidebar.write("\n**Nominatim usage**: Use a unique `GEOPY_USER_AGENT`, cache results, and avoid rapid-fire queries.")

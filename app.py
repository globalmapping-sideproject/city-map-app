import os
import time
import uuid
import base64
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

# -------------------- Secrets / config --------------------
UA = st.secrets.get("GEOPY_USER_AGENT", "rcwg-map/1.0 (contact: you@example.com)")
GEOAPIFY_KEY = st.secrets.get("GEOAPIFY_API_KEY", None)

# GitHub sync settings
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
GITHUB_REPO = st.secrets.get("GITHUB_REPO", "")          # e.g. "globalmapping-sideproject/city-map-app"
GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
GITHUB_FILE_PATH = st.secrets.get("GITHUB_FILE_PATH", "data/entries.csv")

CSV_COLUMNS = ["id","username","city","country","lat","lon","continent","un_region","created_at"]

# -------------------- Geocoders --------------------
_geolocator = Nominatim(user_agent=UA, timeout=10)
_geocode = RateLimiter(_geolocator.geocode, min_delay_seconds=1)
_reverse = RateLimiter(_geolocator.reverse, min_delay_seconds=1)

# -------------------- GitHub helpers --------------------
def _gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def gh_get_file(owner_repo: str, path: str, branch: str):
    """Return (bytes_content, sha) or (None, None) if not found."""
    if not GITHUB_TOKEN or not owner_repo:
        return None, None
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    params = {"ref": branch}
    r = requests.get(url, headers=_gh_headers(), params=params, timeout=12)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    data = r.json()
    content_b64 = data.get("content", "")
    sha = data.get("sha")
    if content_b64:
        raw = base64.b64decode(content_b64.encode("utf-8"))
        return raw, sha
    return None, sha

def gh_put_file(owner_repo: str, path: str, branch: str, content_bytes: bytes, sha: str | None, message: str):
    """Create or update file. If sha is None → create; else update."""
    if not GITHUB_TOKEN or not owner_repo:
        raise RuntimeError("Missing GitHub token/repo in secrets.")
    url = f"https://api.github.com/repos/{owner_repo}/contents/{path}"
    body = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=_gh_headers(), json=body, timeout=15)
    r.raise_for_status()
    return r.json()

def ensure_csv_exists():
    """Create CSV in repo if missing."""
    content, sha = gh_get_file(GITHUB_REPO, GITHUB_FILE_PATH, GITHUB_BRANCH)
    if content is None:
        df = pd.DataFrame(columns=CSV_COLUMNS)
        gh_put_file(
            GITHUB_REPO,
            GITHUB_FILE_PATH,
            GITHUB_BRANCH,
            df.to_csv(index=False).encode("utf-8"),
            sha=None,
            message="chore: initialize entries.csv"
        )

# -------------------- Data helpers (GitHub-synced) --------------------
def load_entries() -> pd.DataFrame:
    """Always read fresh from GitHub so Map tab shows new pins immediately."""
    try:
        ensure_csv_exists()
        content, _sha = gh_get_file(GITHUB_REPO, GITHUB_FILE_PATH, GITHUB_BRANCH)
        if content is None:
            return pd.DataFrame(columns=CSV_COLUMNS)
        df = pd.read_csv(pd.io.common.BytesIO(content))
    except Exception:
        return pd.DataFrame(columns=CSV_COLUMNS)

    # Clean
    for col in ["lat", "lon"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for c in ["username", "city", "country"]:
        if c in df:
            df[c] = df[c].fillna("")
    # keep only valid coordinates (prevents Folium glitches)
    if "lat" in df and "lon" in df:
        df = df.dropna(subset=["lat","lon"])
        df = df[(df["lat"].between(-90,90)) & (df["lon"].between(-180,180))]
    return df

def save_entry(row: dict) -> None:
    """Append a row and push to GitHub with a commit."""
    ensure_csv_exists()
    content, sha = gh_get_file(GITHUB_REPO, GITHUB_FILE_PATH, GITHUB_BRANCH)
    if content is None:
        df = pd.DataFrame(columns=CSV_COLUMNS)
    else:
        df = pd.read_csv(pd.io.common.BytesIO(content))

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    out_bytes = df.to_csv(index=False).encode("utf-8")
    gh_put_file(
        GITHUB_REPO,
        GITHUB_FILE_PATH,
        GITHUB_BRANCH,
        out_bytes,
        sha=sha,  # include sha so it's an update, not a new file
        message=f"feat: add entry for {row.get('username','unknown')} @ {row.get('city','')}"
    )

def country_to_region(_country: str):
    # simple placeholder for future stats
    return "", ""

# -------------------- Geocoding helpers --------------------
def geoapify_autocomplete(text: str, limit: int = 10) -> pd.DataFrame:
    if not GEOAPIFY_KEY or not text.strip():
        return pd.DataFrame(columns=["display_name","lat","lon","country"])
    url = "https://api.geoapify.com/v1/geocode/autocomplete"
    params = {"text": text.strip(), "type": "city", "format": "json", "limit": limit, "apiKey": GEOAPIFY_KEY}
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        rows = []
        for it in r.json().get("results", []):
            name = it.get("formatted") or it.get("city") or it.get("name") or ""
            country = it.get("country", "")
            lat, lon = it.get("lat"), it.get("lon")
            if lat is not None and lon is not None:
                rows.append({"display_name": name, "lat": float(lat), "lon": float(lon), "country": country})
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["display_name","lat","lon","country"])

def nominatim_candidates(query: str, limit: int = 10) -> pd.DataFrame:
    if not query.strip():
        return pd.DataFrame(columns=["display_name","lat","lon","country"])
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

# Session state to keep the picker tight
if "last_query" not in st.session_state:
    st.session_state.last_query = ""
if "options_df" not in st.session_state:
    st.session_state.options_df = pd.DataFrame()
if "selected_loc" not in st.session_state:
    st.session_state.selected_loc = None

tab_add, tab_map = st.tabs(["📍 Add City", "🗺️ Map"])

with tab_add:
    st.subheader("Add yourself to the map")

    # Username
    username = st.text_input("Username", "")

    # ---- City control (single label + dropdown right under it) ----
    typed = st.text_input("City", "", placeholder="Start typing…")

    # fetch suggestions while typing
    new_df = pd.DataFrame()
    if len(typed.strip()) >= 2:
        if GEOAPIFY_KEY:
            new_df = geoapify_autocomplete(typed, limit=12)
        else:
            new_df = nominatim_candidates(typed, limit=12)

    if typed != st.session_state.last_query:
        st.session_state.options_df = new_df
        st.session_state.last_query = typed

    df_opts = st.session_state.options_df
    selected = None
    if not df_opts.empty:
        choice = st.selectbox(" ", df_opts["display_name"], index=None,
                              placeholder="Select a match…", label_visibility="collapsed")
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

    # Add button
    can_add = bool(username.strip()) and (selected is not None)
    if st.button("➕ Add this location", disabled=not can_add):
        row = dict(
            id=str(uuid.uuid4()),
            username=username.strip(),
            city=selected["city"],
            country=selected["country"],
            lat=selected["lat"],
            lon=selected["lon"],
            continent="",
            un_region="",
            created_at=datetime.utcnow().isoformat(),
        )
        try:
            save_entry(row)
            st.session_state.selected_loc = selected
            st.success("Added! Check the Map tab for the community view.")
        except Exception as e:
            st.error(f"Saving to GitHub failed: {e}")

    # ---- Preview map of just YOUR pick ----
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

    df = load_entries()
    if df.empty:
        st.info("No entries yet. Add one in the **Add City** tab.")
    else:
        # hard clean to avoid folium blank renders
        df = df.copy()
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df = df.dropna(subset=["lat","lon"])
        df = df[(df["lat"].between(-90, 90)) & (df["lon"].between(-180, 180))]

        if df.empty:
            st.info("No valid coordinates to show yet.")
        else:
            m = folium.Map(tiles="CartoDB positron")
            cluster = MarkerCluster().add_to(m)

            bounds = []
            for _, r in df.iterrows():
                try:
                    lat, lon = float(r["lat"]), float(r["lon"])
                    popup = f"<b>{r['username']}</b><br>{r['city']}<br>{r['country']}"
                    folium.Marker([lat, lon], popup=popup).add_to(cluster)
                    bounds.append((lat, lon))
                except Exception:
                    continue

            if bounds:
                m.fit_bounds(bounds, padding=(20, 20))
            else:
                m.location = [20, 0]; m.zoom_start = 2

            # Force remount when data changes (prevents blank map after multiple pins)
            key_seed = f"{len(df)}-{round(df['lat'].sum(), 6)}-{round(df['lon'].sum(), 6)}"
            try:
                st_folium(m, height=700, use_container_width=True, key=f"community_map_{key_seed}")
            except Exception:
                from streamlit.components.v1 import html
                html(m.get_root().render(), height=700)

#!/usr/bin/env python3
"""
Florida Utility Plat & Public Records Search
==============================================
Uses FREE Florida state data sources — no paid API keys required.

Data sources:
  - US Census Bureau Geocoder (geocoding — free, no key)
  - FL Dept. of Transportation ArcGIS FeatureServer (parcel data — free)
    All 67 FL counties via FL Dept. of Revenue tax roll + GIS data
  - Nominatim/OpenStreetMap (neighbourhood names — free)

Setup:
    pip install streamlit geopy requests beautifulsoup4

Run:
    streamlit run app.py

Optional API Keys (in .streamlit/secrets.toml):
    CENSUS_API_KEY – Free at https://api.census.gov/data/key_signup.html
    ATTOM_API_KEY  – Paid at https://api.gateway.attomdata.com/ (HOA data)
"""

import os
import re
import time
import json
import streamlit as st
import requests
from urllib.parse import quote_plus

try:
    from geopy.geocoders import Nominatim
    HAS_GEOPY = True
except ImportError:
    HAS_GEOPY = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APP_TITLE = "FL Utility Plat & Records Search"
APP_ICON = "⚡"
REQUEST_TIMEOUT = 15
SCRAPE_DELAY = 0.5

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY",
}
STATE_CODE_TO_FIPS = {v: k for k, v in STATE_FIPS.items()}

# FDOT ArcGIS FeatureServer — all 67 FL counties (layer IDs are alphabetical)
FDOT_BASE = "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/Florida_Statewide_Cadastral/FeatureServer/0"
FL_COUNTY_LAYERS = {
    "alachua": 1, "baker": 2, "bay": 3, "bradford": 4, "brevard": 5,
    "broward": 6, "calhoun": 7, "charlotte": 8, "citrus": 9, "clay": 10,
    "collier": 11, "columbia": 12, "desoto": 13, "dixie": 14, "duval": 15,
    "escambia": 16, "flagler": 17, "franklin": 18, "gadsden": 19, "gilchrist": 20,
    "glades": 21, "gulf": 22, "hamilton": 23, "hardee": 24, "hendry": 25,
    "hernando": 26, "highlands": 27, "hillsborough": 28, "holmes": 29,
    "indian river": 30, "jackson": 31, "jefferson": 32, "lafayette": 33,
    "lake": 34, "lee": 35, "leon": 36, "levy": 37, "liberty": 38,
    "madison": 39, "manatee": 40, "marion": 41, "martin": 42,
    "miami-dade": 43, "monroe": 44, "nassau": 45, "okaloosa": 46,
    "okeechobee": 47, "orange": 48, "osceola": 49, "palm beach": 50,
    "pasco": 51, "pinellas": 52, "polk": 53, "putnam": 54, "santa rosa": 55,
    "sarasota": 56, "seminole": 57, "st. johns": 58, "st. lucie": 59,
    "sumter": 60, "suwannee": 61, "taylor": 62, "union": 63, "volusia": 64,
    "wakulla": 65, "walton": 66, "washington": 67,
}

# Human-readable labels for FL DOR parcel fields
DOR_FIELD_LABELS = {
    "PARCELNO": "Parcel Number",
    "PARCEL_ID": "Parcel ID",
    "ASMNT_YR": "Assessment Year",
    "DOR_UC": "DOR Use Code",
    "JV": "Just Value (Market)",
    "AV_SD": "Assessed Value (School Dist.)",
    "TV_SD": "Taxable Value (School Dist.)",
    "JV_HMSTD": "Homestead Just Value",
    "AV_HMSTD": "Homestead Assessed Value",
    "LND_VAL": "Land Value",
    "LND_SQFOOT": "Land Sq Footage",
    "NO_LND_UNT": "Land Units",
    "IMP_QUAL": "Improvement Quality",
    "CONST_CLAS": "Construction Class",
    "EFF_YR_BLT": "Effective Year Built",
    "ACT_YR_BLT": "Actual Year Built",
    "TOT_LVG_AR": "Total Living Area (sqft)",
    "NO_BULDNG": "Number of Buildings",
    "NO_RES_UNT": "Residential Units",
    "SPEC_FEAT_": "Special Features Value",
    "SALE_PRC1": "Last Sale Price",
    "SALE_YR1": "Last Sale Year",
    "SALE_MO1": "Last Sale Month",
    "OR_BOOK1": "Official Records Book",
    "OR_PAGE1": "Official Records Page",
    "NCONST_VAL": "Non-Construction Value",
    "PHY_ADDR1": "Physical Address 1",
    "PHY_ADDR2": "Physical Address 2",
    "PHY_CITY": "Physical City",
    "PHY_ZIPCD": "Physical ZIP",
    "OWN_NAME": "Owner Name",
    "OWN_ADDR1": "Owner Address 1",
    "OWN_ADDR2": "Owner Address 2",
    "OWN_CITY": "Owner City",
    "OWN_STATE": "Owner State",
    "OWN_ZIPCD": "Owner ZIP",
    "S_LEGAL": "Short Legal Description",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api_key(name):
    try:
        val = st.secrets.get(name)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(name)


def safe_get(url, params=None, headers=None):
    time.sleep(SCRAPE_DELAY)
    try:
        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r
    except requests.RequestException:
        pass
    return None


# ---------------------------------------------------------------------------
# Geocoding — Census Bureau primary
# ---------------------------------------------------------------------------

CENSUS_GEO_BASE = "https://geocoding.geo.census.gov/geocoder"


def geocode_address(text):
    text = text.strip()
    if not text:
        return None
    resp = safe_get(f"{CENSUS_GEO_BASE}/geographies/onelineaddress", params={
        "address": text, "benchmark": "Public_AR_Current",
        "vintage": "Current_Current", "format": "json",
    })
    if not resp:
        return None
    try:
        matches = resp.json().get("result", {}).get("addressMatches", [])
        if not matches:
            return None
        return _census_to_loc(matches[0], text)
    except Exception:
        return None


def reverse_geocode(lat, lon):
    # Census for county/state
    resp = safe_get(f"{CENSUS_GEO_BASE}/geographies/coordinates", params={
        "x": lon, "y": lat, "benchmark": "Public_AR_Current",
        "vintage": "Current_Current", "format": "json",
    })
    county = ""
    state_code = ""
    if resp:
        try:
            geo = resp.json().get("result", {}).get("geographies", {})
            counties = geo.get("Counties", [])
            if counties:
                county = counties[0].get("NAME", "")
                if county and "county" not in county.lower() and "parish" not in county.lower():
                    county += " County"
            states = geo.get("States", [])
            if states:
                state_code = STATE_FIPS.get(states[0].get("STATE", ""), "")
        except Exception:
            pass

    # Nominatim for street address
    street_address = ""
    road = ""
    house_number = ""
    city = ""
    zip_code = ""
    neighbourhood = ""
    display = f"{lat}, {lon}"
    if HAS_GEOPY:
        try:
            g = Nominatim(user_agent="FLUtilitySearch/3.0", timeout=8)
            rev = g.reverse(f"{lat}, {lon}", exactly_one=True, language="en",
                            addressdetails=True, zoom=18)
            if rev:
                a = rev.raw.get("address", {})
                house_number = a.get("house_number", "")
                road = a.get("road", "")
                street_address = f"{house_number} {road}".strip()
                city = (a.get("city") or a.get("town") or a.get("village")
                        or a.get("hamlet") or "")
                zip_code = a.get("postcode", "")
                neighbourhood = (a.get("neighbourhood") or a.get("suburb") or "")
                display = rev.address
        except Exception:
            pass

    if not state_code:
        return None
    return {
        "lat": lat, "lon": lon, "display": display,
        "raw_input": f"{lat}, {lon}", "house_number": house_number,
        "road": road, "street_address": street_address,
        "neighbourhood": neighbourhood, "city": city, "county": county,
        "state": STATE_NAMES.get(state_code, ""), "state_code": state_code,
        "zip_code": zip_code,
    }


def _census_to_loc(match, raw_input):
    coords = match.get("coordinates", {})
    lat = coords.get("y", 0.0)
    lon = coords.get("x", 0.0)
    matched_addr = match.get("matchedAddress", raw_input)
    ac = match.get("addressComponents", {})

    # House number from user input, NOT from Census range
    house_number = ""
    m = re.match(r'^\s*(\d+)', raw_input)
    if m:
        house_number = m.group(1)
    else:
        m2 = re.match(r'^\s*(\d+)', matched_addr)
        if m2:
            house_number = m2.group(1)

    parts = [ac.get(k, "") for k in ["preDirection", "preQualifier", "preType",
             "streetName", "suffixType", "suffixDirection", "suffixQualifier"]]
    road = " ".join(p for p in parts if p)
    street_address = f"{house_number} {road}".strip()

    county = ""
    geo = match.get("geographies", {})
    counties = geo.get("Counties", [])
    if counties:
        county = counties[0].get("NAME", "")
        if county and "county" not in county.lower() and "parish" not in county.lower():
            county += " County"

    neighbourhood = ""
    if HAS_GEOPY and lat and lon:
        try:
            g = Nominatim(user_agent="FLUtilitySearch/3.0", timeout=5)
            rev = g.reverse(f"{lat}, {lon}", exactly_one=True, language="en",
                            addressdetails=True, zoom=18)
            if rev:
                a = rev.raw.get("address", {})
                neighbourhood = (a.get("neighbourhood") or a.get("suburb") or "")
        except Exception:
            pass

    state_code = ac.get("state", "")
    return {
        "lat": lat, "lon": lon, "display": matched_addr,
        "raw_input": raw_input, "house_number": house_number,
        "road": road, "street_address": street_address,
        "neighbourhood": neighbourhood, "city": ac.get("city", ""),
        "county": county, "state": STATE_NAMES.get(state_code, state_code),
        "state_code": state_code, "zip_code": ac.get("zip", ""),
    }


# ---------------------------------------------------------------------------
# FDOT Parcel Data — FREE for all 67 FL counties
# ---------------------------------------------------------------------------

def _get_fl_layer_id(county_name):
    """Map a county name like 'Okaloosa County' to its FDOT layer ID."""
    clean = county_name.lower()
    for suffix in [" county", " parish"]:
        clean = clean.replace(suffix, "")
    clean = clean.strip()
    # Handle St. vs Saint
    if clean.startswith("saint "):
        clean = "st. " + clean[6:]
    return FL_COUNTY_LAYERS.get(clean)


def fetch_fdot_parcel(lat, lon, county_name):
    """
    Query Florida GIO's public ArcGIS statewide parcel layer.
    Single layer with all 67 counties — no token required.
    Returns (attributes_dict, status_string).
    """
    debug = []
    url = f"{FDOT_BASE}/query"

    geometry = json.dumps({
        "x": lon, "y": lat,
        "spatialReference": {"wkid": 4326}
    })
    params = {
        "geometry": geometry,
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }

    debug.append(f"**Query:** `{url}`")
    debug.append(f"**Point:** ({lat:.6f}, {lon:.6f})")

    time.sleep(SCRAPE_DELAY)
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        debug.append(f"**HTTP:** {r.status_code}, {len(r.text)} bytes")

        if r.status_code == 200:
            data = r.json()
            if "error" in data:
                err = data["error"].get("message", str(data["error"]))
                debug.append(f"**ArcGIS error:** {err}")
                st.session_state["_fdot_debug"] = debug
                return None, f"ArcGIS error: {err}"

            features = data.get("features", [])
            debug.append(f"**Features returned:** {len(features)}")

            if features:
                debug.append("✅ **Parcel found!**")
                st.session_state["_fdot_debug"] = debug
                return features[0].get("attributes", {}), "OK"
            else:
                st.session_state["_fdot_debug"] = debug
                return None, "No parcel found at this point"
        else:
            debug.append(f"**Response:** `{r.text[:300]}`")
    except Exception as e:
        debug.append(f"**Exception:** {e}")

    st.session_state["_fdot_debug"] = debug
    return None, "Query failed"


def fetch_fdot_nearby(lat, lon, county_name, radius_m=500):
    """Query for parcels within a radius for neighbourhood context."""
    url = f"{FDOT_BASE}/query"
    geometry = json.dumps({
        "x": lon, "y": lat,
        "spatialReference": {"wkid": 4326}
    })
    params = {
        "geometry": geometry,
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": radius_m,
        "units": "esriSRUnit_Meter",
        "outFields": "PARCELNO,DOR_UC,S_LEGAL,JV,LND_VAL,ACT_YR_BLT,TOT_LVG_AR",
        "returnGeometry": "false",
        "resultRecordCount": 50,
        "f": "json",
    }
    resp = safe_get(url, params=params)
    if not resp:
        return []
    try:
        data = resp.json()
        if "error" in data:
            return []
        return [f.get("attributes", {}) for f in data.get("features", [])]
    except Exception:
        return []


def format_currency(val):
    try:
        v = float(val)
        if v > 0:
            return f"${v:,.0f}"
    except (ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_plat_section(loc, parcel, parcel_status, nearby):
    lines = []

    if parcel:
        lines.append("### 📋 Parcel Record (FL Dept. of Revenue / FDOT)")
        lines.append("")
        for field, label in DOR_FIELD_LABELS.items():
            val = parcel.get(field)
            if val is None or str(val).strip() in ("", "None", "Null", "0", "0.0"):
                continue
            # Format currency fields
            if any(k in field for k in ["VAL", "PRC", "JV", "AV", "TV"]):
                fv = format_currency(val)
                if fv:
                    val = fv
            lines.append(f"- **{label}:** {val}")

        # Show any extra fields not in our label map that have values
        extra_interesting = ["PHY_ADDR1", "PHY_CITY", "S_LEGAL", "OWN_NAME"]
        for key in extra_interesting:
            if key not in DOR_FIELD_LABELS:
                val = parcel.get(key)
                if val and str(val).strip() not in ("", "None", "Null"):
                    lines.append(f"- **{key}:** {val}")
        lines.append("")
    else:
        if loc.get("state_code") != "FL":
            lines.append(
                "⚠️ *This tool currently provides parcel data for **Florida only**. "
                "For other states, use the county resources below.*"
            )
        else:
            lines.append(f"⚠️ *No parcel found. FDOT response: {parcel_status}*")
        lines.append("")

    # Neighbourhood context from nearby parcels
    if nearby:
        legal_descs = set()
        use_codes = set()
        for p in nearby:
            sl = p.get("S_LEGAL")
            if sl and len(str(sl)) > 3:
                # Extract subdivision name (typically first part of legal desc)
                name = str(sl).split(" LOT")[0].split(" BLK")[0].split(" UNIT")[0].strip()
                if len(name) > 3:
                    legal_descs.add(name)
            uc = p.get("DOR_UC")
            if uc:
                use_codes.add(str(uc))

        if legal_descs:
            lines.append("### 🏘️ Subdivisions / Plats Nearby")
            lines.append("")
            lines.append(f"Extracted from legal descriptions of {len(nearby)} nearby parcels:")
            lines.append("")
            for name in sorted(legal_descs)[:15]:
                lines.append(f"- {name}")
            lines.append("")

        if use_codes:
            lines.append(f"**DOR Use Codes nearby:** {', '.join(sorted(use_codes))}")
            lines.append("")

    # County resources
    county = loc["county"]
    state = loc["state"]
    lines.append("### 🗺️ County Recorder & Plat Resources")
    lines.append("")
    rq = quote_plus(f"{county} Florida property appraiser parcel search")
    lines.append(f"- [**{county} Property Appraiser**](https://www.google.com/search?q={rq})")
    gq = quote_plus(f"{county} Florida GIS parcel viewer map")
    lines.append(f"- [**{county} GIS Viewer**](https://www.google.com/search?q={gq})")
    lines.append(
        f"- [**FL Statewide Parcel Map**]"
        f"(https://www.floridagio.gov/datasets/FGIO::florida-statewide-parcels/about)"
    )
    lines.append("- [**USGS National Map**](https://apps.nationalmap.gov/viewer/)")

    # If we have OR Book/Page, link to county clerk
    if parcel:
        book = parcel.get("OR_BOOK1")
        page = parcel.get("OR_PAGE1")
        if book and page:
            clerk_q = quote_plus(f"{county} Florida clerk of court official records book {book} page {page}")
            lines.append(f"- [**Look up OR Book {book}, Page {page}**](https://www.google.com/search?q={clerk_q})")

    lines.append("")
    lines.append(
        "> **Tip:** The Official Records Book/Page numbers link to the plat "
        "document in the county clerk's portal. Florida clerk of court records "
        "are publicly searchable online in most counties."
    )
    return "\n".join(lines)


def build_infrastructure_section(loc):
    lines = []
    county = loc["county"]
    city = loc["city"]

    lines.append("### 🚧 Florida DOT")
    lines.append("")
    lines.append("- [**FL Dept. of Transportation**](https://www.fdot.gov/)")
    pq = quote_plus(f"Florida DOT road projects near {city or county}")
    lines.append(f"- [**Active road projects**](https://www.google.com/search?q={pq})")

    lines.append("")
    lines.append("### 🏗️ Local Engineering")
    lines.append("")
    if city:
        pw = quote_plus(f"{city} Florida public works engineering")
        lines.append(f"- [**{city} Public Works**](https://www.google.com/search?q={pw})")
    ce = quote_plus(f"{county} Florida county engineer road plans")
    lines.append(f"- [**{county} County Engineer**](https://www.google.com/search?q={ce})")

    lines.append("")
    lines.append("### 📡 Utility Infrastructure")
    lines.append("")
    lines.append("- [**National Pipeline Mapping System**](https://www.npms.phmsa.dot.gov/)")
    lines.append(
        f"- [**FCC Broadband Map**](https://broadbandmap.fcc.gov/location-summary/fixed"
        f"?speed=25_3&latlon={loc['lat']:.5f},{loc['lon']:.5f})"
    )
    lines.append(
        f"- [**FEMA Flood Map**](https://msc.fema.gov/portal/search"
        f"?AddressQuery={quote_plus(loc['display'])})"
    )
    return "\n".join(lines)


def build_hoa_section(loc, parcel):
    lines = []
    city = loc["city"]
    county = loc["county"]

    # Extract subdivision from legal description if available
    subdiv = ""
    if parcel:
        sl = parcel.get("S_LEGAL", "")
        if sl:
            subdiv = str(sl).split(" LOT")[0].split(" BLK")[0].split(" UNIT")[0].strip()

    lines.append("### 🔎 HOA Lookup")
    lines.append("")
    if subdiv and len(subdiv) > 3:
        hq = quote_plus(f'"{subdiv}" HOA homeowners association {city} Florida')
        lines.append(f'- [**Search HOA for "{subdiv}"**](https://www.google.com/search?q={hq})')
    aq = quote_plus(f"{loc['display']} HOA homeowners association")
    lines.append(f"- [**Search HOA for this address**](https://www.google.com/search?q={aq})")
    lines.append(
        "- [**FL Dept. of Business — HOA Search**]"
        "(https://www.myfloridalicense.com/wl11.asp?mode=0&SID=)"
    )

    lines.append("")
    lines.append(f"- **CC&Rs** filed with **{county} Clerk of Court**.")
    lines.append("- [HOA-USA Directory](https://www.hoa-usa.com/)")
    lines.append("- Zillow / Redfin / Realtor.com list HOA fees on property pages.")
    return "\n".join(lines)


def build_municipal_section(loc):
    lines = []
    city = loc["city"]
    county = loc["county"]

    lines.append("### 🏛️ Jurisdiction")
    lines.append("")
    lines.append(f"**City:** {city or '(unincorporated)'}")
    lines.append(f"**County:** {county}")
    lines.append(f"**State:** Florida")
    if loc["zip_code"]:
        lines.append(f"**ZIP:** {loc['zip_code']}")
    lines.append("")

    lines.append("### 📞 Contacts")
    lines.append("")
    if city:
        cq = quote_plus(f"{city} Florida city government website")
        lines.append(f"- [**{city} City Government**](https://www.google.com/search?q={cq})")
    coq = quote_plus(f"{county} Florida county government")
    lines.append(f"- [**{county} Government**](https://www.google.com/search?q={coq})")
    paq = quote_plus(f"{county} Florida property appraiser")
    lines.append(f"- [**{county} Property Appraiser**](https://www.google.com/search?q={paq})")

    lines.append("")
    lines.append("### 🗂️ Zoning & Permits")
    lines.append("")
    zq = quote_plus(f"{city or county} Florida zoning map")
    lines.append(f"- [**Zoning Map**](https://www.google.com/search?q={zq})")
    pq = quote_plus(f"{city or county} Florida building permit")
    lines.append(f"- [**Building Permits**](https://www.google.com/search?q={pq})")

    lines.append("")
    lines.append("### 🔧 Public Works")
    lines.append("")
    if city:
        pwq = quote_plus(f"{city} Florida public works utilities")
        lines.append(f"- [**{city} Public Works**](https://www.google.com/search?q={pwq})")
    uq = quote_plus(f"{city or county} Florida water sewer electric utility")
    lines.append(f"- [**Utility Providers**](https://www.google.com/search?q={uq})")

    lines.append("")
    lines.append("### 🚒 Emergency Services")
    lines.append("")
    fq = quote_plus(f"{city or county} Florida fire department")
    plq = quote_plus(f"{city or county} Florida police non-emergency")
    lines.append(f"- [**Fire Dept.**](https://www.google.com/search?q={fq})")
    lines.append(f"- [**Police (non-emergency)**](https://www.google.com/search?q={plq})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def apply_styles():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    .block-container { max-width: 900px; padding-top: 1.5rem; }
    h1 { font-family: 'IBM Plex Sans', sans-serif !important; font-weight: 700 !important;
         color: #0f172a; border-bottom: 3px solid #f59e0b; padding-bottom: 0.3rem; }
    h2, h3 { font-family: 'IBM Plex Sans', sans-serif !important; color: #1e293b; }
    div[data-testid="stExpander"] { border: 1px solid #e2e8f0; border-left: 4px solid #f59e0b;
        border-radius: 6px; margin-bottom: 0.5rem; }
    div[data-testid="stExpander"] details summary p {
        font-size: 1.05rem; font-weight: 600; font-family: 'IBM Plex Sans', sans-serif; }
    .prop-card { background: #0f172a; color: #f8fafc; padding: 1rem 1.5rem;
        border-radius: 8px; font-family: 'IBM Plex Mono', monospace;
        font-size: 0.9rem; line-height: 1.7; margin-bottom: 1rem; }
    .prop-card strong { color: #fbbf24; }
    </style>
    """, unsafe_allow_html=True)


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="centered")
    apply_styles()

    st.title(f"{APP_ICON} {APP_TITLE}")
    st.caption(
        "Free parcel data for all 67 FL counties via FL Dept. of Revenue / FDOT · "
        "No API keys required"
    )
    st.markdown("---")

    # ── Input ─────────────────────────────────────────────────────────────
    tab_addr, tab_coord = st.tabs(["📍 Address Search", "🌐 Coordinate Lookup"])
    loc = None
    triggered = False

    with tab_addr:
        st.markdown("Type any Florida address below.")
        addr = st.text_input("Property address",
                             placeholder="119 Matt Blvd, Niceville, FL 32578",
                             key="addr", label_visibility="collapsed")
        st.caption("**Examples:** `119 Matt Blvd, Niceville, FL 32578` · "
                   "`1600 S Monroe St, Tallahassee, FL`")
        if st.button("🔍  Look Up Address", type="primary",
                     use_container_width=True, key="btn_a"):
            if addr.strip():
                triggered = True
                with st.spinner("Geocoding via US Census Bureau…"):
                    loc = geocode_address(addr)
            else:
                st.warning("Please enter an address.")

    with tab_coord:
        st.markdown("Enter decimal lat/lon. Resolves to nearest address.")
        c1, c2 = st.columns(2)
        with c1:
            lat_in = st.text_input("Latitude", placeholder="30.5085", key="lat")
        with c2:
            lon_in = st.text_input("Longitude", placeholder="-86.4735", key="lon")
        st.caption("**Example:** Niceville `30.5085, -86.4735`")
        if st.button("🔍  Look Up Coordinates", type="primary",
                     use_container_width=True, key="btn_c"):
            triggered = True
            try:
                lv, lnv = float(lat_in.strip()), float(lon_in.strip())
            except (ValueError, AttributeError):
                st.error("Enter valid decimal numbers.")
                return
            with st.spinner("Reverse-geocoding…"):
                loc = reverse_geocode(lv, lnv)

    if not triggered:
        return
    if loc is None:
        st.error("Could not resolve a valid US location. Check your input.")
        return

    # ── Florida check ─────────────────────────────────────────────────────
    if loc["state_code"] != "FL":
        st.warning(
            f"This address is in **{loc['state']}**. This tool provides "
            f"free parcel data for **Florida only**. Results will be limited."
        )

    # ── Property card ─────────────────────────────────────────────────────
    card = f'<div class="prop-card"><strong>📍 {loc["display"]}</strong><br>'
    if loc["street_address"]:
        card += f'Street: {loc["street_address"]}<br>'
    if loc["neighbourhood"]:
        card += f'Neighbourhood: {loc["neighbourhood"]}<br>'
    card += (f'City: {loc["city"]} · County: {loc["county"]} · '
             f'State: {loc["state"]} · ZIP: {loc["zip_code"]}<br>'
             f'Lat/Lon: {loc["lat"]:.6f}, {loc["lon"]:.6f}</div>')
    st.markdown(card, unsafe_allow_html=True)

    # ── FDOT parcel data ──────────────────────────────────────────────────
    parcel = None
    parcel_status = ""
    nearby = []
    if loc["state_code"] == "FL":
        with st.spinner("Querying FL Dept. of Transportation parcel database…"):
            parcel, parcel_status = fetch_fdot_parcel(
                loc["lat"], loc["lon"], loc["county"])
            nearby = fetch_fdot_nearby(loc["lat"], loc["lon"], loc["county"])

    # ── Sections ──────────────────────────────────────────────────────────
    with st.expander("🗺️  Plats, Subdivisions & Parcel Data", expanded=True):
        st.markdown(build_plat_section(loc, parcel, parcel_status, nearby))

    with st.expander("🛣️  Infrastructure & Road Engineering", expanded=True):
        st.markdown(build_infrastructure_section(loc))

    with st.expander("🏘️  HOA Details", expanded=True):
        st.markdown(build_hoa_section(loc, parcel))

    with st.expander("🏛️  Municipal Government & Contacts", expanded=True):
        st.markdown(build_municipal_section(loc))

    # ── Debug ─────────────────────────────────────────────────────────────
    with st.expander("🔧 Debug Info", expanded=False):
        st.write(f"**Geocoded address:** `{loc['display']}`")
        st.write(f"**County:** `{loc['county']}`")
        layer_id = _get_fl_layer_id(loc["county"])
        st.write(f"**FDOT Layer ID (base):** `{layer_id}`")
        st.write(f"**Lat/Lon:** `{loc['lat']}, {loc['lon']}`")
        st.write(f"**Parcel status:** `{parcel_status}`")
        st.write(f"**Nearby parcels:** `{len(nearby)}`")

        # Test URL for browser
        if layer_id:
            geo_str = quote_plus(json.dumps({"x": loc["lon"], "y": loc["lat"],
                                             "spatialReference": {"wkid": 4326}}))
            test_url = (f"{FDOT_BASE}/{layer_id}/query?geometry={geo_str}"
                        f"&geometryType=esriGeometryPoint"
                        f"&spatialRel=esriSpatialRelIntersects"
                        f"&outFields=PARCELNO,S_LEGAL,JV"
                        f"&returnGeometry=false&f=json")
            st.write(f"**Test in browser:** [Layer {layer_id} query]({test_url})")

        st.write("---")
        st.write("**FDOT API call log:**")
        for line in st.session_state.get("_fdot_debug", []):
            st.markdown(line)

        if parcel:
            st.write("---")
            st.write("**Parcel data:**")
            st.json({k: v for k, v in parcel.items()
                     if v is not None and str(v).strip() not in ("", "0", "0.0")})

    st.divider()
    st.caption(
        "**Data source:** FL Dept. of Revenue tax roll via FDOT ArcGIS FeatureServer. "
        "Free, public, no API key required. Updated annually. "
        "Not a substitute for a legal survey or title search."
    )


if __name__ == "__main__":
    main()

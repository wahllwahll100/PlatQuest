#!/usr/bin/env python3
"""
Utility Plat & Public Records Search
======================================
A Streamlit tool for utility companies to look up plat records,
subdivision data, infrastructure, HOA, and municipal contacts
for any US property address.

GEOCODING: Uses the US Census Bureau Geocoder (free, no key needed,
covers virtually all US addresses via TIGER/Line) as the primary
geocoder, with Nominatim as a fallback for neighbourhood context.

Setup:
    pip install streamlit geopy requests beautifulsoup4

Run:
    streamlit run app.py

Optional API Keys (set in .streamlit/secrets.toml or env vars):
    REGRID_API_KEY  – Free tier at https://regrid.com/api
    CENSUS_API_KEY  – Free at https://api.census.gov/data/key_signup.html
    ATTOM_API_KEY   – Paid at https://api.gateway.attomdata.com/
"""

import os
import re
import time
import json
import streamlit as st
import requests
from urllib.parse import quote_plus

# Nominatim is used only as a supplement for neighbourhood names
try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
    HAS_GEOPY = True
except ImportError:
    HAS_GEOPY = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APP_TITLE = "Utility Plat & Records Search"
APP_ICON = "⚡"
REQUEST_TIMEOUT = 15
SCRAPE_DELAY = 1.0

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

STATE_DOT_URLS = {
    "AL": "https://www.dot.state.al.us/", "AK": "https://dot.alaska.gov/",
    "AZ": "https://azdot.gov/", "AR": "https://www.ardot.gov/",
    "CA": "https://dot.ca.gov/", "CO": "https://www.codot.gov/",
    "CT": "https://portal.ct.gov/dot", "DE": "https://deldot.gov/",
    "FL": "https://www.fdot.gov/", "GA": "https://www.dot.ga.gov/",
    "HI": "https://hidot.hawaii.gov/", "ID": "https://itd.idaho.gov/",
    "IL": "https://idot.illinois.gov/", "IN": "https://www.in.gov/indot/",
    "IA": "https://iowadot.gov/", "KS": "https://www.ksdot.gov/",
    "KY": "https://transportation.ky.gov/", "LA": "https://www.dotd.la.gov/",
    "ME": "https://www.maine.gov/mdot/", "MD": "https://www.roads.maryland.gov/",
    "MA": "https://www.mass.gov/orgs/massachusetts-department-of-transportation",
    "MI": "https://www.michigan.gov/mdot", "MN": "https://www.dot.state.mn.us/",
    "MS": "https://mdot.ms.gov/", "MO": "https://www.modot.org/",
    "MT": "https://www.mdt.mt.gov/", "NE": "https://dot.nebraska.gov/",
    "NV": "https://www.dot.nv.gov/", "NH": "https://www.nh.gov/dot/",
    "NJ": "https://www.nj.gov/transportation/", "NM": "https://www.dot.nm.gov/",
    "NY": "https://www.dot.ny.gov/", "NC": "https://www.ncdot.gov/",
    "ND": "https://www.dot.nd.gov/", "OH": "https://www.transportation.ohio.gov/",
    "OK": "https://oklahoma.gov/odot.html", "OR": "https://www.oregon.gov/odot/",
    "PA": "https://www.penndot.pa.gov/", "RI": "https://www.dot.ri.gov/",
    "SC": "https://www.scdot.org/", "SD": "https://dot.sd.gov/",
    "TN": "https://www.tn.gov/tdot.html", "TX": "https://www.txdot.gov/",
    "UT": "https://www.udot.utah.gov/", "VT": "https://vtrans.vermont.gov/",
    "VA": "https://www.virginiadot.org/", "WA": "https://wsdot.wa.gov/",
    "WV": "https://transportation.wv.gov/", "WI": "https://wisconsindot.gov/",
    "WY": "https://www.dot.state.wy.us/", "DC": "https://ddot.dc.gov/",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api_key(name: str) -> str | None:
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
        r = requests.get(url, params=params, headers=headers,
                         timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r
    except requests.RequestException:
        pass
    return None


# ---------------------------------------------------------------------------
# GEOCODING — US Census Bureau Geocoder (primary)
# ---------------------------------------------------------------------------
# The Census Bureau geocoder is free, needs no API key, and uses
# TIGER/Line data covering virtually every deliverable US address.
# https://geocoding.geo.census.gov/geocoder/
# ---------------------------------------------------------------------------

CENSUS_GEO_BASE = "https://geocoding.geo.census.gov/geocoder"


def _census_onelineaddress(address: str) -> dict | None:
    """
    Geocode a single-line address via the Census Bureau geocoder.
    Returns our standardized location dict or None.
    """
    url = f"{CENSUS_GEO_BASE}/geographies/onelineaddress"
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    resp = safe_get(url, params=params)
    if not resp:
        return None
    try:
        data = resp.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            return None
        return _census_match_to_loc(matches[0], address)
    except Exception:
        return None


def _census_address_parts(street: str, city: str, state: str,
                          zip_code: str) -> dict | None:
    """Geocode using structured address fields."""
    url = f"{CENSUS_GEO_BASE}/geographies/address"
    params = {
        "street": street,
        "city": city,
        "state": state,
        "zip": zip_code,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    resp = safe_get(url, params=params)
    if not resp:
        return None
    try:
        data = resp.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if not matches:
            return None
        raw = f"{street}, {city}, {state} {zip_code}".strip(", ")
        return _census_match_to_loc(matches[0], raw)
    except Exception:
        return None


def _census_match_to_loc(match: dict, raw_input: str) -> dict:
    """Convert a Census geocoder match to our location dict."""
    coords = match.get("coordinates", {})
    lat = coords.get("y", 0.0)
    lon = coords.get("x", 0.0)

    matched_addr = match.get("matchedAddress", raw_input)
    addr_components = match.get("addressComponents", {})

    street_name = addr_components.get("streetName", "")
    pre_type = addr_components.get("preType", "")
    pre_dir = addr_components.get("preDirection", "")
    pre_qual = addr_components.get("preQualifier", "")
    suf_type = addr_components.get("suffixType", "")
    suf_dir = addr_components.get("suffixDirection", "")
    suf_qual = addr_components.get("suffixQualifier", "")
    from_addr = addr_components.get("fromAddress", "")
    to_addr = addr_components.get("toAddress", "")

    # Build a clean street address
    house_number = from_addr  # Census returns the matched range start
    road_parts = [p for p in [pre_dir, pre_qual, pre_type, street_name,
                              suf_type, suf_dir, suf_qual] if p]
    road = " ".join(road_parts)
    street_address = f"{house_number} {road}".strip()

    city = addr_components.get("city", "")
    state_code = addr_components.get("state", "")
    zip_code = addr_components.get("zip", "")

    # County from geographies
    county = ""
    geographies = match.get("geographies", {})
    counties = geographies.get("Counties", [])
    if counties:
        county = counties[0].get("NAME", "")
        if county and not county.endswith("County") and not county.endswith("Parish"):
            county = county + " County"

    # Try to get neighbourhood from Nominatim reverse (non-blocking)
    neighbourhood = ""
    if HAS_GEOPY and lat and lon:
        try:
            geolocator = Nominatim(user_agent="UtilityPlatSearch/2.0", timeout=5)
            rev = geolocator.reverse(f"{lat}, {lon}", exactly_one=True,
                                     language="en", addressdetails=True, zoom=18)
            if rev:
                a = rev.raw.get("address", {})
                neighbourhood = (a.get("neighbourhood") or a.get("suburb")
                                 or a.get("quarter") or "")
        except Exception:
            pass

    return {
        "lat": lat,
        "lon": lon,
        "display": matched_addr,
        "raw_input": raw_input,
        "house_number": house_number,
        "road": road,
        "street_address": street_address,
        "neighbourhood": neighbourhood,
        "city": city,
        "county": county,
        "state": STATE_NAMES.get(state_code, state_code),
        "state_code": state_code,
        "zip_code": zip_code,
    }


def _census_reverse(lat: float, lon: float) -> dict | None:
    """Reverse geocode coordinates via Census Bureau."""
    url = f"{CENSUS_GEO_BASE}/geographies/coordinates"
    params = {
        "x": lon,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    resp = safe_get(url, params=params)
    if not resp:
        return None
    try:
        data = resp.json()
        geographies = data.get("result", {}).get("geographies", {})

        # Get county
        county = ""
        counties = geographies.get("Counties", [])
        if counties:
            county = counties[0].get("NAME", "")
            if county and not county.endswith("County") and not county.endswith("Parish"):
                county += " County"

        # Get state
        state_code = ""
        states = geographies.get("States", [])
        if states:
            state_fips = states[0].get("STATE", "")
            state_code = STATE_FIPS.get(state_fips, "")

        # Census reverse doesn't return a street address, so use Nominatim
        street_address = ""
        road = ""
        house_number = ""
        city = ""
        zip_code = ""
        neighbourhood = ""
        display = f"{lat}, {lon}"

        if HAS_GEOPY:
            try:
                geolocator = Nominatim(user_agent="UtilityPlatSearch/2.0", timeout=8)
                rev = geolocator.reverse(f"{lat}, {lon}", exactly_one=True,
                                         language="en", addressdetails=True, zoom=18)
                if rev:
                    a = rev.raw.get("address", {})
                    house_number = a.get("house_number", "")
                    road = a.get("road", "")
                    street_address = f"{house_number} {road}".strip()
                    city = (a.get("city") or a.get("town") or a.get("village")
                            or a.get("hamlet") or a.get("municipality") or "")
                    zip_code = a.get("postcode", "")
                    neighbourhood = (a.get("neighbourhood") or a.get("suburb")
                                     or a.get("quarter") or "")
                    display = rev.address
            except Exception:
                pass

        if not state_code:
            return None

        return {
            "lat": lat,
            "lon": lon,
            "display": display,
            "raw_input": f"{lat}, {lon}",
            "house_number": house_number,
            "road": road,
            "street_address": street_address,
            "neighbourhood": neighbourhood,
            "city": city,
            "county": county,
            "state": STATE_NAMES.get(state_code, state_code),
            "state_code": state_code,
            "zip_code": zip_code,
        }
    except Exception:
        return None


def geocode_address(text: str) -> dict | None:
    """
    Primary geocode function. Tries Census Bureau first (covers
    virtually all US addresses), falls back to Nominatim.
    """
    text = text.strip()
    if not text:
        return None

    # 1) Census Bureau — one-line address (handles any format)
    loc = _census_onelineaddress(text)
    if loc:
        return loc

    # 2) If that fails, try with ", USA" appended
    if not re.search(r'\b(USA?|United States)\b', text, re.I):
        loc = _census_onelineaddress(text + ", USA")
        if loc:
            return loc

    # 3) Fall back to Nominatim
    if HAS_GEOPY:
        try:
            geolocator = Nominatim(user_agent="UtilityPlatSearch/2.0", timeout=12)
            results = geolocator.geocode(
                text, exactly_one=False, limit=5,
                language="en", addressdetails=True, countrycodes="us",
            )
            if results:
                for r in results:
                    a = r.raw.get("address", {})
                    if a.get("country_code") == "us":
                        return _nominatim_to_loc(r, text)
        except Exception:
            pass

    return None


def reverse_geocode(lat: float, lon: float) -> dict | None:
    """Reverse geocode coordinates."""
    loc = _census_reverse(lat, lon)
    if loc:
        return loc
    # Nominatim fallback
    if HAS_GEOPY:
        try:
            geolocator = Nominatim(user_agent="UtilityPlatSearch/2.0", timeout=12)
            r = geolocator.reverse(f"{lat}, {lon}", exactly_one=True,
                                   language="en", addressdetails=True, zoom=18)
            if r and r.raw.get("address", {}).get("country_code") == "us":
                return _nominatim_to_loc(r, f"{lat}, {lon}")
        except Exception:
            pass
    return None


def _nominatim_to_loc(location, raw_input: str) -> dict:
    """Convert Nominatim result to our standard dict."""
    a = location.raw.get("address", {})
    sc = a.get("ISO3166-2-lvl4", "")
    if sc.startswith("US-"):
        sc = sc[3:]
    if not sc:
        for code, name in STATE_NAMES.items():
            if name.lower() == a.get("state", "").lower():
                sc = code
                break
    city = (a.get("city") or a.get("town") or a.get("village")
            or a.get("hamlet") or a.get("municipality") or "")
    hn = a.get("house_number", "")
    rd = a.get("road", "")
    return {
        "lat": location.latitude,
        "lon": location.longitude,
        "display": location.address,
        "raw_input": raw_input,
        "house_number": hn,
        "road": rd,
        "street_address": f"{hn} {rd}".strip(),
        "neighbourhood": (a.get("neighbourhood") or a.get("suburb")
                          or a.get("quarter") or ""),
        "city": city,
        "county": a.get("county", ""),
        "state": a.get("state", ""),
        "state_code": sc,
        "zip_code": a.get("postcode", ""),
    }


# ---------------------------------------------------------------------------
# Regrid API
# ---------------------------------------------------------------------------

def fetch_regrid_parcel(lat, lon, token):
    url = "https://app.regrid.com/api/v1/search.json"
    params = {"lat": lat, "lon": lon, "radius": 10, "limit": 1, "token": token}
    resp = safe_get(url, params=params)
    if resp:
        try:
            data = resp.json()
            results = data.get("results", [])
            if results:
                return results[0].get("properties", {})
        except Exception:
            pass
    return None


def fetch_regrid_nearby(lat, lon, token, radius=500, limit=50):
    url = "https://app.regrid.com/api/v1/search.json"
    params = {"lat": lat, "lon": lon, "radius": radius,
              "limit": limit, "token": token}
    resp = safe_get(url, params=params)
    if resp:
        try:
            data = resp.json()
            return [r.get("properties", {}) for r in data.get("results", [])]
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_plat_section(loc, parcel, nearby):
    lines = []

    if parcel:
        lines.append("### 📋 Parcel Record (Regrid)")
        lines.append("")
        fields = {
            "parcelnumb": "Parcel Number (APN)",
            "owner": "Owner",
            "address": "Situs Address",
            "ll_gisacre": "Acreage (GIS)",
            "ll_gissqft": "Sq Ft (GIS)",
            "usedesc": "Use Description",
            "zoning": "Zoning",
            "zoning_description": "Zoning Description",
            "yearbuilt": "Year Built",
            "improvval": "Improvement Value",
            "landval": "Land Value",
            "parval": "Total Assessed Value",
            "saleprice": "Last Sale Price",
            "saledate": "Last Sale Date",
            "legaldesc": "Legal Description",
            "subdivision": "Subdivision Name",
            "book": "Book",
            "page": "Page",
            "block": "Block",
            "lot": "Lot",
        }
        for k, label in fields.items():
            v = parcel.get(k)
            if v and str(v).strip() and str(v).strip().lower() not in ("none", "null", "0"):
                lines.append(f"- **{label}:** {v}")
        lines.append("")
    else:
        lines.append(
            "⚠️ *No Regrid API key — parcel data unavailable. "
            "Add `REGRID_API_KEY` in Settings → Secrets.*"
        )
        lines.append("")

    if nearby:
        subs = set()
        for p in nearby:
            s = p.get("subdivision")
            if s and str(s).strip().lower() not in ("", "none", "null"):
                subs.add(str(s).strip())
        if subs:
            lines.append("### 🏘️ Subdivisions Nearby (~500 m)")
            lines.append("")
            for s in sorted(subs):
                lines.append(f"- {s}")
            lines.append("")
        zones = set()
        for p in nearby:
            z = p.get("zoning") or p.get("zoning_description")
            if z and str(z).strip().lower() not in ("", "none", "null"):
                zones.add(str(z).strip())
        if zones:
            lines.append("**Zoning nearby:** " + ", ".join(sorted(zones)))
            lines.append("")

    county = loc["county"]
    state = loc["state"]
    lines.append("### 🗺️ County Recorder & Plat Resources")
    lines.append("")
    rq = quote_plus(f"{county} {state} recorder plat map search")
    lines.append(f"- [**{county} Recorder — Plat Maps**](https://www.google.com/search?q={rq})")
    gq = quote_plus(f"{county} {state} GIS parcel viewer")
    lines.append(f"- [**{county} GIS / Parcel Viewer**](https://www.google.com/search?q={gq})")
    lines.append(
        f"- [**Regrid Interactive Map**]"
        f"(https://app.regrid.com/us#{loc['lat']:.5f}/{loc['lon']:.5f}/17)"
    )
    lines.append("- [**USGS National Map**](https://apps.nationalmap.gov/viewer/)")

    sd = parcel.get("subdivision", "") if parcel else ""
    if sd:
        sq = quote_plus(f'"{sd}" plat {county} {state}')
        lines.append(f'- [**Search plat for "{sd}"**](https://www.google.com/search?q={sq})')

    lines.append("")
    lines.append(
        "> **Tip:** Use the Book/Page numbers above to pull the exact plat "
        "document from the county recorder's online portal."
    )
    return "\n".join(lines)


def build_infrastructure_section(loc):
    lines = []
    sc = loc["state_code"]
    state = loc["state"]
    county = loc["county"]
    city = loc["city"]

    dot_url = STATE_DOT_URLS.get(sc, "")
    lines.append("### 🚧 State DOT")
    lines.append("")
    if dot_url:
        lines.append(f"- [**{state} Dept. of Transportation**]({dot_url})")
    pq = quote_plus(f"{state} DOT road projects near {city or county}")
    lines.append(f"- [**Active road projects**](https://www.google.com/search?q={pq})")

    lines.append("")
    lines.append("### 🏗️ Local Engineering")
    lines.append("")
    if city:
        pw = quote_plus(f"{city} {state} public works engineering road plans")
        lines.append(f"- [**{city} Public Works**](https://www.google.com/search?q={pw})")
    ce = quote_plus(f"{county} {state} county engineer road plans")
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
    lines.append("- [**FHWA NHS Maps**](https://www.fhwa.dot.gov/planning/national_highway_system/nhs_maps/)")
    lines.append("- [**National Bridge Inventory**](https://www.fhwa.dot.gov/bridge/nbi.cfm)")

    lines.append("")
    lines.append(
        "> **For as-built drawings:** File a FOIA request with the DOT district "
        "office or county engineer."
    )
    return "\n".join(lines)


def build_hoa_section(loc, parcel):
    lines = []
    city = loc["city"]
    county = loc["county"]
    state = loc["state"]
    sc = loc["state_code"]
    sd = (parcel.get("subdivision", "") or "") if parcel else ""

    attom_key = get_api_key("ATTOM_API_KEY")
    if attom_key:
        lines.append("### 🏘️ HOA Data (ATTOM)")
        lines.append("")
        headers = {"apikey": attom_key, "Accept": "application/json"}
        params = {
            "address1": loc.get("street_address") or loc["raw_input"],
            "address2": f"{city}, {sc} {loc['zip_code']}",
        }
        resp = safe_get(
            "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/detail",
            params=params, headers=headers,
        )
        if resp:
            try:
                data = resp.json()
                prop = data.get("property", [{}])[0]
                fee = prop.get("assessment", {}).get("hoaFee")
                if fee:
                    lines.append(f"- **HOA Fee:** ${fee}/year")
                else:
                    lines.append("- No HOA fee on record.")
            except Exception:
                lines.append("- Could not parse ATTOM response.")
        else:
            lines.append("- ATTOM request failed.")
        lines.append("")

    lines.append("### 🔎 HOA Lookup")
    lines.append("")
    if sd:
        hq = quote_plus(f'"{sd}" HOA homeowners association {city} {state}')
        lines.append(f'- [**Search HOA for "{sd}"**](https://www.google.com/search?q={hq})')
    aq = quote_plus(f"{loc['display']} HOA")
    lines.append(f"- [**Search HOA for this address**](https://www.google.com/search?q={aq})")
    sq = quote_plus(f"{state} secretary of state HOA nonprofit search")
    lines.append(f"- [**{state} SOS — HOA Search**](https://www.google.com/search?q={sq})")

    lines.append("")
    lines.append(f"- **CC&Rs** filed with **{county} Recorder**.")
    lines.append("- [HOA-USA Directory](https://www.hoa-usa.com/)")
    lines.append("- [Community Associations Institute](https://www.caionline.org/)")

    if not attom_key:
        lines.append("")
        lines.append("> Add `ATTOM_API_KEY` for live HOA data.")
    return "\n".join(lines)


def build_municipal_section(loc):
    lines = []
    city = loc["city"]
    county = loc["county"]
    state = loc["state"]
    sc = loc["state_code"]

    lines.append("### 🏛️ Jurisdiction")
    lines.append("")
    lines.append(f"**City:** {city or '(unincorporated)'}")
    lines.append(f"**County:** {county}")
    lines.append(f"**State:** {state}")
    if loc["zip_code"]:
        lines.append(f"**ZIP:** {loc['zip_code']}")
    lines.append("")

    census_key = get_api_key("CENSUS_API_KEY")
    fips = STATE_CODE_TO_FIPS.get(sc, "")
    if fips and census_key:
        try:
            resp = safe_get(
                "https://api.census.gov/data/2022/acs/acs5",
                params={"get": "NAME,B01003_001E", "for": "county:*",
                        "in": f"state:{fips}", "key": census_key},
            )
            if resp:
                rows = resp.json()
                cc = county.replace(" County", "").replace(" Parish", "").strip()
                for row in rows[1:]:
                    if cc.lower() in row[0].lower():
                        lines.append(f"**{county} Population (ACS 2022):** {int(row[1]):,}")
                        lines.append("")
                        break
        except Exception:
            pass

    lines.append("### 📞 Contacts")
    lines.append("")
    if city:
        cq = quote_plus(f"{city} {state} city government official website")
        lines.append(f"- [**{city} City Government**](https://www.google.com/search?q={cq})")
        mq = quote_plus(f"{city} {state} mayor contact")
        lines.append(f"- [**Mayor's Office**](https://www.google.com/search?q={mq})")
    coq = quote_plus(f"{county} {state} county government")
    lines.append(f"- [**{county} Government**](https://www.google.com/search?q={coq})")

    lines.append("")
    lines.append("### 🗂️ Zoning & Permits")
    lines.append("")
    zq = quote_plus(f"{city or county} {state} zoning map")
    lines.append(f"- [**Zoning Map**](https://www.google.com/search?q={zq})")
    pq = quote_plus(f"{city or county} {state} building permit")
    lines.append(f"- [**Building Permits**](https://www.google.com/search?q={pq})")
    lines.append(
        f"- [**Regrid Zoning**](https://app.regrid.com/us#{loc['lat']:.5f}/{loc['lon']:.5f}/17)"
    )

    lines.append("")
    lines.append("### 🔧 Public Works")
    lines.append("")
    if city:
        pwq = quote_plus(f"{city} {state} public works utilities")
        lines.append(f"- [**{city} Public Works**](https://www.google.com/search?q={pwq})")
    uq = quote_plus(f"{city or county} {state} water sewer electric utility")
    lines.append(f"- [**Utility Providers**](https://www.google.com/search?q={uq})")

    lines.append("")
    lines.append("### 🚒 Emergency Services")
    lines.append("")
    fq = quote_plus(f"{city or county} {state} fire department")
    plq = quote_plus(f"{city or county} {state} police non-emergency")
    lines.append(f"- [**Fire Dept.**](https://www.google.com/search?q={fq})")
    lines.append(f"- [**Police (non-emergency)**](https://www.google.com/search?q={plq})")

    cf = quote_plus(county.lower().replace(" ", "") + sc.lower())
    lines.append("")
    lines.append(f"- [**Census QuickFacts — {county}**](https://www.census.gov/quickfacts/{cf})")
    lines.append("- [**USA.gov Local Government**](https://www.usa.gov/local-governments)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def apply_styles():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
    .block-container { max-width: 900px; padding-top: 1.5rem; }
    h1 {
        font-family: 'IBM Plex Sans', sans-serif !important;
        font-weight: 700 !important; color: #0f172a;
        border-bottom: 3px solid #f59e0b; padding-bottom: 0.3rem;
    }
    h2, h3 { font-family: 'IBM Plex Sans', sans-serif !important; color: #1e293b; }
    div[data-testid="stExpander"] {
        border: 1px solid #e2e8f0; border-left: 4px solid #f59e0b;
        border-radius: 6px; margin-bottom: 0.5rem;
    }
    div[data-testid="stExpander"] details summary p {
        font-size: 1.05rem; font-weight: 600;
        font-family: 'IBM Plex Sans', sans-serif;
    }
    .prop-card {
        background: #0f172a; color: #f8fafc;
        padding: 1rem 1.5rem; border-radius: 8px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.9rem; line-height: 1.7; margin-bottom: 1rem;
    }
    .prop-card strong { color: #fbbf24; }
    .api-badge {
        display: inline-block; border-radius: 4px;
        padding: 2px 8px; font-size: 0.75rem; font-weight: 600; margin-left: 6px;
    }
    .api-badge.on { background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; }
    .api-badge.off { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
    </style>
    """, unsafe_allow_html=True)


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="centered")
    apply_styles()

    st.title(f"{APP_ICON} {APP_TITLE}")
    st.caption("Parcel records · Subdivision plats · Infrastructure · HOA · Municipal contacts")

    # API badges
    regrid_key = get_api_key("REGRID_API_KEY")
    census_key = get_api_key("CENSUS_API_KEY")
    attom_key = get_api_key("ATTOM_API_KEY")

    def badge(name, ok):
        cls = "on" if ok else "off"
        sym = "✓" if ok else "✗"
        return f'<span class="api-badge {cls}">{name} {sym}</span>'

    st.markdown(
        "**Data sources:** "
        + '<span class="api-badge on">Census Geocoder ✓</span>'
        + badge("Regrid", regrid_key)
        + badge("Census Data", census_key)
        + badge("ATTOM", attom_key),
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # ── Input ─────────────────────────────────────────────────────────────
    tab_addr, tab_coord = st.tabs(["📍 Address Search", "🌐 Coordinate Lookup"])

    loc = None
    triggered = False

    with tab_addr:
        st.markdown(
            "Type any US street address. The Census Bureau geocoder "
            "covers virtually every deliverable address in the US."
        )
        addr = st.text_input(
            "Property address",
            placeholder="119 Matt Blvd, Niceville, FL 32578",
            key="addr",
            label_visibility="collapsed",
        )
        st.caption(
            "**Examples:** `119 Matt Blvd, Niceville, FL 32578` · "
            "`1600 Pennsylvania Ave NW, Washington, DC` · "
            "`350 Fifth Avenue, New York, NY 10118`"
        )
        if st.button("🔍  Look Up Address", type="primary",
                     use_container_width=True, key="btn_a"):
            if addr.strip():
                triggered = True
                with st.spinner("Geocoding via US Census Bureau…"):
                    loc = geocode_address(addr)
            else:
                st.warning("Please enter an address.")

    with tab_coord:
        st.markdown(
            "Enter decimal latitude and longitude. "
            "Resolves to the nearest street address and neighbourhood."
        )
        c1, c2 = st.columns(2)
        with c1:
            lat_in = st.text_input("Latitude", placeholder="30.5085",
                                   help="Decimal degrees. US: ~24–49 N", key="lat")
        with c2:
            lon_in = st.text_input("Longitude", placeholder="-86.4735",
                                   help="Decimal degrees. US: ~-67 to -125 W", key="lon")
        st.caption(
            "**Examples:** Niceville `30.5085, -86.4735` · "
            "LA `34.0522, -118.2437` · Miami `25.7617, -80.1918`"
        )
        if st.button("🔍  Look Up Coordinates", type="primary",
                     use_container_width=True, key="btn_c"):
            triggered = True
            try:
                lv = float(lat_in.strip())
                lnv = float(lon_in.strip())
            except (ValueError, AttributeError):
                st.error("Enter valid decimal numbers.")
                return
            if not (-90 <= lv <= 90 and -180 <= lnv <= 180):
                st.error("Coordinates out of range.")
                return
            with st.spinner("Reverse-geocoding…"):
                loc = reverse_geocode(lv, lnv)

    if not triggered:
        return
    if loc is None:
        st.error(
            "Could not resolve a valid US location. "
            "Check the address spelling and try again."
        )
        return

    # ── Property card ─────────────────────────────────────────────────────
    card = f'<div class="prop-card"><strong>📍 {loc["display"]}</strong><br>'
    if loc["street_address"]:
        card += f'Street: {loc["street_address"]}<br>'
    if loc["neighbourhood"]:
        card += f'Neighbourhood: {loc["neighbourhood"]}<br>'
    card += (
        f'City: {loc["city"]} · County: {loc["county"]} · '
        f'State: {loc["state"]} · ZIP: {loc["zip_code"]}<br>'
        f'Lat/Lon: {loc["lat"]:.6f}, {loc["lon"]:.6f}</div>'
    )
    st.markdown(card, unsafe_allow_html=True)

    # ── Regrid ────────────────────────────────────────────────────────────
    parcel = None
    nearby = []
    if regrid_key:
        with st.spinner("Querying Regrid for parcel & subdivision data…"):
            parcel = fetch_regrid_parcel(loc["lat"], loc["lon"], regrid_key)
            nearby = fetch_regrid_nearby(loc["lat"], loc["lon"], regrid_key)

    # ── Sections ──────────────────────────────────────────────────────────
    with st.expander("🗺️  Plats, Subdivisions & Parcel Data", expanded=True):
        st.markdown(build_plat_section(loc, parcel, nearby))

    with st.expander("🛣️  Infrastructure & Road Engineering", expanded=True):
        st.markdown(build_infrastructure_section(loc))

    with st.expander("🏘️  HOA Details", expanded=True):
        st.markdown(build_hoa_section(loc, parcel))

    with st.expander("🏛️  Municipal Government & Contacts", expanded=True):
        st.markdown(build_municipal_section(loc))

    st.divider()
    st.caption(
        "**Disclaimer:** Aggregates public records and government links. "
        "Not a substitute for a legal survey or title search."
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Utility Plat & Public Records Search
======================================
A Streamlit tool for utility companies to look up plat records,
subdivision data, infrastructure info, HOA details, and municipal
contacts for any US property address.

Setup:
    pip install streamlit geopy requests beautifulsoup4

Run:
    streamlit run app.py

API Keys (set in .streamlit/secrets.toml or as env vars):
    Required for full functionality:
        REGRID_API_KEY  – Free tier at https://regrid.com/api (parcel/subdivision data)
    Optional:
        CENSUS_API_KEY  – Free at https://api.census.gov/data/key_signup.html
        ATTOM_API_KEY   – Paid at https://api.gateway.attomdata.com/ (HOA data)

    The app works without any keys but provides richer data with them.
"""

import os
import re
import time
import json
import streamlit as st
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_TITLE = "Utility Plat & Records Search"
APP_ICON = "⚡"
USER_AGENT = "UtilityPlatSearch/2.0 (utility-tool)"
REQUEST_TIMEOUT = 12
SCRAPE_DELAY = 1.0

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "FL": "12", "GA": "13",
    "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29",
    "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34",
    "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50",
    "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56",
    "DC": "11",
}

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


def safe_get(url: str, params: dict | None = None,
             headers: dict | None = None) -> requests.Response | None:
    time.sleep(SCRAPE_DELAY)
    try:
        resp = requests.get(url, params=params, headers=headers,
                            timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp
    except requests.RequestException:
        pass
    return None


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def geocode_address(address_text: str) -> dict | None:
    """
    Geocode a free-form US address. Accepts any reasonable format:
        '123 Main St, Anytown, CA 90210'
        '123 Main St Anytown CA'
        'Anytown, CA'
        '90210'
    """
    raw = address_text.strip()
    if not raw:
        return None

    geolocator = Nominatim(user_agent=USER_AGENT, timeout=12)

    try:
        results = geolocator.geocode(
            raw, exactly_one=False, limit=5,
            language="en", addressdetails=True, countrycodes="us",
        )
        if not results:
            results = geolocator.geocode(
                raw + ", USA", exactly_one=False, limit=5,
                language="en", addressdetails=True, countrycodes="us",
            )
        if not results:
            return None

        for loc in results:
            addr = loc.raw.get("address", {})
            if addr.get("country_code") != "us":
                continue
            return _build_loc(loc, raw)
        return None

    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        st.warning(f"Geocoding service temporarily unavailable: {e}")
        return None
    except Exception as e:
        st.warning(f"Geocoding error: {e}")
        return None


def reverse_geocode(lat: float, lon: float) -> dict | None:
    """Reverse-geocode to a full street address."""
    geolocator = Nominatim(user_agent=USER_AGENT, timeout=12)
    try:
        loc = geolocator.reverse(
            f"{lat}, {lon}", exactly_one=True,
            language="en", addressdetails=True, zoom=18,
        )
        if not loc:
            return None
        addr = loc.raw.get("address", {})
        if addr.get("country_code") != "us":
            return None
        return _build_loc(loc, f"{lat}, {lon}")
    except Exception:
        return None


def _build_loc(location, raw_input: str) -> dict:
    addr = location.raw.get("address", {})
    state_code = addr.get("ISO3166-2-lvl4", "")
    if state_code.startswith("US-"):
        state_code = state_code[3:]
    if not state_code:
        for code, name in STATE_NAMES.items():
            if name.lower() == addr.get("state", "").lower():
                state_code = code
                break

    city = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("hamlet") or addr.get("municipality") or "")
    county = addr.get("county", "")
    house_number = addr.get("house_number", "")
    road = addr.get("road", "")
    street_address = f"{house_number} {road}".strip()
    neighbourhood = (addr.get("neighbourhood") or addr.get("suburb")
                     or addr.get("quarter") or "")

    return {
        "lat": location.latitude,
        "lon": location.longitude,
        "display": location.address,
        "raw_input": raw_input,
        "house_number": house_number,
        "road": road,
        "street_address": street_address,
        "neighbourhood": neighbourhood,
        "city": city,
        "county": county,
        "state": addr.get("state", ""),
        "state_code": state_code,
        "zip_code": addr.get("postcode", ""),
    }


# ---------------------------------------------------------------------------
# Regrid API
# ---------------------------------------------------------------------------

def fetch_regrid_parcel(lat: float, lon: float, token: str) -> dict | None:
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


def fetch_regrid_nearby(lat: float, lon: float, token: str,
                        radius: int = 500, limit: int = 50) -> list[dict]:
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

def build_plat_section(loc: dict, parcel: dict | None,
                       nearby: list[dict]) -> str:
    lines: list[str] = []

    if parcel:
        lines.append("### 📋 Parcel Record (Regrid)")
        lines.append("")
        field_labels = {
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
        for key, label in field_labels.items():
            val = parcel.get(key)
            if val and str(val).strip() and str(val).strip().lower() not in ("none", "null", "0"):
                lines.append(f"- **{label}:** {val}")
        lines.append("")
    else:
        lines.append(
            "⚠️ *No Regrid API key configured — parcel-level data unavailable. "
            "Add `REGRID_API_KEY` in Settings → Secrets for APN, subdivision, "
            "legal description, zoning, and assessed values.*"
        )
        lines.append("")

    if nearby:
        subdivisions = set()
        for p in nearby:
            sd = p.get("subdivision")
            if sd and str(sd).strip().lower() not in ("", "none", "null"):
                subdivisions.add(str(sd).strip())
        if subdivisions:
            lines.append("### 🏘️ Subdivisions in this Neighbourhood")
            lines.append("")
            lines.append(
                f"**{len(subdivisions)}** named subdivision(s) within ~500 m:"
            )
            lines.append("")
            for sd in sorted(subdivisions):
                lines.append(f"- {sd}")
            lines.append("")

        zoning_types = set()
        for p in nearby:
            z = p.get("zoning") or p.get("zoning_description")
            if z and str(z).strip().lower() not in ("", "none", "null"):
                zoning_types.add(str(z).strip())
        if zoning_types:
            lines.append("**Zoning nearby:** " + ", ".join(sorted(zoning_types)))
            lines.append("")

    # County recorder resources
    lines.append("### 🗺️ County Recorder & Plat Resources")
    lines.append("")
    county = loc["county"]
    state = loc["state"]
    recorder_q = quote_plus(f"{county} {state} recorder plat map search")
    lines.append(f"- [**{county} Recorder — Plat Maps**](https://www.google.com/search?q={recorder_q})")
    gis_q = quote_plus(f"{county} {state} GIS parcel viewer")
    lines.append(f"- [**{county} GIS / Parcel Viewer**](https://www.google.com/search?q={gis_q})")
    lines.append(
        f"- [**Regrid Interactive Map**]"
        f"(https://app.regrid.com/us#{loc['lat']:.5f}/{loc['lon']:.5f}/17)"
    )
    lines.append("- [**USGS National Map**](https://apps.nationalmap.gov/viewer/)")

    subdiv_name = parcel.get("subdivision", "") if parcel else ""
    if subdiv_name:
        sd_q = quote_plus(f'"{subdiv_name}" plat {county} {state}')
        lines.append(f'- [**Search plat for "{subdiv_name}"**](https://www.google.com/search?q={sd_q})')

    lines.append("")
    lines.append(
        "> **Tip:** Plats are filed by book/page with the county recorder. "
        "Use the Book/Page from the parcel record above to pull the exact document."
    )
    return "\n".join(lines)


def build_infrastructure_section(loc: dict) -> str:
    lines: list[str] = []
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
    lines.append(f"- [**Active road projects near {city or county}**](https://www.google.com/search?q={pq})")

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
        f"- [**FCC Broadband Map**]"
        f"(https://broadbandmap.fcc.gov/location-summary/fixed"
        f"?speed=25_3&latlon={loc['lat']:.5f},{loc['lon']:.5f})"
    )
    lines.append(
        f"- [**FEMA Flood Map**]"
        f"(https://msc.fema.gov/portal/search?AddressQuery="
        f"{quote_plus(loc['display'])})"
    )
    lines.append("- [**FHWA National Highway Maps**](https://www.fhwa.dot.gov/planning/national_highway_system/nhs_maps/)")
    lines.append("- [**National Bridge Inventory**](https://www.fhwa.dot.gov/bridge/nbi.cfm)")

    lines.append("")
    lines.append(
        "> **For as-built drawings:** File a FOIA/public records request "
        "with the DOT district office or county engineer."
    )
    return "\n".join(lines)


def build_hoa_section(loc: dict, parcel: dict | None) -> str:
    lines: list[str] = []
    city = loc["city"]
    county = loc["county"]
    state = loc["state"]
    state_code = loc["state_code"]
    subdiv = (parcel.get("subdivision", "") or "") if parcel else ""

    attom_key = get_api_key("ATTOM_API_KEY")
    if attom_key:
        lines.append("### 🏘️ HOA Data (ATTOM)")
        lines.append("")
        headers = {"apikey": attom_key, "Accept": "application/json"}
        params = {
            "address1": loc.get("street_address") or loc["raw_input"],
            "address2": f"{city}, {state_code} {loc['zip_code']}",
        }
        resp = safe_get(
            "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/detail",
            params=params, headers=headers,
        )
        if resp:
            try:
                data = resp.json()
                prop = data.get("property", [{}])[0]
                hoa_fee = prop.get("assessment", {}).get("hoaFee")
                if hoa_fee:
                    lines.append(f"- **HOA Fee:** ${hoa_fee}/year")
                else:
                    lines.append("- No HOA fee on record.")
            except Exception:
                lines.append("- Could not parse ATTOM response.")
        else:
            lines.append("- ATTOM API request failed.")
        lines.append("")

    lines.append("### 🔎 HOA Lookup")
    lines.append("")
    if subdiv:
        hq = quote_plus(f'"{subdiv}" HOA homeowners association {city} {state}')
        lines.append(f'- [**Search HOA for "{subdiv}"**](https://www.google.com/search?q={hq})')
    aq = quote_plus(f"{loc['display']} HOA")
    lines.append(f"- [**Search HOA for this address**](https://www.google.com/search?q={aq})")
    sq = quote_plus(f"{state} secretary of state HOA nonprofit search")
    lines.append(f"- [**{state} SOS — HOA/Nonprofit Search**](https://www.google.com/search?q={sq})")

    lines.append("")
    lines.append("### 📋 Resources")
    lines.append("")
    lines.append(f"- **CC&Rs** are filed with the **{county} Recorder's Office**.")
    lines.append("- [HOA-USA Directory](https://www.hoa-usa.com/)")
    lines.append("- [Community Associations Institute](https://www.caionline.org/)")
    lines.append("- Zillow / Redfin / Realtor.com list HOA fees on property pages.")

    if not attom_key:
        lines.append("")
        lines.append(
            "> Add `ATTOM_API_KEY` for live HOA fee data. "
            "Get one at [api.gateway.attomdata.com](https://api.gateway.attomdata.com/)."
        )
    return "\n".join(lines)


def build_municipal_section(loc: dict) -> str:
    lines: list[str] = []
    city = loc["city"]
    county = loc["county"]
    state = loc["state"]
    state_code = loc["state_code"]
    fips = STATE_FIPS.get(state_code, "")

    lines.append("### 🏛️ Jurisdiction")
    lines.append("")
    lines.append(f"**City:** {city or '(unincorporated)'}")
    lines.append(f"**County:** {county}")
    lines.append(f"**State:** {state}")
    if loc["zip_code"]:
        lines.append(f"**ZIP:** {loc['zip_code']}")
    lines.append("")

    census_key = get_api_key("CENSUS_API_KEY")
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
    coq = quote_plus(f"{county} {state} county government website")
    lines.append(f"- [**{county} Government**](https://www.google.com/search?q={coq})")

    lines.append("")
    lines.append("### 🗂️ Zoning & Permits")
    lines.append("")
    zq = quote_plus(f"{city or county} {state} zoning map")
    lines.append(f"- [**Zoning Map**](https://www.google.com/search?q={zq})")
    pq = quote_plus(f"{city or county} {state} building permit office")
    lines.append(f"- [**Building Permits**](https://www.google.com/search?q={pq})")
    lines.append(
        f"- [**Regrid Zoning View**](https://app.regrid.com/us#{loc['lat']:.5f}/{loc['lon']:.5f}/17)"
    )

    lines.append("")
    lines.append("### 🔧 Public Works & Utilities")
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
    lines.append(f"- [**Fire Department**](https://www.google.com/search?q={fq})")
    lines.append(f"- [**Police (non-emergency)**](https://www.google.com/search?q={plq})")

    cf = quote_plus(county.lower().replace(" ", "") + state_code.lower())
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
        font-weight: 700 !important;
        color: #0f172a;
        border-bottom: 3px solid #f59e0b;
        padding-bottom: 0.3rem;
    }
    h2, h3 {
        font-family: 'IBM Plex Sans', sans-serif !important;
        color: #1e293b;
    }
    div[data-testid="stExpander"] {
        border: 1px solid #e2e8f0;
        border-left: 4px solid #f59e0b;
        border-radius: 6px;
        margin-bottom: 0.5rem;
    }
    div[data-testid="stExpander"] details summary p {
        font-size: 1.05rem;
        font-weight: 600;
        font-family: 'IBM Plex Sans', sans-serif;
    }
    .prop-card {
        background: #0f172a;
        color: #f8fafc;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.9rem;
        line-height: 1.7;
        margin-bottom: 1rem;
    }
    .prop-card strong { color: #fbbf24; }
    .api-badge {
        display: inline-block;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-left: 6px;
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

    # API status
    regrid_key = get_api_key("REGRID_API_KEY")
    census_key = get_api_key("CENSUS_API_KEY")
    attom_key = get_api_key("ATTOM_API_KEY")

    def badge(name, ok):
        cls = "on" if ok else "off"
        sym = "✓" if ok else "✗"
        return f'<span class="api-badge {cls}">{name} {sym}</span>'

    st.markdown(
        "**Data sources:** "
        + badge("Regrid", regrid_key)
        + badge("Census", census_key)
        + badge("ATTOM", attom_key)
        + " &nbsp;·&nbsp; Configure in Settings → Secrets",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # ── Input tabs ────────────────────────────────────────────────────────
    tab_addr, tab_coord = st.tabs(["📍 Address Search", "🌐 Coordinate Lookup"])

    loc = None
    search_triggered = False

    with tab_addr:
        st.markdown(
            "Type any US address below. Partial addresses work — "
            "you can enter a full street address, just a city and state, or even a ZIP code."
        )
        address_input = st.text_input(
            "Property address",
            placeholder="123 Main St, Anytown, CA 90210",
            key="addr_input",
            label_visibility="collapsed",
        )
        st.caption(
            "**Accepts:** `123 Main St, Anytown, CA 90210` · "
            "`123 Main St Anytown CA` · `Anytown, CA` · `90210`"
        )
        addr_btn = st.button(
            "🔍  Look Up Address", type="primary",
            use_container_width=True, key="btn_addr",
        )
        if addr_btn and address_input.strip():
            search_triggered = True
            with st.spinner("Resolving address…"):
                loc = geocode_address(address_input)

    with tab_coord:
        st.markdown(
            "Enter decimal latitude and longitude. "
            "The lookup resolves to the **nearest street address** and neighbourhood."
        )
        c1, c2 = st.columns(2)
        with c1:
            lat_in = st.text_input(
                "Latitude", placeholder="34.0522",
                help="Decimal degrees, positive = north. US range: ~24 to ~49.",
                key="lat_in",
            )
        with c2:
            lon_in = st.text_input(
                "Longitude", placeholder="-118.2437",
                help="Decimal degrees, negative = west. US range: ~-67 to ~-125.",
                key="lon_in",
            )
        st.caption(
            "**Examples:** Los Angeles `34.0522, -118.2437` · "
            "Miami `25.7617, -80.1918` · Seattle `47.6062, -122.3321`"
        )
        coord_btn = st.button(
            "🔍  Look Up Coordinates", type="primary",
            use_container_width=True, key="btn_coord",
        )
        if coord_btn:
            search_triggered = True
            try:
                lat_v = float(lat_in.strip())
                lon_v = float(lon_in.strip())
            except (ValueError, AttributeError):
                st.error("Enter valid decimal numbers for both latitude and longitude.")
                return
            if not (-90 <= lat_v <= 90) or not (-180 <= lon_v <= 180):
                st.error("Coordinates out of range.")
                return
            with st.spinner("Reverse-geocoding to nearest address…"):
                loc = reverse_geocode(lat_v, lon_v)

    if not search_triggered:
        return

    if loc is None:
        st.error("Could not resolve a valid US location. Check your input and try again.")
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

    # ── Regrid data ───────────────────────────────────────────────────────
    parcel = None
    nearby = []
    if regrid_key:
        with st.spinner("Querying Regrid for parcel & subdivision data…"):
            parcel = fetch_regrid_parcel(loc["lat"], loc["lon"], regrid_key)
            nearby = fetch_regrid_nearby(loc["lat"], loc["lon"], regrid_key)

    # ── Result sections ───────────────────────────────────────────────────
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
        "**Disclaimer:** This tool aggregates publicly available parcel data "
        "and links to government portals. Not a substitute for a legal survey "
        "or title search. Verify with the relevant county office."
    )


if __name__ == "__main__":
    main()

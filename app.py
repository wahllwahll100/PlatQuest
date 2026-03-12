#!/usr/bin/env python3
"""
US Public Records Location Search Engine
=========================================
A Streamlit web app that retrieves location-specific public records
for any US address or coordinates.

Setup:
    pip install streamlit geopy requests beautifulsoup4

Run:
    streamlit run app.py

Optional API Keys (set as environment variables or in Streamlit secrets):
    - CENSUS_API_KEY: For US Census Bureau data (free at https://api.census.gov/data/key_signup.html)
    - GEOAPIFY_API_KEY: For places/POI data (free tier at https://www.geoapify.com/)
    - ATTOM_API_KEY: For HOA/property data (paid, https://api.gateway.attomdata.com/)

Without API keys the app uses publicly available data and constructed
links to official county/state portals.
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

APP_TITLE = "US Public Records Search"
APP_ICON = "🏛️"
USER_AGENT = "USPublicRecordsSearch/1.0 (educational-project)"
REQUEST_TIMEOUT = 10
SCRAPE_DELAY = 1.0  # seconds between requests – be polite

# State FIPS codes for Census API lookups
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

# Common county recorder URL patterns (expandable)
COUNTY_RECORDER_PATTERNS = {
    "CA": "https://www.{county_slug}clerk.com/",
    "FL": "https://www.{county_slug}clerk.com/",
    "TX": "https://www.{county_slug}countyclerk.com/",
    "NY": "https://www.{county_slug}countyclerk.com/",
}

# State DOT websites
STATE_DOT_URLS = {
    "AL": "https://www.dot.state.al.us/",
    "AK": "https://dot.alaska.gov/",
    "AZ": "https://azdot.gov/",
    "AR": "https://www.ardot.gov/",
    "CA": "https://dot.ca.gov/",
    "CO": "https://www.codot.gov/",
    "CT": "https://portal.ct.gov/dot",
    "DE": "https://deldot.gov/",
    "FL": "https://www.fdot.gov/",
    "GA": "https://www.dot.ga.gov/",
    "HI": "https://hidot.hawaii.gov/",
    "ID": "https://itd.idaho.gov/",
    "IL": "https://idot.illinois.gov/",
    "IN": "https://www.in.gov/indot/",
    "IA": "https://iowadot.gov/",
    "KS": "https://www.ksdot.gov/",
    "KY": "https://transportation.ky.gov/",
    "LA": "https://www.dotd.la.gov/",
    "ME": "https://www.maine.gov/mdot/",
    "MD": "https://www.roads.maryland.gov/",
    "MA": "https://www.mass.gov/orgs/massachusetts-department-of-transportation",
    "MI": "https://www.michigan.gov/mdot",
    "MN": "https://www.dot.state.mn.us/",
    "MS": "https://mdot.ms.gov/",
    "MO": "https://www.modot.org/",
    "MT": "https://www.mdt.mt.gov/",
    "NE": "https://dot.nebraska.gov/",
    "NV": "https://www.dot.nv.gov/",
    "NH": "https://www.nh.gov/dot/",
    "NJ": "https://www.nj.gov/transportation/",
    "NM": "https://www.dot.nm.gov/",
    "NY": "https://www.dot.ny.gov/",
    "NC": "https://www.ncdot.gov/",
    "ND": "https://www.dot.nd.gov/",
    "OH": "https://www.transportation.ohio.gov/",
    "OK": "https://oklahoma.gov/odot.html",
    "OR": "https://www.oregon.gov/odot/",
    "PA": "https://www.penndot.pa.gov/",
    "RI": "https://www.dot.ri.gov/",
    "SC": "https://www.scdot.org/",
    "SD": "https://dot.sd.gov/",
    "TN": "https://www.tn.gov/tdot.html",
    "TX": "https://www.txdot.gov/",
    "UT": "https://www.udot.utah.gov/",
    "VT": "https://vtrans.vermont.gov/",
    "VA": "https://www.virginiadot.org/",
    "WA": "https://wsdot.wa.gov/",
    "WV": "https://transportation.wv.gov/",
    "WI": "https://wisconsindot.gov/",
    "WY": "https://www.dot.state.wy.us/",
    "DC": "https://ddot.dc.gov/",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_api_key(name: str) -> str | None:
    """Retrieve an API key from Streamlit secrets or env vars."""
    try:
        return st.secrets.get(name)
    except Exception:
        pass
    return os.environ.get(name)


def safe_request(url: str, params: dict | None = None,
                 headers: dict | None = None, timeout: int = REQUEST_TIMEOUT) -> requests.Response | None:
    """Make a GET request with error handling and polite delay."""
    time.sleep(SCRAPE_DELAY)
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp
    except requests.RequestException:
        pass
    return None


def parse_input(raw: str) -> dict | None:
    """
    Parse user input as either coordinates or an address.
    Returns dict with keys: lat, lon, address, city, county, state, state_code, zip_code
    or None on failure.
    """
    raw = raw.strip()
    if not raw:
        return None

    geolocator = Nominatim(user_agent=USER_AGENT, timeout=10)

    # Check for coordinate input  (lat, lon)
    coord_match = re.match(
        r'^([+-]?\d{1,3}(?:\.\d+)?)\s*[,\s]\s*([+-]?\d{1,3}(?:\.\d+)?)$', raw
    )

    try:
        if coord_match:
            lat, lon = float(coord_match.group(1)), float(coord_match.group(2))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return None
            location = geolocator.reverse(f"{lat}, {lon}", exactly_one=True,
                                          language="en", addressdetails=True)
            if not location:
                return None
            addr = location.raw.get("address", {})
        else:
            # Treat as address string – append USA if not present
            query = raw if re.search(r'\bUS(A)?\b', raw, re.I) else raw + ", USA"
            location = geolocator.geocode(query, exactly_one=True,
                                          language="en", addressdetails=True,
                                          countrycodes="us")
            if not location:
                return None
            lat, lon = location.latitude, location.longitude
            addr = location.raw.get("address", {})

        country_code = addr.get("country_code", "")
        if country_code != "us":
            return None

        state_code = addr.get("ISO3166-2-lvl4", "")
        if state_code.startswith("US-"):
            state_code = state_code[3:]

        # Fallback: try to derive state_code from state name
        if not state_code:
            state_name = addr.get("state", "")
            for code, name in STATE_NAMES.items():
                if name.lower() == state_name.lower():
                    state_code = code
                    break

        city = (addr.get("city") or addr.get("town") or addr.get("village")
                or addr.get("hamlet") or addr.get("municipality") or "")
        county = addr.get("county", "")

        return {
            "lat": lat,
            "lon": lon,
            "display": location.address,
            "address": raw,
            "city": city,
            "county": county,
            "state": addr.get("state", ""),
            "state_code": state_code,
            "zip_code": addr.get("postcode", ""),
        }

    except (GeocoderTimedOut, GeocoderUnavailable):
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data‑fetching functions
# ---------------------------------------------------------------------------

def fetch_plat_data(loc: dict) -> str:
    """
    Build links and information about development / neighborhood plats,
    subdivision details, or development plans.
    """
    county = loc["county"]
    state_code = loc["state_code"]
    city = loc["city"]
    lines: list[str] = []

    county_clean = county.replace(" County", "").replace(" Parish", "").strip()
    county_slug = county_clean.lower().replace(" ", "")

    # 1. County recorder / clerk links
    lines.append("### 🗺️ County Recorder / Clerk Resources")
    lines.append("")

    # Generic county search links
    search_query = quote_plus(f"{county} {loc['state']} plat maps recorder")
    lines.append(
        f"- **[Search for {county} Plat Maps]"
        f"(https://www.google.com/search?q={search_query})** – "
        f"Google search for official county recorder plat records"
    )

    # State-specific recorder pattern
    if state_code in COUNTY_RECORDER_PATTERNS:
        recorder_url = COUNTY_RECORDER_PATTERNS[state_code].format(
            county_slug=county_slug
        )
        lines.append(f"- **Possible County Clerk Portal:** [{recorder_url}]({recorder_url})")

    # 2. Subdivision / development plan links
    lines.append("")
    lines.append("### 📐 Subdivision & Development Plans")
    lines.append("")

    if city:
        city_query = quote_plus(f"{city} {loc['state']} subdivision plat map site:.gov")
        lines.append(
            f"- **[{city} Subdivision Records (gov sites)]"
            f"(https://www.google.com/search?q={city_query})**"
        )

    county_dev_query = quote_plus(
        f"{county} {loc['state']} development plan zoning map"
    )
    lines.append(
        f"- **[{county} Development / Zoning Plans]"
        f"(https://www.google.com/search?q={county_dev_query})**"
    )

    # 3. USGS / National Map
    lines.append("")
    lines.append("### 🌐 National Mapping Resources")
    lines.append("")
    lines.append(
        f"- **[USGS National Map Viewer]"
        f"(https://apps.nationalmap.gov/viewer/)** – "
        f"View topographic and parcel data near ({loc['lat']:.4f}, {loc['lon']:.4f})"
    )
    lines.append(
        f"- **[Census TIGER/Line Shapefiles]"
        f"(https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html)** – "
        f"Download boundary and road shapefiles for {county}"
    )

    # 4. Regrid / parcel data (free viewer)
    lines.append(
        f"- **[Regrid Parcel Map]"
        f"(https://app.regrid.com/us#{loc['lat']:.5f}/{loc['lon']:.5f}/16)** – "
        f"Interactive parcel boundaries and ownership data"
    )

    lines.append("")
    lines.append(
        "> **Note:** Plat maps are typically maintained by the county recorder or "
        "clerk's office. Many counties now offer online portals to search recorded "
        "plats by subdivision name, book/page number, or address. Contact the "
        f"**{county} Recorder's Office** directly for certified copies."
    )

    return "\n".join(lines)


def fetch_infrastructure_data(loc: dict) -> str:
    """
    Retrieve links and info about road infrastructure, engineering drawings,
    and DOT resources.
    """
    state_code = loc["state_code"]
    county = loc["county"]
    city = loc["city"]
    lines: list[str] = []

    # 1. State DOT
    dot_url = STATE_DOT_URLS.get(state_code, "")
    state_name = STATE_NAMES.get(state_code, loc["state"])

    lines.append("### 🚧 State Department of Transportation")
    lines.append("")
    if dot_url:
        lines.append(f"- **[{state_name} DOT Official Site]({dot_url})**")
    lines.append(
        f"- **[{state_name} DOT Road Projects]"
        f"(https://www.google.com/search?q={quote_plus(state_name + ' DOT road projects map')})** – "
        f"Search for active and planned projects"
    )

    # 2. FHWA / National Highway System
    lines.append("")
    lines.append("### 🛣️ Federal Highway Resources")
    lines.append("")
    lines.append(
        "- **[FHWA National Highway System Maps]"
        "(https://www.fhwa.dot.gov/planning/national_highway_system/nhs_maps/)** – "
        "Official NHS route maps by state"
    )
    lines.append(
        "- **[National Bridge Inventory]"
        "(https://www.fhwa.dot.gov/bridge/nbi.cfm)** – "
        "Structural data for bridges in the area"
    )

    # 3. Local public works / engineering
    lines.append("")
    lines.append("### 🏗️ Local Engineering & Public Works")
    lines.append("")

    if city:
        pw_query = quote_plus(f"{city} {state_name} public works engineering drawings")
        lines.append(
            f"- **[{city} Public Works / Engineering]"
            f"(https://www.google.com/search?q={pw_query})**"
        )

    county_eng_query = quote_plus(
        f"{county} {state_name} county engineer road plans"
    )
    lines.append(
        f"- **[{county} County Engineer / Road Plans]"
        f"(https://www.google.com/search?q={county_eng_query})**"
    )

    # 4. Utility / Infrastructure maps
    lines.append("")
    lines.append("### 📡 Utility & Infrastructure Maps")
    lines.append("")
    lines.append(
        "- **[National Pipeline Mapping System]"
        "(https://www.npms.phmsa.dot.gov/)** – "
        "Gas & hazardous‑liquid pipeline locations"
    )
    lines.append(
        "- **[FCC Broadband Map]"
        "(https://broadbandmap.fcc.gov/location-summary/fixed?speed=25_3&latlon="
        f"{loc['lat']:.5f},{loc['lon']:.5f})** – "
        "Internet infrastructure at this location"
    )

    lines.append("")
    lines.append(
        "> **Note:** Detailed engineering drawings for public roads are usually "
        "available through Public Records Requests (FOIA) to the relevant DOT "
        "district office or county engineer. Many states also publish as‑built "
        "drawings on their online plan rooms."
    )

    return "\n".join(lines)


def fetch_hoa_data(loc: dict) -> str:
    """
    Attempt to retrieve HOA details. Uses ATTOM API if key available,
    otherwise provides research links and guidance.
    """
    lines: list[str] = []
    city = loc["city"]
    county = loc["county"]
    state_name = STATE_NAMES.get(loc["state_code"], loc["state"])
    attom_key = get_api_key("ATTOM_API_KEY")

    if attom_key:
        # ------- ATTOM Property API (paid) -------
        lines.append("### 🏘️ HOA Data (via ATTOM Property API)")
        lines.append("")
        headers = {"apikey": attom_key, "Accept": "application/json"}
        params = {"address1": loc["address"], "address2": f"{city}, {loc['state_code']} {loc['zip_code']}"}
        resp = safe_request(
            "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/detail",
            params=params, headers=headers
        )
        if resp:
            try:
                data = resp.json()
                prop = data.get("property", [{}])[0]
                hoa = prop.get("assessment", {})
                hoa_fee = hoa.get("hoaFee")
                if hoa_fee:
                    lines.append(f"- **HOA Fee:** ${hoa_fee}/year")
                else:
                    lines.append("- HOA fee data not available for this property.")
                lines.append("")
                lines.append(
                    "> Data sourced from ATTOM Data Solutions. Contact HOA "
                    "management company directly for rules and bylaws."
                )
            except Exception:
                lines.append("- ⚠️ Could not parse ATTOM response.")
        else:
            lines.append("- ⚠️ ATTOM API request failed. Check your API key.")
    else:
        # ------- No API key – provide research links -------
        lines.append("### 🏘️ HOA Lookup Resources")
        lines.append("")
        lines.append(
            "No ATTOM API key configured. Below are resources to find HOA "
            "information for this property:"
        )
        lines.append("")

        # HOA search links
        addr_query = quote_plus(f"{loc['address']} HOA homeowners association")
        lines.append(
            f"- **[Search for this property's HOA]"
            f"(https://www.google.com/search?q={addr_query})**"
        )
        if city:
            city_hoa = quote_plus(f"{city} {state_name} HOA directory")
            lines.append(
                f"- **[{city} HOA Directory]"
                f"(https://www.google.com/search?q={city_hoa})**"
            )

        # Common HOA registries by state
        lines.append("")
        lines.append("**State HOA Registry / Filing Search:**")
        sos_query = quote_plus(
            f"{state_name} secretary of state HOA corporation search"
        )
        lines.append(
            f"- **[{state_name} Secretary of State – Business Search]"
            f"(https://www.google.com/search?q={sos_query})** – "
            f"HOAs are often registered as nonprofits"
        )

    # General resources (always show)
    lines.append("")
    lines.append("### 📋 General HOA Research Tips")
    lines.append("")
    lines.append(
        "- **Title / Deed Search:** HOA covenants (CC&Rs) are recorded with the "
        f"county deed records. Check the **{county} Recorder's Office**."
    )
    lines.append(
        "- **Real Estate Listing Sites:** Zillow, Redfin, and Realtor.com often "
        "list HOA fees and management company names on property pages."
    )
    lines.append(
        "- **Management Company Databases:**\n"
        "  - [HOA-USA Directory](https://www.hoa-usa.com/)\n"
        "  - [Community Associations Institute](https://www.caionline.org/)"
    )

    lines.append("")
    lines.append(
        "> **To set up ATTOM API access:** Get a key at "
        "[api.gateway.attomdata.com](https://api.gateway.attomdata.com/) and add "
        "it as `ATTOM_API_KEY` in your Streamlit secrets or environment variables."
    )

    return "\n".join(lines)


def fetch_municipal_data(loc: dict) -> str:
    """
    Retrieve municipal / city / county government details.
    Uses Census API for demographics, constructs links for government contacts.
    """
    city = loc["city"]
    county = loc["county"]
    state_code = loc["state_code"]
    state_name = STATE_NAMES.get(state_code, loc["state"])
    fips = STATE_FIPS.get(state_code, "")
    lines: list[str] = []

    # ----- Census API (basic demographic context) -----
    census_key = get_api_key("CENSUS_API_KEY")
    lines.append("### 🏛️ Municipal Government")
    lines.append("")

    if city:
        lines.append(f"**City / Town:** {city}")
    lines.append(f"**County:** {county}")
    lines.append(f"**State:** {state_name}")
    if loc["zip_code"]:
        lines.append(f"**ZIP Code:** {loc['zip_code']}")
    lines.append("")

    # Census population data
    if fips and census_key:
        try:
            census_url = "https://api.census.gov/data/2022/acs/acs5"
            params = {
                "get": "NAME,B01003_001E",
                "for": "county:*",
                "in": f"state:{fips}",
                "key": census_key,
            }
            resp = safe_request(census_url, params=params)
            if resp:
                rows = resp.json()
                header = rows[0]
                county_clean = county.replace(" County", "").replace(" Parish", "").strip()
                for row in rows[1:]:
                    if county_clean.lower() in row[0].lower():
                        pop = int(row[1])
                        lines.append(f"**{county} Estimated Population (ACS 2022):** {pop:,}")
                        lines.append("")
                        break
        except Exception:
            pass

    # ----- Government contact links -----
    lines.append("### 📞 Government Contacts & Resources")
    lines.append("")

    if city:
        city_gov_query = quote_plus(f"{city} {state_name} city government official website")
        lines.append(
            f"- **[{city} Official City Website]"
            f"(https://www.google.com/search?q={city_gov_query})**"
        )
        mayor_query = quote_plus(f"{city} {state_name} mayor contact information")
        lines.append(
            f"- **[Mayor's Office – {city}]"
            f"(https://www.google.com/search?q={mayor_query})**"
        )

    county_gov_query = quote_plus(f"{county} {state_name} county government website")
    lines.append(
        f"- **[{county} Government Website]"
        f"(https://www.google.com/search?q={county_gov_query})**"
    )

    # Zoning
    lines.append("")
    lines.append("### 🗂️ Zoning & Land Use")
    lines.append("")
    zone_query = quote_plus(
        f"{city or county} {state_name} zoning map ordinance"
    )
    lines.append(
        f"- **[Zoning Map / Ordinance]"
        f"(https://www.google.com/search?q={zone_query})**"
    )
    lines.append(
        f"- **[Regrid Zoning Overlay]"
        f"(https://app.regrid.com/us#{loc['lat']:.5f}/{loc['lon']:.5f}/16)** – "
        "View parcel zoning designations"
    )

    # Public works / utilities
    lines.append("")
    lines.append("### 🔧 Public Works & Utilities")
    lines.append("")
    if city:
        pw_query = quote_plus(f"{city} {state_name} public works department contact")
        lines.append(
            f"- **[{city} Public Works]"
            f"(https://www.google.com/search?q={pw_query})**"
        )
    permit_query = quote_plus(
        f"{city or county} {state_name} building permit office"
    )
    lines.append(
        f"- **[Building Permits Office]"
        f"(https://www.google.com/search?q={permit_query})**"
    )

    # Emergency services
    lines.append("")
    lines.append("### 🚒 Emergency Services")
    lines.append("")
    fire_query = quote_plus(f"{city or county} {state_name} fire department")
    police_query = quote_plus(f"{city or county} {state_name} police department non-emergency")
    lines.append(
        f"- **[Fire Department]"
        f"(https://www.google.com/search?q={fire_query})**"
    )
    lines.append(
        f"- **[Police – Non‑Emergency]"
        f"(https://www.google.com/search?q={police_query})**"
    )

    # SBA city/county data
    lines.append("")
    lines.append("### 📊 Additional Municipal Data")
    lines.append("")
    lines.append(
        f"- **[Census QuickFacts – {county}]"
        f"(https://www.census.gov/quickfacts/{quote_plus(county.lower().replace(' ', '') + state_code.lower())})** – "
        "Population, income, housing stats"
    )
    lines.append(
        "- **[USA.gov Local Government]"
        "(https://www.usa.gov/local-governments)** – "
        "Directory of local government offices"
    )

    lines.append("")
    lines.append(
        "> **Tip:** Most municipalities publish meeting agendas, budgets, and "
        "ordinances on their official websites. Many also offer 311 services "
        "for non‑emergency questions."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def set_page_style():
    """Apply custom CSS for a clean, professional look."""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Playfair+Display:wght@700&display=swap');

    .block-container {
        max-width: 860px;
        padding-top: 2rem;
    }
    h1 {
        font-family: 'Playfair Display', serif !important;
        color: #1a2744;
        border-bottom: 3px solid #2563eb;
        padding-bottom: 0.4rem;
    }
    h2, h3 {
        font-family: 'Source Sans 3', sans-serif !important;
        color: #1e3a5f;
    }
    .stExpander {
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        margin-bottom: 0.5rem;
    }
    div[data-testid="stExpander"] details summary p {
        font-size: 1.1rem;
        font-weight: 600;
    }
    .loc-badge {
        background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
        color: white;
        padding: 0.8rem 1.2rem;
        border-radius: 8px;
        font-family: 'Source Sans 3', sans-serif;
        margin-bottom: 1rem;
        line-height: 1.6;
    }
    .loc-badge strong { color: #93c5fd; }
    </style>
    """, unsafe_allow_html=True)


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="centered")
    set_page_style()

    st.title(f"{APP_ICON} {APP_TITLE}")
    st.markdown(
        "Enter a **US address** or **latitude, longitude** to look up public "
        "records including plat maps, infrastructure data, HOA details, and "
        "municipal government information."
    )

    # -- Input --
    user_input = st.text_input(
        "Address or Coordinates",
        placeholder='e.g. "123 Main St, Anytown, CA 90210" or "34.0522, -118.2437"',
    )

    search_clicked = st.button("🔍  Search", type="primary", use_container_width=True)

    if not search_clicked:
        st.caption(
            "Supported: US street addresses, city/state, or decimal coordinates."
        )
        return

    # -- Geocode --
    with st.spinner("Geocoding location…"):
        loc = parse_input(user_input)

    if loc is None:
        st.error(
            "❌ Could not resolve a valid US location from your input. "
            "Please enter a US street address or coordinates within the US."
        )
        return

    # -- Show resolved location --
    st.markdown(
        f'<div class="loc-badge">'
        f'📍 <strong>Resolved Location:</strong> {loc["display"]}<br>'
        f'<strong>Coordinates:</strong> {loc["lat"]:.5f}, {loc["lon"]:.5f} · '
        f'<strong>County:</strong> {loc["county"]} · '
        f'<strong>State:</strong> {loc["state"]}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # -- Sections --
    with st.expander("🗺️  Development / Neighborhood Plats", expanded=True):
        with st.spinner("Fetching plat data…"):
            st.markdown(fetch_plat_data(loc))

    with st.expander("🛣️  Infrastructure Plats & Road Engineering", expanded=True):
        with st.spinner("Fetching infrastructure data…"):
            st.markdown(fetch_infrastructure_data(loc))

    with st.expander("🏘️  HOA Details", expanded=True):
        with st.spinner("Fetching HOA data…"):
            st.markdown(fetch_hoa_data(loc))

    with st.expander("🏛️  Municipal Details & Contacts", expanded=True):
        with st.spinner("Fetching municipal data…"):
            st.markdown(fetch_municipal_data(loc))

    # -- Footer --
    st.divider()
    st.caption(
        "**Disclaimer:** This tool aggregates links to publicly available records "
        "and government portals. It does not guarantee accuracy or completeness. "
        "Always verify information with the relevant government office. "
        "No personal or sensitive data is collected or stored."
    )


if __name__ == "__main__":
    main()

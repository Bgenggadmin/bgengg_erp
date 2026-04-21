"""
Asset loader — fetches brand images from Supabase public storage bucket.

Bucket: progress-photos (public)
Assets: logo.png (and potentially tagline.png / hero.png in the future)

Usage:
    from bg_offer_generator.utils.assets import load_brand_assets
    logo_bytes, tagline_bytes, hero_bytes = load_brand_assets()
"""
import streamlit as st
from typing import Optional, Tuple


# Public URL pattern for Supabase storage
_BUCKET = "progress-photos"
_ASSET_FILES = {
    "logo":     "logo.png",
    "tagline":  "tagline.png",        # may not exist yet — handled gracefully
    "hero":     "hero.png",           # may not exist yet — handled gracefully
}


def _get_supabase_url() -> Optional[str]:
    """Get the Supabase project URL from secrets.
    Supports both [supabase] section and [connections.supabase] (st_supabase_connection)."""
    try:
        # Try st_supabase_connection style first (used by your ERP)
        if "connections" in st.secrets and "supabase" in st.secrets["connections"]:
            url = st.secrets["connections"]["supabase"].get("SUPABASE_URL")
            if url:
                return url.rstrip("/")
        # Fallback: plain [supabase] section
        if "supabase" in st.secrets:
            url = st.secrets["supabase"].get("url") or st.secrets["supabase"].get("SUPABASE_URL")
            if url:
                return url.rstrip("/")
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asset_bytes(filename: str) -> Optional[bytes]:
    """Download an asset from the public Supabase bucket; returns None on failure."""
    import requests
    base = _get_supabase_url()
    if not base:
        return None
    url = f"{base}/storage/v1/object/public/{_BUCKET}/{filename}"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None


def load_brand_assets() -> Tuple[Optional[bytes], Optional[bytes], Optional[bytes]]:
    """
    Load (logo, tagline, hero) image bytes from Supabase.
    Any asset missing returns None — DOCX generator handles None gracefully.
    """
    logo = fetch_asset_bytes(_ASSET_FILES["logo"])
    tagline = fetch_asset_bytes(_ASSET_FILES["tagline"])
    hero = fetch_asset_bytes(_ASSET_FILES["hero"])
    return logo, tagline, hero

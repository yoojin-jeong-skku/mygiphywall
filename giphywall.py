from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import uuid4

import streamlit as st


st.set_page_config(page_title="Giphy Stack", layout="centered")

DATA_FILE = Path("data/gifs.json")


def _ensure_protocol(url: str) -> str:
    """Prefix urls without a scheme so urlparse works consistently."""
    url = url.strip()
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://{url}"
    return url


def extract_gif_id(raw_url: str) -> Optional[str]:
    """Return the Giphy media id from any standard Giphy URL."""
    if not raw_url:
        return None

    normalized = _ensure_protocol(raw_url)
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    if not path:
        return None

    slug = path.split("/")[-1]
    # For slugs like keyword-keyword-<id>, grab the literal id portion.
    if "-" in slug:
        slug = slug.split("-")[-1]

    match = re.search(r"([A-Za-z0-9]+)$", slug)
    if not match:
        return None
    return match.group(1)


def load_gifs_from_disk() -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        return []

    try:
        with DATA_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            if isinstance(payload, list):
                return payload
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_gifs_to_disk(gifs: list[dict[str, Any]]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as handle:
        json.dump(gifs, handle, ensure_ascii=True, indent=2)


def add_gif_to_state(gif_id: str, source_url: str) -> None:
    st.session_state.gifs.insert(
        0,
        {
            "uuid": uuid4().hex,
            "gif_id": gif_id,
            "embed_url": f"https://giphy.com/embed/{gif_id}",
            "source_url": source_url,
        },
    )
    save_gifs_to_disk(st.session_state.gifs)


def delete_gif_from_state(uuid: str) -> None:
    st.session_state.gifs = [gif for gif in st.session_state.gifs if gif["uuid"] != uuid]
    save_gifs_to_disk(st.session_state.gifs)


if "gifs" not in st.session_state:
    st.session_state.gifs = load_gifs_from_disk()


st.title("My Giphy Wall")
st.caption("Paste any Giphy link to pile it on the wall. Newest gifs show up first.")

st.markdown(
    """
    <style>
        body, div[data-testid="stAppViewContainer"] {
            background-color: #000000;
            color: #f0f0f0;
        }
        div[data-testid="stForm"] { width: min(600px, 90vw); margin: 0 auto; }
        div[data-testid="stTextInput"] input {
            border-radius: 999px;
            padding: 0.8rem 1.2rem;
            font-size: 1rem;
        }
        .giphy-card {
            width: min(50vw, 520px);
            margin: 0 auto 1.5rem auto;
            padding: 0.5rem 0.5rem 1rem;
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.04);
            box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
        }
        .giphy-card iframe {
            width: 100%;
            min-height: 320px;
            border: none;
            border-radius: 16px;
        }
        button[kind="secondary"] {
            width: 100%;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.form("add-giphy"):
    gif_url = st.text_input(
        "Paste a Giphy link",
        placeholder="https://giphy.com/gifs/...",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("Add Giphy")

if submitted:
    gif_id = extract_gif_id(gif_url)
    if gif_id:
        add_gif_to_state(gif_id, _ensure_protocol(gif_url))
        st.success("Giphy added.")
        st.rerun()
    else:
        st.error("Hmm, that link doesn't look like a valid Giphy URL.")

if st.session_state.gifs:
    for gif in st.session_state.gifs:
        with st.container():
            st.markdown(
                f"""
                <div class="giphy-card">
                    <iframe
                        src="{gif['embed_url']}"
                        title="Giphy {gif['gif_id']}"
                        allowfullscreen
                    ></iframe>
                </div>
                """,
                unsafe_allow_html=True,
            )
            delete = st.button("Delete", key=f"delete_{gif['uuid']}")
            if delete:
                delete_gif_from_state(gif["uuid"])
                st.rerun()
else:
    st.info("No gifs yet. Drop your first link above!")

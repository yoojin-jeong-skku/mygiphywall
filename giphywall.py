from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import uuid4

import streamlit as st
import base64
import random

# Support running as a package or a script: prefer relative import when possible,
# but fall back to a direct import if the module is executed as __main__.
try:
    from . import giphy_db
except Exception:
    import giphy_db


st.set_page_config(page_title="Giphy Stack", layout="centered")

BASE_DIR = Path(__file__).parent
STYLES_DIR = BASE_DIR / "styles"

# initialize DB file alongside this module by default
giphy_db.init_db()

REACTION_OPTIONS = [
    {"key": "doge", "label": "Such wow", "color": "#f5c542"},
    {"key": "pocket", "label": "Tiny wow", "color": "#76d96b"},
    {"key": "boop", "label": "Boop of wow", "color": "#4cd4ff"},
]


def safe_rerun() -> None:
    """Attempt to rerun the Streamlit app in a safe way.

    Some Streamlit environments may not expose `st.experimental_rerun`. Use
    this helper to avoid AttributeError: if rerun isn't available we set a
    session flag and call `st.stop()` to halt rendering.
    """
    try:
        if hasattr(st, "experimental_rerun"):
            st.experimental_rerun()
            return
    except Exception:
        # fall through to fallback
        pass

    try:
        st.session_state["_rerun_needed"] = True
        st.stop()
    except Exception:
        # last-resort: do nothing
        return

# Simple local login configuration: no external provider required.
# This displays a small sign-in form in the sidebar. Users are stored
# locally in the `users` table; we store a `login_identifier` field to
# record an external or local identifier.


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


def build_thumbnail_url(gif_id: str) -> str:
    """Use Giphy's 200px-wide rendition to keep the wall lightweight."""
    return f"https://media.giphy.com/media/{gif_id}/200w.gif"


def load_local_gif_data_uri(filename: str) -> Optional[str]:
    """Return a base64 data URI for a gif under doges/ or ../doges/."""
    candidates = [
        BASE_DIR / "doges" / filename,
        BASE_DIR.parent / "doges" / filename,
    ]
    for path in candidates:
        try:
            if path.exists():
                b = path.read_bytes()
                return f"data:image/gif;base64,{base64.b64encode(b).decode('ascii')}"
        except Exception:
            continue
    return None


def load_gifs_from_db(owner_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Load gifs from the SQLite DB and normalize to the app's card format."""
    gifs: list[dict[str, Any]] = []
    try:
        if owner_id is not None:
            rows = giphy_db.list_giphies_for_user(owner_id)
        else:
            rows = []
        for r in rows:
            gif_id = r.get("giphy_id")
            thumbnail = r.get("thumbnail_url") or (build_thumbnail_url(gif_id) if gif_id else "")
            gifs.append(
                {
                    "uuid": r.get("uuid") or uuid4().hex,
                    "gif_id": gif_id,
                    "embed_url": f"https://giphy.com/embed/{gif_id}" if gif_id else None,
                    "thumbnail_url": thumbnail,
                    "source_url": r.get("giphy_url"),
                }
            )
    except Exception:
        # fail safe: return empty list
        gifs = []
    return gifs


def refresh_wall_gifs(owner_id: Optional[int]) -> None:
    """Populate session state with gifs belonging to the requested wall owner."""
    st.session_state["gifs"] = load_gifs_from_db(owner_id)
    st.session_state["_gifs_for_user_id"] = owner_id


def add_gif_to_state(gif_id: str, source_url: str) -> None:
    uid = uuid4().hex
    thumbnail = build_thumbnail_url(gif_id)
    uploaded_by = None
    user = st.session_state.get("user")
    if user and isinstance(user, dict):
        uploaded_by = user.get("id")
    try:
        giphy_db.add_giphy(
            uuid=uid,
            giphy_id=gif_id,
            giphy_url=source_url,
            thumbnail_url=thumbnail,
            uploaded_by=uploaded_by,
        )
    except Exception:
        pass
    refresh_wall_gifs(st.session_state.get("active_wall_user_id"))


def delete_gif_from_state(uuid: str) -> None:
    try:
        giphy_db.delete_giphy_by_uuid(uuid)
    except Exception:
        pass
    refresh_wall_gifs(st.session_state.get("active_wall_user_id"))


def inject_stylesheet(filename: str) -> None:
    """Load a CSS file from disk and inject it into the current Streamlit page."""
    css_path = STYLES_DIR / filename
    try:
        css = css_path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError):
        return
    except Exception:
        return
    st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)


def clear_session_and_logout() -> None:
    st.stop()


def render_reactions(active_wall_user_id: int) -> None:
    friend_counts = (
        st.session_state.get("friend_reactions", {}).get(active_wall_user_id, {})
        if isinstance(active_wall_user_id, int)
        else {}
    )
    st.markdown("#### React wow wow")
    max_gauge = max(5, max(friend_counts.values(), default=0))
    btn_cols = st.columns(len(REACTION_OPTIONS))
    for option, col in zip(REACTION_OPTIONS, btn_cols):
        with col:
            count = friend_counts.get(option["label"], 0)
            st.markdown("<div class='reaction-btn-wrap'>", unsafe_allow_html=True)
            if st.button(f"{option['label']} (+{count})", key=f"react_{active_wall_user_id}_{option['key']}"):
                counts = st.session_state.setdefault("friend_reactions", {})
                friend_counts = counts.setdefault(active_wall_user_id, {})
                friend_counts[option["label"]] = friend_counts.get(option["label"], 0) + 1
                st.session_state["friend_reactions"] = counts
                count = friend_counts[option["label"]]
                max_gauge = max(max_gauge, count)
            degrees = int(180 * min(1.0, count / max_gauge))
            gauge_html = f"""
            <div class='reaction-gauge'>
                <div class='rg-meter' style='background: conic-gradient({option['color']} 0deg {degrees}deg, rgba(255,255,255,0.08) {degrees}deg 180deg);'>
                    <div class='rg-cover'>{count}</div>
                </div>
                <div class='rg-label'>{option['label']}</div>
            </div>
            """
            st.markdown(gauge_html, unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)


def render_login_screen() -> None:
    try:
        doge_comment = giphy_db.generate_doge_comment(
            "welcome to the giphy wall lots of gifs dogs memes wow"
        )
    except Exception:
        doge_comment = "wow such login much welcome"

    inject_stylesheet("login.css")

    with st.container():
        st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
        doge_dir = BASE_DIR / "doges"
        doge_images: list[str] = []
        try:
            if doge_dir.exists() and doge_dir.is_dir():
                for p in sorted(doge_dir.iterdir()):
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                        try:
                            b = p.read_bytes()
                            uri = f"data:image/{p.suffix.lstrip('.')};base64,{base64.b64encode(b).decode('ascii')}"
                            doge_images.append(uri)
                        except Exception:
                            continue
        except Exception:
            doge_images = []

        slots = ["fd-1", "fd-2", "fd-3", "fd-4"]
        parts: list[str] = []
        if doge_images:
            for i, slot in enumerate(slots):
                src = doge_images[i] if i < len(doge_images) else doge_images[i % len(doge_images)]
                parts.append(
                    f"<img class='float-doge {slot}' src='{src}' alt='doge' style='border-radius:50%; object-fit:cover;' />"
                )
            fuzzy_positions = [
                (8, 6),
                (20, 10),
                (34, 18),
                (52, 8),
                (68, 14),
                (82, 20),
                (28, 6),
            ]
        else:
            doge_url = "https://pngimg.com/d/doge_meme_PNG112723.png"
            for slot in slots:
                parts.append(
                    f"<img class='float-doge {slot}' src='{doge_url}' alt='doge' style='border-radius:50%; object-fit:cover; pointer-events:none;' />"
                )
            fuzzy_positions = [
                (6, 4),
                (18, 12),
                (30, 20),
                (50, 6),
                (66, 16),
                (78, 22),
                (34, 10),
            ]
        for idx, (l, t) in enumerate(fuzzy_positions):
            size_class = "small" if idx % 2 == 0 else "xs"
            parts.append(
                f"<div class='fuzzy {size_class}' style='left:{l}%; top:{t}%; animation: floaty-small {6+idx%4}s ease-in-out {(idx%3)/2}s infinite;'></div>"
            )
        st.markdown("".join(parts), unsafe_allow_html=True)

        st.markdown('<div class="login-box">', unsafe_allow_html=True)
        st.markdown("<div class='login-title'>MUCH GIPHY WALL</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='login-sub'>{doge_comment}</div>", unsafe_allow_html=True)
        with st.form("login_full"):
            username = st.text_input("Username")
            email = st.text_input("Email")
            submit = st.form_submit_button("Enter, wow")
            if submit:
                uname = (username or "").strip() or None
                mail = (email or "").strip() or None
                try:
                    user_by_username = giphy_db.get_user_by_username(uname) if uname else None
                except Exception:
                    user_by_username = None
                try:
                    user_by_email = giphy_db.get_user_by_email(mail) if mail else None
                except Exception:
                    user_by_email = None

                conflict = (
                    user_by_username
                    and user_by_email
                    and user_by_username.get("id") != user_by_email.get("id")
                )
                if conflict:
                    st.warning(
                        "Such mismatch. Username and email belong to diff accounts. "
                        "Return with matching combo wow."
                    )
                    return
                uname_conflict = user_by_username and mail and user_by_username.get("email") and mail != user_by_username.get("email")
                mail_conflict = user_by_email and uname and user_by_email.get("username") and uname != user_by_email.get("username")
                if uname_conflict:
                    st.warning("Username tied to other email. Much taken.")
                    return
                if mail_conflict:
                    st.warning("Email tied to other username. Very claimed.")
                    return

                existing = user_by_username or user_by_email
                if existing:
                    login_identifier = (
                        existing.get("login_identifier")
                        or existing.get("external_id")
                        or existing.get("kakao_id")
                        or f"local:{uname or mail or uuid4().hex}"
                    )
                    sess_user = {
                        "login_identifier": login_identifier,
                        "username": existing.get("username") or uname,
                        "email": existing.get("email") or mail,
                        "id": existing.get("id"),
                    }
                else:
                    login_identifier = f"local:{uname or mail or uuid4().hex}"
                    local_id = giphy_db.create_user(
                        login_identifier=login_identifier,
                        username=uname,
                        display_name=uname,
                        profile_url=None,
                        email=mail,
                    )
                    sess_user = {
                        "login_identifier": login_identifier,
                        "username": uname,
                        "email": mail,
                        "id": local_id,
                    }

                st.session_state["user"] = sess_user
                st.session_state["_active_user_id"] = sess_user.get("id")
                st.session_state["active_wall_user_id"] = sess_user.get("id")
                st.session_state["wall_selector"] = sess_user.get("id")
                refresh_wall_gifs(sess_user.get("id"))
                safe_rerun()
        st.markdown("</div></div>", unsafe_allow_html=True)


def render_snow_overlay(count: int = 24) -> None:
    """Inject a playful falling snow overlay once per session."""
    flakes_html: list[str] = []
    flake_chars = ["❄", "❅", "❆"]
    for idx in range(count):
        left = round(random.uniform(0, 100), 2)
        delay = round(random.uniform(0, 10), 2)
        duration = round(random.uniform(6, 12), 2)
        size = round(random.uniform(0.8, 1.6), 2)
        flake = random.choice(flake_chars)
        flakes_html.append(
            f"<div class='giphy-snowflake' style='left:{left}%; animation-delay:{delay}s; animation-duration:{duration}s; font-size:{size}rem;'>{flake}</div>"
        )
    flakes_markup = "\n".join(flakes_html)
    snow_markup = f"""
    <div class='giphy-snowflakes' aria-hidden='true'>
        {flakes_markup}
    </div>
    """
    st.markdown(snow_markup, unsafe_allow_html=True)


inject_stylesheet("wall.css")
render_snow_overlay()

if "user" not in st.session_state or not st.session_state.get("user"):
    render_login_screen()
    st.stop()

if "user" in st.session_state and st.session_state.get("user"):
    user = st.session_state["user"]
    user_id = user.get("id")
    active_user_id = st.session_state.get("_active_user_id")
    if active_user_id != user_id:
        st.session_state["_active_user_id"] = user_id
        st.session_state["active_wall_user_id"] = user_id
        st.session_state["wall_selector"] = user_id
    if "active_wall_user_id" not in st.session_state or st.session_state.get("active_wall_user_id") is None:
        st.session_state["active_wall_user_id"] = user_id
    friends = giphy_db.list_friends(user_id) if user_id else []
    friend_lookup = {f.get("id"): f for f in friends if f.get("id")}
    active_wall_user_id = st.session_state.get("active_wall_user_id") or user_id
    if active_wall_user_id != user_id and active_wall_user_id not in friend_lookup:
        active_wall_user_id = user_id
        st.session_state["active_wall_user_id"] = user_id
    pending_requests = giphy_db.list_pending_friend_requests(user_id) if user_id else []
    sent_requests = giphy_db.list_sent_friend_requests(user_id) if user_id else []

    with st.sidebar:
        uname = user.get('username') or user.get('email') or 'user'
        # Single-column: kermit image, fun wording, username-as-button, then logout
        try:
            # Prefer local in-package doges/kermit.gif
            kermit_path = BASE_DIR / "doges" / "kermit.gif"
            kermit_uri = None
            if kermit_path.exists():
                b = kermit_path.read_bytes()
                kermit_uri = f"data:image/gif;base64,{base64.b64encode(b).decode('ascii')}"
            else:
                # also check a sibling ../doge/kermit.gif (user-provided path)
                alt = BASE_DIR.parent / "doge" / "kermit.gif"
                if alt.exists():
                    b = alt.read_bytes()
                    kermit_uri = f"data:image/gif;base64,{base64.b64encode(b).decode('ascii')}"
            if not kermit_uri:
                # fallback public Kermit GIF
                kermit_uri = "https://media.giphy.com/media/3o6ZtaO9BZHcOjmErm/giphy.gif"

            kermit_phrases = [
                "But that's none of my business...",
                "Sipping tea, much drama",
                "Why you do this?",
                "Such meme, very green",
                "This is fine (not really)",
                "Am I the drama?",
                "Keep calm and Kermit on",
            ]
            chosen = random.choice(kermit_phrases)

            kermit_html = f"""
            <div class='kermit-card'>
              <div class='kermit-avatar'>
                <img src='{kermit_uri}' alt='kermit' />
              </div>
              <div class='kermit-info'>
                <div class='kermit-status'>Much logged in, wow</div>
                <div class='kermit-user-btn'>
                  <button>{uname}</button>
                </div>
                <div class='kermit-phrase'>
                  <span>{chosen}</span>
                </div>
              </div>
            </div>
            """
            st.markdown(kermit_html, unsafe_allow_html=True)
        except Exception:
            # render a simple text fallback
            st.markdown(f"**Signed in as:** {uname}")

        if st.button("Logout (double-click wow)"):
            try:
                st.session_state.clear()
            except Exception:
                pass
            safe_rerun()
            st.stop()

        st.divider()
        st.subheader("Much Fren Zone")
        st.markdown("<div class='friend-zone-box'>", unsafe_allow_html=True)
        st.caption("Send fren req wow. Jump to buddy GIF wall, very share.")
        with st.form("friend-request", clear_on_submit=True):
            st.caption("Add fren")
            friend_query = st.text_input(
                "Add fren",
                placeholder="username or email wow",
                label_visibility="collapsed",
            )
            send_request = st.form_submit_button("Launch fren req", use_container_width=True)
            if send_request:
                query = (friend_query or "").strip()
                if not query:
                    st.warning("Need name/email for fren req. Such empty.")
                else:
                    target = giphy_db.find_user_by_identifier(query)
                    if not target:
                        st.warning("No fren found. Much search again.")
                    elif target.get("id") == user_id:
                        st.warning("That you! Mirror fren not allowed.")
                    else:
                        ok, msg = giphy_db.create_friend_request(user_id, target.get("id"))
                        if ok:
                            st.success(msg)
                        else:
                            st.warning(msg)

        friend_gif_name = "love.gif" if pending_requests else "lonely.gif"
        friend_gif_uri = load_local_gif_data_uri(friend_gif_name)
        if friend_gif_uri:
            st.markdown(
                f"""
                <div class="friend-gif-preview">
                    <img src="{friend_gif_uri}" alt="friend gif" />
                </div>
                """,
                unsafe_allow_html=True,
            )

        if pending_requests:
            st.markdown("**Pending fren pings**")
            for req in pending_requests:
                requester_label = req.get("requester_username") or req.get("requester_email") or f"User {req.get('requester_id')}"
                st.write(f"{requester_label} say \"pls fren?\"")
                acc_col, dec_col = st.columns(2)
                with acc_col:
                    if st.button("Much accept", key=f"accept_req_{req['id']}"):
                        ok, msg = giphy_db.respond_to_friend_request(req["id"], user_id, True)
                        if ok:
                            st.success("Much accepted wow.")
                        else:
                            st.warning(msg)
                with dec_col:
                    if st.button("Such decline", key=f"decline_req_{req['id']}"):
                        ok, msg = giphy_db.respond_to_friend_request(req["id"], user_id, False)
                        if ok:
                            st.info("Declined. Much boundaries.")
                        else:
                            st.warning(msg)
        else:
            st.caption("No pending fren pings. So lonely.")

        if sent_requests:
            st.markdown("**Sent fren pings**")
            for req in sent_requests:
                receiver_label = req.get("receiver_username") or req.get("receiver_email") or f"User {req.get('receiver_id')}"
                st.caption(f"Waiting on {receiver_label}")
        else:
            st.caption("No outgoing fren reqs right now.")
        st.markdown("</div>", unsafe_allow_html=True)

        friend_option_ids = [uid for uid in [user_id] + [f.get("id") for f in friends if f.get("id")] if uid is not None]
        if not friend_option_ids:
            friend_option_ids = [user_id]
        friend_labels: dict[int, str] = {}
        if user_id is not None:
            friend_labels[user_id] = "My wall"
        for f in friends:
            fid = f.get("id")
            if fid is None:
                continue
            label = f.get("username") or f.get("email") or f"Friend #{fid}"
            friend_labels[fid] = f"{label}'s wall"
        selector_value = st.session_state.get("wall_selector", user_id)
        if selector_value not in friend_option_ids:
            selector_value = user_id
        selected_wall = st.selectbox(
            "Viewing",
            friend_option_ids,
            format_func=lambda uid, mapping=friend_labels, me=user_id: (
                "My wall" if me is not None and uid == me else mapping.get(uid, f"Friend #{uid}")
            ),
            index=friend_option_ids.index(selector_value),
        )
        if selected_wall in friend_option_ids:
            st.session_state["wall_selector"] = selected_wall
            st.session_state["active_wall_user_id"] = selected_wall
            active_wall_user_id = selected_wall
        else:
            st.session_state["wall_selector"] = user_id
            st.session_state["active_wall_user_id"] = user_id
            active_wall_user_id = user_id

    if st.session_state.get("_gifs_for_user_id") != active_wall_user_id or "gifs" not in st.session_state:
        refresh_wall_gifs(active_wall_user_id)

    viewing_self = active_wall_user_id == user_id
    active_wall_user = user if viewing_self else friend_lookup.get(active_wall_user_id) or giphy_db.get_user_by_id(active_wall_user_id)
    wall_owner_label = (
        (active_wall_user or {}).get("username")
        or (active_wall_user or {}).get("email")
        or "Friend"
    )

    if viewing_self:
        st.title("Such My Giphy Wall")
    else:
        st.title(f"Much {wall_owner_label}'s Giphy Wall")
        st.info(f"Peeking at {wall_owner_label}'s wall. Read-only vibes, wow.")
        render_reactions(active_wall_user_id)

        if st.button("Return to my wall wow"):
            st.session_state["active_wall_user_id"] = user_id
            st.session_state["wall_selector"] = user_id
            refresh_wall_gifs(user_id)
else:
    # If somehow reached without a user (shouldn't happen), block access
    st.info("Pls sign in to view doge wall, wow.")
    st.stop()
if "viewing_self" in locals():
    if viewing_self:
        st.caption("Paste Giphy link. Wall grow. New GIF go top. Very amaze.")
    else:
        st.caption(f"Enjoy {wall_owner_label}'s GIF stash wow. Switch back to share ur own favs.")

submitted = False
gif_url = ""
if viewing_self:
    with st.form("add-giphy"):
        gif_url = st.text_input(
            "Drop Giphy link wow",
            placeholder="https://giphy.com/gifs/...",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Summon Giphy")
else:
    st.info("No posting on fren wall. Switch back to share ur own GIFs.")

if submitted:
    gif_id = extract_gif_id(gif_url)
    if gif_id:
        add_gif_to_state(gif_id, _ensure_protocol(gif_url))
        st.success("Giphy added, wow!")
        st.rerun()
    else:
        st.error("Hmm, link not giphy enough. Much retry.")

wall_gifs = st.session_state.get("gifs") or []
if wall_gifs:
    for gif in wall_gifs:
        with st.container():
            st.markdown(
                f"""
                <div class="giphy-card">
                    <img
                        src="{gif['thumbnail_url']}"
                        alt="Giphy {gif['gif_id']}"
                        loading="lazy"
                    />
                </div>
                """,
                unsafe_allow_html=True,
            )
            if viewing_self:
                delete = st.button("Yikes, delete", key=f"delete_{gif['uuid']}")
                if delete:
                    delete_gif_from_state(gif["uuid"])
                    st.rerun()
else:
    if viewing_self:
        st.info("No gifs yet. Drop first link above, amaze incoming!")
    else:
        st.info(f"{wall_owner_label} has zero GIFs yet. Encourage fren!")

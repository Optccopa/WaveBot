import base64
import hashlib
import json
import logging
import os
import re
import secrets

import aiohttp
import aiohttp_jinja2
import aiohttp_session
import asyncpg
import jinja2
from aiohttp import web
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from redis.asyncio import Redis

from configmanager import ConfigManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
MANAGE_GUILD = 0x20

FIELD_LABELS = {
    "partner_channel": ("Partner Channel ID", "Channel where partner ads are posted"),
    "ad_channel": ("Ad Channel ID", "Channel containing your server ad (recent message with a link)"),
    "log_channel": ("Log Channel ID", "Private channel for WaveBot warnings and status messages"),
    "member_role": ("Member Role ID", "Role assigned to >95% of your server members"),
    "partner_ping_role": ("Partner Ping Role ID", "Role pinged for partner ads, must cover >8% of members"),
}

SNOWFLAKE_RE = re.compile(r"^\d{15,21}$")

routes = web.RouteTableDef()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@web.middleware
async def auth_middleware(request, handler):
    public = {"/login", "/callback"}
    if request.path not in public and not request.path.startswith("/static"):
        session = await aiohttp_session.get_session(request)
        if not session.get("user"):
            raise web.HTTPFound("/login")
    return await handler(request)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_manage_guild(permissions: int) -> bool:
    return bool(permissions & MANAGE_GUILD)


def _icon_url(guild_id: str, icon: str | None) -> str:
    if icon:
        return f"https://cdn.discordapp.com/icons/{guild_id}/{icon}.png?size=128"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


def _is_ready(config: dict | None) -> bool:
    if not config:
        return False
    return all(config.get(f) for f in FIELD_LABELS)


async def _authorized_guild_ids(request) -> set[int]:
    """Return set of guild IDs the bot knows about."""
    redis: Redis = request.app["redis"]
    members = await redis.smembers("bot:guild_ids")
    if members:
        return {int(m) for m in members}
    # fallback: guilds that have touched config
    async with request.app["db_pool"].acquire() as conn:
        rows = await conn.fetch("SELECT guild_id FROM guild_config")
    return {row["guild_id"] for row in rows}


async def _get_user_guilds(request) -> list[dict]:
    """Guilds from session filtered to: user has MANAGE_GUILD + bot is present."""
    session = await aiohttp_session.get_session(request)
    raw_guilds: list[dict] = session.get("guilds", [])
    bot_guild_ids = await _authorized_guild_ids(request)
    return [
        g for g in raw_guilds
        if _has_manage_guild(int(g["permissions"])) and int(g["id"]) in bot_guild_ids
    ]


async def _discord_get(http: aiohttp.ClientSession, token: str, path: str):
    async with http.get(
        f"{DISCORD_API}{path}",
        headers={"Authorization": f"Bearer {token}"}
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@routes.get("/login")
async def handle_login(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    client_id = os.environ["DISCORD_CLIENT_ID"]
    redirect_uri = os.environ["DISCORD_REDIRECT_URI"]
    params = (
        f"client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=identify%20guilds"
        f"&state={state}"
    )
    raise web.HTTPFound(f"https://discord.com/oauth2/authorize?{params}")


@routes.get("/callback")
async def handle_callback(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)

    code = request.rel_url.query.get("code")
    state = request.rel_url.query.get("state")

    if not code or state != session.get("oauth_state"):
        return aiohttp_jinja2.render_template(
            "error.html", request,
            {"code": 400, "message": "Invalid OAuth2 state. Try logging in again."},
            status=400
        )

    http: aiohttp.ClientSession = request.app["http_session"]

    async with http.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": os.environ["DISCORD_REDIRECT_URI"],
            "client_id": os.environ["DISCORD_CLIENT_ID"],
            "client_secret": os.environ["DISCORD_CLIENT_SECRET"],
        }
    ) as resp:
        if resp.status != 200:
            return aiohttp_jinja2.render_template(
                "error.html", request,
                {"code": 502, "message": "Failed to exchange code with Discord."},
                status=502
            )
        token_data = await resp.json()

    access_token = token_data["access_token"]

    user = await _discord_get(http, access_token, "/users/@me")
    guilds = await _discord_get(http, access_token, "/users/@me/guilds")

    session["user"] = {
        "id": user["id"],
        "username": user["username"],
        "avatar": user.get("avatar"),
    }
    session["guilds"] = [
        {"id": g["id"], "name": g["name"], "icon": g.get("icon"), "permissions": g["permissions"]}
        for g in guilds
    ]
    session["access_token"] = access_token
    del session["oauth_state"]

    raise web.HTTPFound("/")


@routes.get("/logout")
async def handle_logout(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    session.invalidate()
    raise web.HTTPFound("/login")


@routes.get("/")
async def handle_guild_list(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    user = session["user"]
    cm: ConfigManager = request.app["config_manager"]

    user_guilds = await _get_user_guilds(request)

    guild_cards = []
    for g in user_guilds:
        config = await cm.get(int(g["id"]))
        guild_cards.append({
            "id": g["id"],
            "name": g["name"],
            "icon_url": _icon_url(g["id"], g.get("icon")),
            "is_ready": _is_ready(config),
        })

    guild_cards.sort(key=lambda x: x["name"].lower())

    return aiohttp_jinja2.render_template("guilds.html", request, {
        "user": user,
        "guilds": guild_cards,
    })


@routes.get("/server/{guild_id}")
async def handle_server_get(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    user = session["user"]
    guild_id_str = request.match_info["guild_id"]

    try:
        guild_id = int(guild_id_str)
    except ValueError:
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 404, "message": "Guild not found."}, status=404
        )

    user_guilds = await _get_user_guilds(request)
    guild = next((g for g in user_guilds if int(g["id"]) == guild_id), None)
    if not guild:
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 403, "message": "Access denied."}, status=403
        )

    cm: ConfigManager = request.app["config_manager"]
    config = await cm.get(guild_id) or {}
    saved = request.rel_url.query.get("saved") == "1"

    return aiohttp_jinja2.render_template("server.html", request, {
        "user": user,
        "guild_id": guild_id_str,
        "guild_name": guild["name"],
        "guild_icon_url": _icon_url(guild["id"], guild.get("icon")),
        "config": config,
        "saved": saved,
        "errors": {},
        "labels": FIELD_LABELS,
    })


@routes.post("/server/{guild_id}")
async def handle_server_post(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    user = session["user"]
    guild_id_str = request.match_info["guild_id"]

    try:
        guild_id = int(guild_id_str)
    except ValueError:
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 404, "message": "Guild not found."}, status=404
        )

    user_guilds = await _get_user_guilds(request)
    guild = next((g for g in user_guilds if int(g["id"]) == guild_id), None)
    if not guild:
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 403, "message": "Access denied."}, status=403
        )

    form = await request.post()
    errors = {}
    fields = {}

    for field in FIELD_LABELS:
        raw = form.get(field, "").strip()
        if raw == "":
            continue
        if not SNOWFLAKE_RE.match(raw):
            errors[field] = "Must be a valid Discord ID (15–21 digits) or leave empty."
        else:
            fields[field] = int(raw)

    if errors:
        cm: ConfigManager = request.app["config_manager"]
        config = await cm.get(guild_id) or {}
        # overlay submitted values so the form retains user input
        for f, v in fields.items():
            config[f] = v
        return aiohttp_jinja2.render_template("server.html", request, {
            "user": user,
            "guild_id": guild_id_str,
            "guild_name": guild["name"],
            "guild_icon_url": _icon_url(guild["id"], guild.get("icon")),
            "config": config,
            "saved": False,
            "errors": errors,
            "labels": FIELD_LABELS,
        }, status=422)

    if fields:
        cm: ConfigManager = request.app["config_manager"]
        await cm.set(guild_id, **fields)

    raise web.HTTPFound(f"/server/{guild_id_str}?saved=1")


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

async def on_startup(app: web.Application):
    app["db_pool"] = await asyncpg.create_pool(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        user=os.environ.get("POSTGRES_USER", "appuser"),
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ.get("POSTGRES_DB", "appdb"),
    )
    app["redis"] = Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=6379,
        decode_responses=True,
    )
    app["config_manager"] = ConfigManager(app["db_pool"], app["redis"])
    app["http_session"] = aiohttp.ClientSession()


async def on_cleanup(app: web.Application):
    await app["db_pool"].close()
    await app["redis"].aclose()
    await app["http_session"].close()


def make_app() -> web.Application:
    # Session middleware must be registered before auth_middleware so get_session() works
    raw_key = os.environ["SESSION_SECRET_KEY"].encode()
    secret_key = hashlib.sha256(raw_key).digest()
    storage = EncryptedCookieStorage(secret_key, max_age=86400)

    app = web.Application()
    aiohttp_session.setup(app, storage)  # adds session middleware first
    app.middlewares.append(auth_middleware)

    # Jinja2 templates
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(
            os.path.join(os.path.dirname(__file__), "templates")
        ),
    )

    app.router.add_routes(routes)
    app.router.add_static("/static", os.path.join(os.path.dirname(__file__), "static"))

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PANEL_PORT", 8080))
    web.run_app(make_app(), host="0.0.0.0", port=port)

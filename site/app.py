import hashlib
import json
import logging
import os
import re
import secrets

import aiohttp
import aiohttp_jinja2
import yaml
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
async def security_headers_middleware(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        log.exception("Unhandled error on %s %s", request.method, request.path)
        response = aiohttp_jinja2.render_template(
            "error.html", request,
            {"code": 500, "message": "Something went wrong. Try again later."},
            status=500
        )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' https://cdn.discordapp.com data:; "
        "style-src 'self'; "
        "script-src 'none'"
    )
    return response


@web.middleware
async def auth_middleware(request, handler):
    public = {"/", "/login", "/callback", "/tos", "/privacy", "/favicon.ico"}
    if request.path not in public and not request.path.startswith("/static/"):
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


def _banner_url(guild_id: str, banner: str | None) -> str | None:
    if banner:
        return f"https://cdn.discordapp.com/banners/{guild_id}/{banner}.png?size=512"
    return None


def _is_ready(config: dict | None) -> bool:
    if not config:
        return False
    return all(config.get(f) for f in FIELD_LABELS)


def _csrf_token(session) -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


async def _authorized_guild_ids(request) -> set[int]:
    redis: Redis = request.app["redis"]
    members = await redis.smembers("bot:guild_ids")
    if members:
        return {int(m) for m in members}
    async with request.app["db_pool"].acquire() as conn:
        rows = await conn.fetch("SELECT guild_id FROM guild_config")
    return {row["guild_id"] for row in rows}


async def _get_user_guilds(request) -> list[dict]:
    session = await aiohttp_session.get_session(request)
    user_id = session["user"]["id"]
    redis: Redis = request.app["redis"]

    cache_key = f"panel:guilds:{user_id}"
    cached = await redis.get(cache_key)
    if cached:
        raw_guilds = json.loads(cached)
    else:
        http: aiohttp.ClientSession = request.app["http_session"]
        raw_guilds = await _discord_get(http, session["access_token"], "/users/@me/guilds?with_counts=true")
        raw_guilds = [
            {
                "id": g["id"],
                "name": g["name"],
                "icon": g.get("icon"),
                "banner": g.get("banner"),
                "permissions": g["permissions"],
                "member_count": g.get("approximate_member_count"),
                "online_count": g.get("approximate_presence_count"),
            }
            for g in raw_guilds
        ]
        await redis.set(cache_key, json.dumps(raw_guilds), ex=300)

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
        if resp.status == 429:
            raise web.HTTPServiceUnavailable(reason="Discord rate limit hit, try again in a moment.")
        resp.raise_for_status()
        return await resp.json()


def _client_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote or "unknown"


async def _check_rate_limit(redis: Redis, key: str, max_requests: int, window: int):
    # SET NX EX is atomic — eliminates INCR/EXPIRE race
    await redis.set(key, 0, nx=True, ex=window)
    count = await redis.incr(key)
    if count > max_requests:
        raise web.HTTPTooManyRequests(reason="Too many requests. Slow down.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@routes.get("/login")
async def handle_login(request: web.Request) -> web.Response:
    redis: Redis = request.app["redis"]
    await _check_rate_limit(redis, f"ratelimit:login:{_client_ip(request)}", max_requests=10, window=60)
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
    redis: Redis = request.app["redis"]
    await _check_rate_limit(redis, f"ratelimit:callback:{_client_ip(request)}", max_requests=10, window=60)
    session = await aiohttp_session.get_session(request)

    code = request.rel_url.query.get("code")
    state = request.rel_url.query.get("state")
    stored_state = session.get("oauth_state")

    # Clear state immediately after reading — prevents replay
    if "oauth_state" in session:
        del session["oauth_state"]

    if not code or state != stored_state:
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

    # Regenerate session to prevent session fixation
    session.invalidate()
    session["user"] = {
        "id": user["id"],
        "username": user["username"],
        "avatar": user.get("avatar"),
    }
    session["access_token"] = access_token

    raise web.HTTPFound("/servers")


@routes.post("/logout")
async def handle_logout(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    form = await request.post()
    if form.get("csrf_token") != session.get("csrf_token"):
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 403, "message": "Invalid request. Please try again."}, status=403
        )
    session.invalidate()
    raise web.HTTPFound("/login")


@routes.get("/")
async def handle_home(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    redis: Redis = request.app["redis"]
    guild_count = await redis.scard("bot:guild_ids")
    member_total = 0
    info = await redis.hgetall("bot:guild_info")
    for raw in info.values():
        try:
            member_total += json.loads(raw).get("member_count") or 0
        except Exception:
            pass
    partners_day = await redis.get("stats:partners")
    client_id = os.environ.get("DISCORD_CLIENT_ID", "")
    invite_url = (
        f"https://discord.com/oauth2/authorize?client_id={client_id}"
        f"&scope=bot+applications.commands&permissions=274877992000"
    ) if client_id else None
    partner_cooldown_hours = request.app["yaml_config"]["cache"]["partner_cooldown"] // 3600
    return aiohttp_jinja2.render_template("home.html", request, {
        "user": session.get("user"),
        "guild_count": guild_count,
        "member_total": member_total,
        "partners_day": partners_day,
        "partner_cooldown_hours": partner_cooldown_hours,
        "invite_url": invite_url,
        "support_invite": request.app["yaml_config"]["bot"]["support_invite"],
        "csrf_token": _csrf_token(session) if session.get("user") else None,
    })


@routes.get("/tos")
async def handle_tos(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    return aiohttp_jinja2.render_template("tos.html", request, {
        "user": session.get("user"),
        "support_invite": request.app["yaml_config"]["bot"]["support_invite"],
        "csrf_token": _csrf_token(session) if session.get("user") else None,
    })


@routes.get("/privacy")
async def handle_privacy(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    return aiohttp_jinja2.render_template("privacy.html", request, {
        "user": session.get("user"),
        "csrf_token": _csrf_token(session) if session.get("user") else None,
    })


@routes.get("/servers")
async def handle_guild_list(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    user = session["user"]
    cm: ConfigManager = request.app["config_manager"]

    redis: Redis = request.app["redis"]
    await _check_rate_limit(redis, f"ratelimit:get:{user['id']}", max_requests=30, window=60)

    user_guilds = await _get_user_guilds(request)

    guild_cards = []
    for g in user_guilds:
        config = await cm.get(int(g["id"]))
        guild_cards.append({
            "id": g["id"],
            "name": g["name"],
            "icon_url": _icon_url(g["id"], g.get("icon")),
            "banner_url": _banner_url(g["id"], g.get("banner")),
            "member_count": g.get("member_count"),
            "online_count": g.get("online_count"),
            "is_ready": _is_ready(config),
        })

    guild_cards.sort(key=lambda x: x["name"].lower())

    return aiohttp_jinja2.render_template("guilds.html", request, {
        "user": user,
        "guilds": guild_cards,
        "csrf_token": _csrf_token(session),
    })


@routes.get("/server/{guild_id}")
async def handle_server_get(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    user = session["user"]
    guild_id_str = request.match_info["guild_id"]

    if not SNOWFLAKE_RE.match(guild_id_str):
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 404, "message": "Guild not found."}, status=404
        )
    guild_id = int(guild_id_str)

    redis: Redis = request.app["redis"]
    await _check_rate_limit(redis, f"ratelimit:get:{user['id']}", max_requests=30, window=60)

    user_guilds = await _get_user_guilds(request)
    guild = next((g for g in user_guilds if int(g["id"]) == guild_id), None)
    if not guild:
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 403, "message": "Access denied."}, status=403
        )

    cm: ConfigManager = request.app["config_manager"]
    config = await cm.get(guild_id) or {}
    saved = request.rel_url.query.get("saved") == "1"
    pd_cfg = request.app["yaml_config"]["partner_delay"]

    return aiohttp_jinja2.render_template("server.html", request, {
        "user": user,
        "guild_id": guild_id_str,
        "guild_name": guild["name"],
        "guild_icon_url": _icon_url(guild["id"], guild.get("icon")),
        "config": config,
        "saved": saved,
        "errors": {},
        "validation_error": None,
        "labels": FIELD_LABELS,
        "csrf_token": _csrf_token(session),
        "partner_delay_hours": (config.get("partner_delay") or pd_cfg["default"]) // 3600,
        "partner_delay_min": pd_cfg["min"] // 3600,
        "partner_delay_max": pd_cfg["max"] // 3600,
    })


@routes.post("/server/{guild_id}")
async def handle_server_post(request: web.Request) -> web.Response:
    session = await aiohttp_session.get_session(request)
    user = session["user"]
    guild_id_str = request.match_info["guild_id"]

    if not SNOWFLAKE_RE.match(guild_id_str):
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 404, "message": "Guild not found."}, status=404
        )
    guild_id = int(guild_id_str)

    user_guilds = await _get_user_guilds(request)
    guild = next((g for g in user_guilds if int(g["id"]) == guild_id), None)
    if not guild:
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 403, "message": "Access denied."}, status=403
        )

    form = await request.post()

    # CSRF check
    if form.get("csrf_token") != session.get("csrf_token"):
        return aiohttp_jinja2.render_template(
            "error.html", request, {"code": 403, "message": "Invalid request. Please try again."}, status=403
        )

    # Rate limit: 10 saves per minute per user
    redis: Redis = request.app["redis"]
    await _check_rate_limit(redis, f"ratelimit:config:{user['id']}", max_requests=10, window=60)

    pd_cfg = request.app["yaml_config"]["partner_delay"]
    min_h = pd_cfg["min"] // 3600
    max_h = pd_cfg["max"] // 3600

    errors = {}
    fields = {}

    for field in FIELD_LABELS:
        raw = form.get(field, "").strip()
        if raw == "":
            continue
        if not SNOWFLAKE_RE.match(raw):
            errors[field] = "Must be a valid Discord ID (15-21 digits) or leave empty."
        else:
            fields[field] = int(raw)

    raw_delay = form.get("partner_delay_hours", "").strip()
    if raw_delay != "":
        try:
            hours = int(raw_delay)
            if not (min_h <= hours <= max_h):
                errors["partner_delay"] = f"Must be between {min_h} and {max_h} hours."
            else:
                fields["partner_delay"] = hours * 3600
        except ValueError:
            errors["partner_delay"] = "Must be a whole number of hours."

    if errors:
        cm: ConfigManager = request.app["config_manager"]
        config = await cm.get(guild_id) or {}
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
            "csrf_token": _csrf_token(session),
            "partner_delay_hours": raw_delay,
            "partner_delay_min": min_h,
            "partner_delay_max": max_h,
        }, status=422)

    if fields:
        cm: ConfigManager = request.app["config_manager"]
        current = await cm.get(guild_id) or {}
        merged = {**current, **fields}
        if all(merged.get(f) for f in ("member_role", "partner_ping_role", "partner_channel")):
            validation_error = None
            try:
                bot_url = os.environ.get("BOT_INTERNAL_URL", "http://bot:8081")
                http: aiohttp.ClientSession = request.app["http_session"]
                async with http.post(
                    f"{bot_url}/validate/{guild_id}",
                    json={"config": merged},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()
                    validation_error = data.get("reason")
            except Exception:
                pass
            if validation_error:
                config = await cm.get(guild_id) or {}
                for f, v in fields.items():
                    config[f] = v
                return aiohttp_jinja2.render_template("server.html", request, {
                    "user": user,
                    "guild_id": guild_id_str,
                    "guild_name": guild["name"],
                    "guild_icon_url": _icon_url(guild["id"], guild.get("icon")),
                    "config": config,
                    "saved": False,
                    "errors": {},
                    "validation_error": validation_error,
                    "labels": FIELD_LABELS,
                    "csrf_token": _csrf_token(session),
                    "partner_delay_hours": (merged.get("partner_delay") or pd_cfg["default"]) // 3600,
                    "partner_delay_min": min_h,
                    "partner_delay_max": max_h,
                }, status=422)
        await cm.set(guild_id, **fields)

    raise web.HTTPFound(f"/server/{guild_id_str}?saved=1")


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

async def on_startup(app: web.Application):
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path) as f:
        app["yaml_config"] = yaml.safe_load(f)
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
    app["http_session"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))


async def on_cleanup(app: web.Application):
    await app["db_pool"].close()
    await app["redis"].aclose()
    await app["http_session"].close()


def make_app() -> web.Application:
    raw_key = os.environ["SESSION_SECRET_KEY"].encode()
    secret_key = hashlib.sha256(raw_key).digest()
    storage = EncryptedCookieStorage(
        secret_key,
        max_age=86400,
        secure=os.environ.get("PRODUCTION", "false").lower() == "true",
        httponly=True,
        samesite="Lax",
    )

    app = web.Application()
    aiohttp_session.setup(app, storage)
    app.middlewares.append(security_headers_middleware)
    app.middlewares.append(auth_middleware)

    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(
            os.path.join(os.path.dirname(__file__), "templates")
        ),
    )

    app.router.add_routes(routes)
    app.router.add_static("/static", os.path.join(os.path.dirname(__file__), "static"))
    app.router.add_get("/favicon.ico", lambda _: web.FileResponse(os.path.join(os.path.dirname(__file__), "static", "favicon.ico")))

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PANEL_PORT", 8080))
    web.run_app(make_app(), host="0.0.0.0", port=port)

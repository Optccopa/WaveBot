# Test Checklist — Home Page + /servers Move + Auth Hardening

Run after deploy. Tick each box once verified.

## Routing
- [ ] Service starts cleanly under `docker compose up site`
- [ ] Visit `/` logged out → home renders, stats visible, no redirect to `/login`
- [ ] Visit `/` logged in → home still renders, nav shows user chrome
- [ ] Click `Log in` from home → OAuth flow → lands on `/servers`
- [ ] Visit `/servers` logged out → redirected to `/login`
- [ ] Visit `/servers` logged in → guild list renders as before
- [ ] On a `/server/{id}` page, click back-link → lands on `/servers`
- [ ] Logout → redirected to `/login`; revisit `/` → home renders without user chrome
- [ ] Visit `/tos` and `/privacy` logged out → both render

## Auth Hardening
- [ ] Hit `/login` 11 times in a minute from one IP → 11th returns `429`
- [ ] Hit `/callback?code=x` 11 times in a minute from one IP → 11th returns `429`
- [ ] Hit `/staticx` → redirected to `/login` (no bypass)
- [ ] Hit `/static/style.css` → 200, no auth required

## Stats Sanity
- [ ] `guild_count` on home matches `redis-cli SCARD bot:guild_ids`
- [ ] `member_total` on home matches manual sum of `HGETALL bot:guild_info` member_count fields
- [ ] Invite button on home opens correct Discord OAuth invite URL

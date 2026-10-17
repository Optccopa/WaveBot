# Wavebot

A discord server partnership bot build for scale.

## Run
man idk, tell claude to do it

## Features
- Ads are indexed from the most recent 10 messages in the ad channel, taking the most recent message with a link and caching it
- Ad scanning pipeline with claude-haiku-4-5 (use haiku 5.5 or rebuild to use a decision model), and a regex pre-scan for flagged words
- Configureable per-server partner cooldown
- Matches pairs from all available servers based on multiple factors, doesnt pair inside of cooldown or if a guilds premium blocks it
- Ad info buttons (add wavebot, partner info, report)
- Report system: model on each ad + triage in a staff channel (blacklist or dismiss, with an optional message to reporter and target owner)
- Website frontend with discord oauth and a servers dashboard (May be live at `https://unity.wavebot.dev`)

### Public commands
- `p!ping` - latency
- `p!help` - command list
- `p!support` - support server invite
- `/bot info` - server count, total members, stack, support inv, version
- `/partner reqs [membercount]` - show partner req calculations
- `/partner ad [guild id]` - view a servers public cached ad
### Management commands
- `/config set` - set config variables; channels, times, etc
- `/config view` - show them
- `/partner status` - Figure out why you are not eligible for partners
### Guild owner commands
- `/premium configset [available pings]` - restrict pings usable if your server is premium
- `/premium configview` - Show them
### Bot owner commands
  - `/partner force [gid1] [gid2]` - force a partner between 2 servers
  - `/partner loopforce` - force a full loop
  - `/partner indexads` - force a full ad reindex
  - `/partner broadcast [gid]` - sends the cached ad to every server available (24hr cooldown to avoid dc flagging it), use to send the bots support server ad
  - `/servers overview` - members, needs/week, available/week, next eligible time
  - `/servers debug / debugall` - basically same as partner status but from owner side
  - `/servers leave [gid]` - leave a server
  - `/servers invide [gid]` - get an invite to a server
  - `/blacklist add / check /remove [gid]` - blacklist commands
  - `/whitelist add / remove [link]` - add or remove links from the link whitelist
  - `/whitelist list` - list all whitelisted links
  - `/earlyaccess add [gid] [user] [reason]` - lets the bot join servers under 50 members (DO NOT GIVE THIS TO ANNOYING BEGGARS)
  - `/earlyaccess remove [gid]` - yk
  - `/earlyaccess list` - yk
  - `/premium add / remove [gid]` - toggle a guilds premium (/premium configset above)
  - `p!exec` - runs async python in bot context
  - `p!search [query]` - search for a guild via name
  - `p!cull` - lists servers missing required config vars
  - `/error` - shows the last recorded error per type

## Contact
- Discord: optccopa

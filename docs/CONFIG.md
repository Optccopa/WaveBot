# Server Configuration

## Setup Command
```
/config set [option] [value]
```

### Options

#### partner_channel (required)
- **Type:** Discord Text Channel
- **Description:** Channel where partner ads are posted
- **Required for:** Partnership matching

#### ad_channel (required)
- **Type:** Discord Text Channel
- **Description:** Channel containing the server's own ad (must have a recent message with a URL)
- **Required for:** Partnership matching

#### member_role (required)
- **Type:** Discord Role
- **Description:** Role assigned to active members
- **Requirement:** Must be assigned to ≥80% of server members
- **Required for:** Partnership matching

#### partner_ping_role (required)
- **Type:** Discord Role
- **Description:** Role pinged when partners are received
- **Requirement:** Must be assigned to ≥8% of server members
- **Required for:** Partnership matching

#### log_channel (optional)
- **Type:** Discord Text Channel
- **Description:** Channel for WaveBot warnings and status messages
- **Default:** None
- **Recommendation:** Private channel, restricted to mods

#### partner_delay (optional)
- **Type:** Integer (seconds in DB; hours in web panel)
- **Description:** Time between receiving partners
- **Minimum:** 3600 seconds (1 hour)
- **Maximum:** 604800 seconds (7 days)
- **Default:** 21600 seconds (6 hours)
- **Web panel:** Displayed and entered in hours (1–168). Converts to/from seconds automatically.

## View Configuration
```
/config view
```

Displays all current settings and their status (valid/invalid/not set).

## Example Setup
```
/config set partner_channel #partners
/config set ad_channel #our-ad
/config set member_role @member
/config set partner_ping_role @partner-ping
/config set log_channel #bot-logs
/config set partner_delay 86400
```

This configures:
- Ads post to #partners
- Bot reads server ad from #our-ad
- Members identified by @member role
- @partner-ping is pinged on new partners
- Errors logged to #bot-logs
- Wait 24 hours between partner rounds

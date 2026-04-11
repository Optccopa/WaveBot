from discord import app_commands

partnerGroup = app_commands.Group(
    name="partner",
    description="Partner commands"
)

blacklistGroup = app_commands.Group(
    name="blacklist",
    description="Server blacklist management"
)

serversGroup = app_commands.Group(
    name="servers",
    description="Manage all servers together"
)
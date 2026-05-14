import discord

def is_owner():
    """Check if the user is the bot owner"""
    async def predicate(interaction) -> bool:
        return await interaction.client.is_owner(interaction.user)
    return discord.app_commands.check(predicate)

def is_guild_owner():
    """Check if the user has guild owner permissions, or is the bot owner"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if await interaction.client.is_owner(interaction.user):
            return True
        if interaction.guild and interaction.guild.owner_id == interaction.user.id:
            return True
        raise discord.app_commands.MissingPermissions(["guild_owner"])
    return discord.app_commands.check(predicate)

def is_management():
    """Check if the user has admin, manage guild, or is the bot owner"""
    async def predicate(interaction: discord.Interaction) -> bool:
        if await interaction.client.is_owner(interaction.user):
            return True
        perms = interaction.permissions
        if perms.administrator or perms.manage_guild:
            return True
        raise discord.app_commands.MissingPermissions(["manage_guild"])
    return discord.app_commands.check(predicate)
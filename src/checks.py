import discord

def _is_owner(interaction: discord.Interaction) -> bool:
    if interaction.client.owner_id and interaction.user.id == interaction.client.owner_id:
        return True
    if interaction.client.owner_ids and interaction.user.id in interaction.client.owner_ids:
        return True
    return False

def is_owner():
    async def predicate(interaction) -> bool:
        return await interaction.client.is_owner(interaction.user)
    return discord.app_commands.check(predicate)

def has_management():
    async def predicate(interaction: discord.Interaction) -> bool:
        if _is_owner(interaction):
            return True
        perms = interaction.permissions
        if perms.administrator or perms.manage_guild:
            return True
        raise discord.app_commands.MissingPermissions(["manage_guild"])
    return discord.app_commands.check(predicate)
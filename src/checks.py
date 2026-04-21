import discord


def is_owner():
    async def predicate(interaction) -> bool:
        return await interaction.client.is_owner(interaction.user)
    return discord.app_commands.check(predicate)

def has_management():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await interaction.client.is_owner(interaction.user):
            return True
        perms = interaction.permissions
        if perms.administrator or perms.manage_guild:
            return True
        raise discord.app_commands.MissingPermissions(["manage_guild"])
    return discord.app_commands.check(predicate)
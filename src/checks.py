import discord

def is_owner():
    async def predicate(interaction) -> bool:
        return await interaction.client.is_owner(interaction.user)
    return discord.app_commands.check(predicate)
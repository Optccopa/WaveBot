# Commands Reference

## Autocomplete

```python
@discord.app_commands.command(name="partner", description="Partner with a server.")
async def partner(self, interaction: discord.Interaction, server: str):
    ...

@partner.autocomplete("server")
async def server_autocomplete(
    self, interaction: discord.Interaction, current: str
) -> list[discord.app_commands.Choice[str]]:
    guild_ids = await self.redis.smembers("bot:guild_ids")
    return [
        discord.app_commands.Choice(name=name, value=str(gid))
        for gid, name in matches
        if current.lower() in name.lower()
    ][:25]  # max 25 choices
```

## Checks

Custom check decorator pattern (from `src/checks.py`):

```python
def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not await interaction.client.is_owner(interaction.user):
            raise discord.app_commands.MissingPermissions(["bot_owner"])
        return True
    return discord.app_commands.check(predicate)
```

Stack multiple checks — all must pass:

```python
@discord.app_commands.command(...)
@discord.app_commands.checks.cooldown(1, 10)
@is_management()
async def cmd(self, interaction: discord.Interaction):
    ...
```

## Interaction Timing

Discord requires a response within 3 seconds. For slow operations:

```python
async def slow_command(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    result = await some_slow_operation()
    await interaction.followup.send(result)
```

Never call `defer()` if you've already called `send_message()`, or vice versa.

## Ephemeral vs Public

- Errors and feedback visible only to the invoker → `ephemeral=True`
- Information others in the channel should see → no flag
- Management/owner commands → always `ephemeral=True`

## Guild-Only Commands

Add to command or group to restrict to servers (no DMs):

```python
@discord.app_commands.guild_only()
```

## Transformer Arguments

For typed Discord objects as parameters:

```python
async def cmd(self, interaction: discord.Interaction, channel: discord.TextChannel):
    ...
```

`TransformerError` is caught by `ErrorHandler` if Discord can't resolve the value.

## Prefix Command Specifics

- `on_message` lowercases content before `process_commands` — prefix commands are case-insensitive.
- Prefix is `p!` (from `yaml_config['bot']['prefix']`).
- Prefix commands used only for owner tooling (`cogs/owneronly.py`).
- `ctx.send()` for responses; delete after short delay for ephemeral-style:

```python
msg = await ctx.send("...", delete_after=3)
```

import asyncio
import logging
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is missing. Add it to your .env file.")

PREFIX = os.getenv("BOT_PREFIX", "!")
ADMIN_ROLE = os.getenv("BOT_ADMIN_ROLE", "admin")
WELCOME_CHANNEL_ID = os.getenv("WELCOME_CHANNEL_ID", "").strip()
WELCOME_RULES = tuple(
    rule.strip()
    for rule in os.getenv(
        "WELCOME_RULES",
        "Be respectful to everyone|No NSFW or otherwise inappropriate content"
        "|No spam, raids, or unsolicited advertising|Respect people's privacy"
        "|Follow Discord's Terms of Service and moderator instructions",
    ).split("|")
    if rule.strip()
)
WELCOME_RULES_TEXT = "\n".join(f"• {rule}" for rule in WELCOME_RULES)
if not WELCOME_RULES or len(WELCOME_RULES_TEXT) > 1024:
    raise SystemExit("WELCOME_RULES must contain rules totaling 1024 characters or fewer.")
SUGGESTIONS_CHANNEL_ID = os.getenv("SUGGESTIONS_CHANNEL_ID", "").strip()
REPORTS_CHANNEL_ID = os.getenv("REPORTS_CHANNEL_ID", "").strip()
DATABASE_PATH = os.getenv("WARNINGS_DATABASE", "warnings.sqlite3")
DEFAULT_BLOCKED_WORDS = (
    "arse",
    "ass",
    "asshole",
    "bastard",
    "bitch",
    "bullshit",
    "crap",
    "cunt",
    "damn",
    "dick",
    "dipshit",
    "fucked",
    "fucker",
    "fucks",
    "fuck",
    "fucking",
    "jackass",
    "motherfucker",
    "piss",
    "shit",
    "shithead",
    "slut",
    "twat",
    "wanker",
)
BLOCKED_WORDS = [
    word.strip()
    for word in os.getenv("BLOCKED_WORDS", ",".join(DEFAULT_BLOCKED_WORDS)).split(",")
    if word.strip()
]
BLOCKED_WORD_PATTERN = (
    re.compile(
        "|".join(
            r"(?<!\w)"
            + r"[\W_]{0,2}".join(re.escape(character) for character in word)
            + r"(?!\w)"
            for word in sorted(BLOCKED_WORDS, key=len, reverse=True)
        ),
        re.IGNORECASE,
    )
    if BLOCKED_WORDS
    else None
)

logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    filename="discord.log",
    encoding="utf-8",
    maxBytes=1_000_000,
    backupCount=3,
)
handler.setFormatter(
    logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")
)
logger.addHandler(handler)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


def initialize_warning_database():
    with sqlite3.connect(DATABASE_PATH) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


initialize_warning_database()
HELP_GROUPS = {
    "✨ General": (
        "help", "hello", "ping", "botinfo", "serverinfo", "userinfo", "avatar", "roleinfo"
    ),
    "🎉 Community": (
        "poll", "choose", "coinflip", "8ball", "reply", "dm", "remind", "suggest", "report"
    ),
    "🛡️ Moderation": (
        "clear", "purgeuser", "warn", "warnings", "clearwarnings", "kick", "ban",
        "unban", "timeout", "untimeout", "nickname",
    ),
    "🔧 Channel tools": ("lock", "unlock", "slowmode", "announce"),
    "🎭 Roles": ("assign", "remove", "secret"),
}


def format_member(member):
    return f"{member} (`{member.id}`)"


def make_embed(title, description=None, color=discord.Color.blurple()):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Victonite.Jr • Community bot")
    return embed


@bot.command(name="help")
async def show_help(ctx, *, command_name: str = None):
    """Show the command guide or usage for one command."""
    if command_name:
        command = bot.get_command(command_name.strip())
        if command is None:
            await ctx.send(
                embed=make_embed(
                    "❔ Command not found",
                    f"Use `{PREFIX}help` to see the available commands.",
                    discord.Color.orange(),
                )
            )
            return
        embed = make_embed(
            f"📘 {PREFIX}{command.qualified_name}",
            command.help or "No description is available.",
        )
        embed.add_field(
            name="Usage",
            value=f"`{PREFIX}{command.qualified_name} {command.signature}`".strip(),
            inline=False,
        )
        if command.aliases:
            embed.add_field(name="Aliases", value=", ".join(command.aliases), inline=False)
        await ctx.send(embed=embed)
        return

    embed = make_embed(
        "📚 Victonite.Jr command guide",
        f"Use `{PREFIX}help <command>` for usage and details.\n"
        f"Current prefix: `{PREFIX}`",
    )
    for group_name, command_names in HELP_GROUPS.items():
        descriptions = []
        for name in command_names:
            command = bot.get_command(name)
            if command is not None:
                descriptions.append(f"`{PREFIX}{name}` — {command.short_doc or 'Bot command'}")
        if descriptions:
            embed.add_field(name=group_name, value="\n".join(descriptions), inline=False)
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    await ctx.send(embed=embed)


def configured_channel_id(value, setting_name):
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{setting_name} must be a numeric Discord channel ID.") from error


@bot.event
async def on_ready():
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    logger.info("Connected to %s server(s)", len(bot.guilds))
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name=f"{PREFIX}help",
        )
    )


@bot.event
async def on_member_join(member):
    channel = None
    try:
        if WELCOME_CHANNEL_ID:
            channel_id = configured_channel_id(WELCOME_CHANNEL_ID, "WELCOME_CHANNEL_ID")
            channel = member.guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                logger.warning(
                    "Welcome channel %s is unavailable or is not a text channel in server %s",
                    channel_id,
                    member.guild.id,
                )
    except ValueError:
        logger.error("WELCOME_CHANNEL_ID must be a numeric Discord channel ID")

    if channel is None:
        channel = member.guild.system_channel
    if channel is None and member.guild.me:
        channel = next(
            (
                candidate
                for candidate in member.guild.text_channels
                if candidate.permissions_for(member.guild.me).view_channel
                and candidate.permissions_for(member.guild.me).send_messages
            ),
            None,
        )

    if member.guild.me and isinstance(channel, discord.TextChannel):
        permissions = channel.permissions_for(member.guild.me)
        if not permissions.view_channel or not permissions.send_messages:
            channel = next(
                (
                    candidate
                    for candidate in member.guild.text_channels
                    if candidate.id != channel.id
                    and candidate.permissions_for(member.guild.me).view_channel
                    and candidate.permissions_for(member.guild.me).send_messages
                ),
                None,
            )

    if isinstance(channel, discord.TextChannel):
        permissions = channel.permissions_for(member.guild.me) if member.guild.me else None
        if permissions and permissions.view_channel and permissions.send_messages:
            welcome_embed = make_embed(
                f"Welcome to {member.guild.name}!",
                f"{member.mention} just joined the community.\n"
                f"You’re member **#{member.guild.member_count or '—'}**!",
                discord.Color.green(),
            )
            welcome_embed.set_thumbnail(url=member.display_avatar.url)
            welcome_embed.add_field(
                name="Getting started",
                value="Check your DMs for the server rules, then say hello!",
                inline=False,
            )
            if member.guild.icon:
                welcome_embed.set_author(
                    name=member.guild.name,
                    icon_url=member.guild.icon.url,
                )
            try:
                await channel.send(
                    content=member.mention,
                    embed=welcome_embed,
                    allowed_mentions=discord.AllowedMentions(
                        users=[member], roles=False, everyone=False
                    ),
                )
            except discord.Forbidden:
                logger.info(
                    "Could not post a welcome message in channel %s",
                    channel.id,
                )
            except discord.HTTPException:
                logger.exception(
                    "Failed to post a welcome message in channel %s",
                    channel.id,
                )
        else:
            logger.warning(
                "Bot cannot view or send welcome messages in channel %s",
                channel.id,
            )
    else:
        logger.warning(
            "No suitable welcome text channel found in server %s",
            member.guild.id,
        )

    rules_embed = make_embed(
        f"Welcome to {member.guild.name}!",
        "Before you join in, please read and follow these community rules.",
        discord.Color.blurple(),
    )
    rules_embed.add_field(
        name="📜 Server rules",
        value=WELCOME_RULES_TEXT,
        inline=False,
    )
    if member.guild.icon:
        rules_embed.set_thumbnail(url=member.guild.icon.url)
    rules_embed.add_field(
        name="Need help?",
        value="Contact a moderator if you have questions. Enjoy your stay!",
        inline=False,
    )
    try:
        await member.send(embed=rules_embed)
    except discord.Forbidden:
        logger.info(
            "Could not DM the server rules to member %s; their DMs may be closed",
            member.id,
        )
    except discord.HTTPException:
        logger.exception(
            "Failed to DM the server rules to member %s",
            member.id,
        )


@bot.event
async def on_member_remove(member):
    if not WELCOME_CHANNEL_ID:
        return
    try:
        channel_id = configured_channel_id(WELCOME_CHANNEL_ID, "WELCOME_CHANNEL_ID")
        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        embed = make_embed(
            "A member has left",
            f"**{discord.utils.escape_markdown(member.display_name)}** left the server.",
            discord.Color.dark_grey(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)
    except ValueError:
        logger.error("WELCOME_CHANNEL_ID must be a numeric Discord channel ID")
    except discord.Forbidden:
        logger.info("Could not post a leave message for member %s", member.id)
    except discord.HTTPException:
        logger.exception("Failed to post a leave message for member %s", member.id)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if (
        BLOCKED_WORD_PATTERN
        and message.guild is not None
        and BLOCKED_WORD_PATTERN.search(message.content)
    ):
        try:
            await message.delete()
            notice = make_embed(
                "Please keep it respectful",
                f"{message.author.mention}, your message was removed for language "
                "that isn't allowed here.",
                discord.Color.orange(),
            )
            await message.channel.send(
                embed=notice,
                delete_after=8,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        except discord.Forbidden:
            logger.warning(
                "Missing permission to moderate messages in channel %s",
                message.channel.id,
            )
        except discord.HTTPException:
            logger.exception("Failed to moderate message %s", message.id)

    await bot.process_commands(message)


@bot.command()
async def hello(ctx):
    """Say hello to the bot."""
    await ctx.send(f"Hello, {ctx.author.mention}!")


@bot.command()
async def ping(ctx):
    """Show the bot's websocket latency."""
    embed = make_embed(
        "🏓 Pong!",
        f"Gateway latency: **{bot.latency * 1000:.0f} ms**",
        discord.Color.green(),
    )
    await ctx.send(embed=embed)


@bot.command()
async def botinfo(ctx):
    """Show bot version, uptime-independent stats, and invite details."""
    embed = make_embed(
        "🤖 Victonite.Jr",
        "Your all-in-one community assistant.",
        discord.Color.blurple(),
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
        embed.add_field(name="Bot user", value=bot.user.mention, inline=True)
    embed.add_field(name="Servers", value=len(bot.guilds), inline=True)
    embed.add_field(name="Commands", value=len(bot.commands), inline=True)
    embed.add_field(name="Library", value=f"discord.py {discord.__version__}", inline=True)
    embed.add_field(name="Prefix", value=f"`{PREFIX}`", inline=True)
    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
async def serverinfo(ctx):
    """Show information about this server."""
    guild = ctx.guild
    embed = make_embed(
        f"🏰 {guild.name}",
        "A quick look at this community.",
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Server ID", value=guild.id, inline=True)
    embed.add_field(name="Members", value=guild.member_count or "Unknown", inline=True)
    embed.add_field(name="Owner", value=guild.owner or f"ID: {guild.owner_id}", inline=True)
    embed.add_field(name="Text channels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="Voice channels", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="Roles", value=max(0, len(guild.roles) - 1), inline=True)
    embed.add_field(
        name="Created",
        value=discord.utils.format_dt(guild.created_at, style="D"),
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
async def userinfo(ctx, member: discord.Member = None):
    """Show information about you or another server member."""
    member = member or ctx.author
    embed = make_embed(
        f"👤 {discord.utils.escape_markdown(str(member))}",
        f"Profile overview for {member.mention}.",
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="User ID", value=member.id, inline=True)
    embed.add_field(
        name="Account created",
        value=discord.utils.format_dt(member.created_at, style="R"),
        inline=True,
    )
    embed.add_field(
        name="Joined server",
        value=(
            discord.utils.format_dt(member.joined_at, style="R")
            if member.joined_at
            else "Unknown"
        ),
        inline=True,
    )
    roles = [role.mention for role in reversed(member.roles) if role.name != "@everyone"]
    embed.add_field(
        name=f"Roles ({len(roles)})",
        value=", ".join(roles[:10]) or "No roles",
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command()
async def avatar(ctx, member: discord.User = None):
    """Show your avatar or another user's avatar."""
    member = member or ctx.author
    embed = make_embed(f"🖼️ {member.display_name}'s avatar")
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
@commands.guild_only()
async def roleinfo(ctx, *, role: discord.Role):
    """Show details about a server role."""
    embed = make_embed(
        f"🎭 Role: {discord.utils.escape_markdown(role.name)}",
        f"Role ID: `{role.id}`",
    )
    embed.add_field(name="Members", value=len(role.members), inline=True)
    embed.add_field(name="Position", value=role.position, inline=True)
    embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
    embed.add_field(
        name="Mentionable",
        value="Yes" if role.mentionable else "No",
        inline=True,
    )
    embed.add_field(name="Created", value=discord.utils.format_dt(role.created_at, style="R"))
    await ctx.send(embed=embed)


@bot.command(name="poll", aliases=["echo"])
async def poll(ctx, *, question: str):
    """Create a yes/no or multi-choice poll using | between choices."""
    parts = [part.strip() for part in question.split("|")]
    question = parts[0]
    if not question or len(question) > 2000:
        raise commands.BadArgument("Poll questions must be between 1 and 2000 characters.")
    choices = parts[1:]
    if choices and not 2 <= len(choices) <= 10:
        raise commands.BadArgument("A poll needs between 2 and 10 choices.")
    if any(not choice for choice in choices):
        raise commands.BadArgument("Poll choices cannot be empty.")
    if any(len(choice) > 100 for choice in choices):
        raise commands.BadArgument("Each poll choice must be 100 characters or fewer.")
    description = f"**{question}**"
    if choices:
        number_emojis = (
            "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
            "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
        )
        description += "\n\n" + "\n".join(
            f"{number_emojis[index]}  {choice}" for index, choice in enumerate(choices)
        )
        reactions = number_emojis[:len(choices)]
    else:
        description += "\n\nReact with 👍 for yes or 👎 for no."
        reactions = ("👍", "👎")
    embed = make_embed("📊 Community Poll", description, discord.Color.blue())
    embed.set_author(name=f"Poll by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    embed.set_footer(text="Cast your vote with a reaction • Victonite.Jr")
    poll_message = await ctx.send(embed=embed)
    for reaction in reactions:
        await poll_message.add_reaction(reaction)


@bot.command()
async def choose(ctx, *, options: str):
    """Choose one of comma-separated options. Example: !choose tea, coffee, water"""
    choices = [option.strip() for option in options.split(",") if option.strip()]
    if len(choices) < 2:
        raise commands.BadArgument("Provide at least two choices separated by commas.")
    if len(choices) > 20:
        raise commands.BadArgument("Please provide no more than 20 choices.")
    await ctx.send(embed=make_embed(
        "🎯 The choice is...",
        f"**{discord.utils.escape_markdown(random.choice(choices))}**",
        discord.Color.gold(),
    ))


@bot.command()
async def coinflip(ctx):
    """Flip a coin."""
    await ctx.send(embed=make_embed(
        "🪙 Coin flip",
        f"The result is **{random.choice(('Heads', 'Tails'))}**!",
        discord.Color.gold(),
    ))


@bot.command(name="8ball")
async def eightball(ctx, *, question: str):
    """Ask the magic 8-ball a question."""
    answers = (
        "It is certain.",
        "Without a doubt.",
        "Yes, definitely.",
        "Most likely.",
        "Ask again later.",
        "Cannot predict that right now.",
        "Probably not.",
        "My sources say no.",
        "Very doubtful.",
    )
    await ctx.send(embed=make_embed(
        "🎱 The Magic 8-Ball says...",
        f"**{random.choice(answers)}**",
        discord.Color.purple(),
    ))


@bot.command()
async def dm(ctx, *, message: str):
    """Send yourself a private message from the bot."""
    await ctx.author.send(message)
    await ctx.send("I sent you a DM.")


def get_configured_channel(ctx, setting_value, setting_name):
    try:
        channel_id = configured_channel_id(setting_value, setting_name)
    except ValueError as error:
        raise commands.BadArgument(str(error)) from error
    channel = ctx.guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        raise commands.BadArgument(
            f"Set {setting_name} to a valid text channel or thread ID to use this feature."
        )
    return channel


@bot.command()
@commands.guild_only()
@commands.cooldown(1, 15, commands.BucketType.user)
async def suggest(ctx, *, suggestion: str):
    """Send a suggestion to the configured suggestions channel."""
    suggestion = suggestion.strip()
    if not suggestion or len(suggestion) > 1500:
        raise commands.BadArgument("Suggestions must be between 1 and 1500 characters.")
    channel = get_configured_channel(ctx, SUGGESTIONS_CHANNEL_ID, "SUGGESTIONS_CHANNEL_ID")
    embed = make_embed(
        "💡 New community suggestion",
        discord.utils.escape_mentions(suggestion),
        discord.Color.gold(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="Status", value="🟡 Under review", inline=False)
    suggestion_message = await channel.send(embed=embed)
    await suggestion_message.add_reaction("👍")
    await suggestion_message.add_reaction("👎")
    await ctx.send("Thanks! Your suggestion has been sent to the team.")


@bot.command()
@commands.guild_only()
@commands.cooldown(1, 15, commands.BucketType.user)
async def report(ctx, member: discord.Member, *, reason: str):
    """Privately submit a member report to the configured reports channel."""
    reason = reason.strip()
    if not reason or len(reason) > 1500:
        raise commands.BadArgument("Report details must be between 1 and 1500 characters.")
    channel = get_configured_channel(ctx, REPORTS_CHANNEL_ID, "REPORTS_CHANNEL_ID")
    embed = make_embed(
        "🚩 Member report",
        discord.utils.escape_mentions(reason),
        discord.Color.red(),
    )
    embed.add_field(name="Reported member", value=format_member(member), inline=False)
    embed.add_field(name="Reported by", value=format_member(ctx.author), inline=False)
    embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await ctx.send("Your report has been sent to the moderation team.")


@bot.command()
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def announce(ctx, *, message: str):
    """Post a polished announcement in the current channel."""
    message = message.strip()
    if not message or len(message) > 4000:
        raise commands.BadArgument("Announcements must be between 1 and 4000 characters.")
    embed = make_embed(
        "📣 Server Announcement",
        discord.utils.escape_mentions(message),
        discord.Color.blurple(),
    )
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.command()
async def remind(ctx, minutes: int, *, reminder: str):
    """Send yourself a reminder in this channel, up to 7 days from now."""
    if not 1 <= minutes <= 10080:
        raise commands.BadArgument("Reminder time must be between 1 and 10080 minutes.")
    reminder = reminder.strip()
    if not reminder or len(reminder) > 1000:
        raise commands.BadArgument("Reminder text must be between 1 and 1000 characters.")
    remind_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    await ctx.send(
        embed=make_embed(
            "⏰ Reminder set",
            f"I’ll remind you {discord.utils.format_dt(remind_at, style='R')}.\n"
            f"> {discord.utils.escape_mentions(reminder)}",
            discord.Color.teal(),
        )
    )
    asyncio.create_task(
        deliver_reminder(ctx.channel.id, ctx.author.id, reminder, minutes * 60)
    )


async def deliver_reminder(channel_id, user_id, reminder, delay_seconds):
    await asyncio.sleep(delay_seconds)
    channel = bot.get_channel(channel_id)
    if channel is None:
        logger.warning("Could not deliver reminder; channel %s is unavailable", channel_id)
        return
    try:
        await channel.send(
            content=f"<@{user_id}>",
            embed=make_embed(
                "⏰ Your reminder",
                discord.utils.escape_mentions(reminder),
                discord.Color.teal(),
            ),
            allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=user_id)]),
        )
    except discord.HTTPException:
        logger.exception("Could not deliver reminder to user %s", user_id)


@bot.command(aliases=["say"])
async def reply(ctx, *, message: str):
    """Repeat a message without allowing it to trigger user or role mentions."""
    await ctx.send(
        f"{ctx.author.display_name} says: {message}",
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.command(name="assign", aliases=["roleadd"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def assign(ctx, member: discord.Member, *, role: discord.Role):
    """Assign a role to a member (requires Manage Roles)."""
    if role.is_default():
        raise commands.BadArgument("The @everyone role cannot be assigned.")
    await member.add_roles(role, reason=f"Role assigned by {ctx.author}")
    await ctx.send(f"Assigned {role.mention} to {member.mention}.")


@bot.command(name="remove", aliases=["roleremove"])
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def remove(ctx, member: discord.Member, *, role: discord.Role):
    """Remove a role from a member (requires Manage Roles)."""
    if role.is_default():
        raise commands.BadArgument("The @everyone role cannot be removed.")
    await member.remove_roles(role, reason=f"Role removed by {ctx.author}")
    await ctx.send(f"Removed {role.mention} from {member.mention}.")


@bot.command()
@commands.guild_only()
@commands.has_guild_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    """Set the current channel slowmode from 0 to 21600 seconds."""
    if not isinstance(ctx.channel, discord.TextChannel):
        raise commands.BadArgument("Slowmode can only be changed in a text channel.")
    if not 0 <= seconds <= 21600:
        raise commands.BadArgument("Slowmode must be between 0 and 21600 seconds.")
    await ctx.channel.edit(slowmode_delay=seconds, reason=f"Changed by {ctx.author}")
    await ctx.send(
        embed=make_embed(
            "🐢 Slowmode updated",
            f"Slowmode is now **{seconds} seconds**.",
            discord.Color.orange(),
        )
    )


@bot.command()
@commands.guild_only()
@commands.has_guild_permissions(manage_channels=True)
async def lock(ctx):
    """Prevent @everyone from sending messages in the current channel."""
    if not isinstance(ctx.channel, discord.TextChannel):
        raise commands.BadArgument("Channels can only be locked from a text channel.")
    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        send_messages=False,
        reason=f"Channel locked by {ctx.author}",
    )
    await ctx.send(embed=make_embed("🔒 Channel locked", color=discord.Color.red()))


@bot.command()
@commands.guild_only()
@commands.has_guild_permissions(manage_channels=True)
async def unlock(ctx):
    """Allow @everyone to send messages in the current channel."""
    if not isinstance(ctx.channel, discord.TextChannel):
        raise commands.BadArgument("Channels can only be unlocked from a text channel.")
    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        send_messages=None,
        reason=f"Channel unlocked by {ctx.author}",
    )
    await ctx.send(embed=make_embed("🔓 Channel unlocked", color=discord.Color.green()))


@bot.command()
@commands.has_role(ADMIN_ROLE)
async def secret(ctx):
    """Show a message available to members with the configured admin role."""
    await ctx.send(f"This command is restricted to the **{ADMIN_ROLE}** role.")


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    """Delete 1–100 recent messages (requires Manage Messages)."""
    if not 1 <= amount <= 100:
        raise commands.BadArgument("Choose a number from 1 to 100.")
    deleted = await ctx.channel.purge(limit=amount + 1)
    confirmation = await ctx.send(f"Deleted {max(0, len(deleted) - 1)} message(s).")
    await confirmation.delete(delay=5)


@bot.command(name="purgeuser")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def purge_user(ctx, member: discord.Member, amount: int = 100):
    """Delete up to 100 recent messages from one member in this channel."""
    if not 1 <= amount <= 100:
        raise commands.BadArgument("Choose a number from 1 to 100.")
    matched = 0

    def matches_target(message):
        nonlocal matched
        if (
            message.id == ctx.message.id
            or message.author.id != member.id
            or matched >= amount
        ):
            return False
        matched += 1
        return True

    deleted = await ctx.channel.purge(
        limit=1000,
        check=matches_target,
        bulk=True,
    )
    await ctx.send(
        embed=make_embed(
            "🧹 Messages cleaned",
            f"Removed **{len(deleted)}** recent message(s) from {member.mention}.",
            discord.Color.orange(),
        ),
        delete_after=8,
    )


@bot.command()
@commands.guild_only()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Kick a member (requires Kick Members)."""
    if member == ctx.author:
        raise commands.BadArgument("You cannot kick yourself.")
    await member.kick(reason=f"{ctx.author}: {reason}")
    await ctx.send(f"Kicked {format_member(member)}. Reason: {reason}")


@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Ban a member (requires Ban Members)."""
    if member == ctx.author:
        raise commands.BadArgument("You cannot ban yourself.")
    await ctx.guild.ban(member, reason=f"{ctx.author}: {reason}")
    await ctx.send(f"Banned {format_member(member)}. Reason: {reason}")


@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason: str = "No reason provided"):
    """Unban a user by their Discord ID (requires Ban Members)."""
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
    except discord.NotFound as error:
        raise commands.BadArgument("That user is not currently banned here.") from error
    await ctx.send(
        embed=make_embed(
            "🔓 Ban removed",
            f"Unbanned **{discord.utils.escape_markdown(str(user))}** (`{user.id}`).",
            discord.Color.green(),
        )
    )


@bot.command()
@commands.guild_only()
@commands.has_guild_permissions(manage_nicknames=True)
async def nickname(ctx, member: discord.Member, *, name: str = None):
    """Set a member's nickname, or reset it if no name is supplied."""
    if name and len(name) > 32:
        raise commands.BadArgument("Nicknames must be 32 characters or fewer.")
    await member.edit(nick=name, reason=f"Nickname changed by {ctx.author}")
    action = f"set to **{discord.utils.escape_markdown(name)}**" if name else "reset"
    await ctx.send(
        embed=make_embed(
            "✏️ Nickname updated",
            f"{member.mention}'s nickname was {action}.",
            discord.Color.green(),
        )
    )


@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def timeout(
    ctx,
    member: discord.Member,
    duration_minutes: int,
    *,
    reason: str = "No reason provided",
):
    """Timeout a member for 1–40320 minutes (requires Moderate Members)."""
    if member == ctx.author:
        raise commands.BadArgument("You cannot timeout yourself.")
    if not 1 <= duration_minutes <= 40320:
        raise commands.BadArgument("Timeout duration must be from 1 to 40320 minutes.")
    await member.timeout(
        timedelta(minutes=duration_minutes),
        reason=f"{ctx.author}: {reason}",
    )
    await ctx.send(
        f"Timed out {member.mention} for {duration_minutes} minute(s). Reason: {reason}"
    )


@bot.command(name="untimeout")
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Remove a member's timeout (requires Moderate Members)."""
    await member.timeout(None, reason=f"{ctx.author}: {reason}")
    await ctx.send(f"Removed {member.mention}'s timeout. Reason: {reason}")


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason: str):
    """Record a persistent warning for a member (requires Manage Messages)."""
    if member.bot:
        raise commands.BadArgument("Warnings can only be recorded for human members.")
    with sqlite3.connect(DATABASE_PATH) as database:
        cursor = database.execute(
            """
            INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ctx.guild.id,
                member.id,
                ctx.author.id,
                reason[:1000],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        warning_id = cursor.lastrowid
    await ctx.send(
        f"Recorded warning #{warning_id} for {member.mention}. Reason: {reason[:1000]}"
    )
    try:
        await member.send(
            f"You received a warning in **{ctx.guild.name}**. Reason: {reason[:1000]}"
        )
    except discord.Forbidden:
        logger.info("Could not DM warned member %s", member.id)


@bot.command(name="warnings")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def warnings(ctx, member: discord.Member):
    """Show the latest 10 warnings for a member (requires Manage Messages)."""
    with sqlite3.connect(DATABASE_PATH) as database:
        records = database.execute(
            """
            SELECT id, moderator_id, reason, created_at
            FROM warnings
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (ctx.guild.id, member.id),
        ).fetchall()
    if not records:
        await ctx.send(f"{member.mention} has no recorded warnings.")
        return
    lines = [
        f"`#{warning_id}` <t:{int(datetime.fromisoformat(created_at).timestamp())}:R> "
        f"by <@{moderator_id}> — {reason[:250]}"
        for warning_id, moderator_id, reason, created_at in records
    ]
    embed = discord.Embed(
        title=f"Warnings for {member}",
        description="\n".join(lines),
        color=discord.Color.orange(),
    )
    await ctx.send(embed=embed)


@bot.command(name="clearwarnings")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def clear_warnings(ctx, member: discord.Member):
    """Delete all recorded warnings for a member (requires Manage Messages)."""
    with sqlite3.connect(DATABASE_PATH) as database:
        cursor = database.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, member.id),
        )
        deleted_count = cursor.rowcount
    await ctx.send(f"Removed {deleted_count} warning(s) for {member.mention}.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing required input. Try `{PREFIX}help {ctx.command}`.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(str(error) or f"Invalid input. Try `{PREFIX}help {ctx.command}`.")
        return
    if isinstance(error, commands.MissingPermissions):
        permissions = ", ".join(
            permission.replace("_", " ") for permission in error.missing_permissions
        )
        await ctx.send(f"You need the following permission(s): {permissions}.")
        return
    if isinstance(error, commands.BotMissingPermissions):
        permissions = ", ".join(
            permission.replace("_", " ") for permission in error.missing_permissions
        )
        await ctx.send(f"I need the following permission(s): {permissions}.")
        return
    if isinstance(error, commands.MissingRole):
        await ctx.send(f"You need the **{error.missing_role}** role to use this command.")
        return
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("This command can only be used in a server.")
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Please wait {error.retry_after:.1f} seconds before trying again.")
        return
    if isinstance(error, commands.CheckFailure):
        await ctx.send("You are not allowed to use this command here.")
        return
    if isinstance(error, commands.CommandInvokeError):
        original_error = error.original
        logger.error(
            "Command %s failed",
            ctx.command,
            exc_info=(
                type(original_error),
                original_error,
                original_error.__traceback__,
            ),
        )
        await ctx.send("The command failed. Check the bot's permissions and try again.")
        return

    logger.error(
        "Unexpected command error in %s",
        ctx.command,
        exc_info=(type(error), error, error.__traceback__),
    )
    await ctx.send("An unexpected error occurred while running that command.")


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=handler, log_level=logging.INFO)

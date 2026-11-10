# Victonite.Jr Discord Bot

A single-file Discord bot built with Python and discord.py. It includes polished
welcome messages, configurable profanity filtering, polls and suggestions,
reminders, server utilities, role management, channel controls, and moderation
with persistent warning history.

See [FEATURES.txt](FEATURES.txt) for the complete feature, command, permission,
configuration, and troubleshooting guide.

## Requirements

- Python 3.10 or later
- A Discord application and bot token
- The bot's **Message Content Intent** and **Server Members Intent** enabled in
  the Discord Developer Portal

## Setup

1. Clone this repository and enter its folder.
2. Create and activate a virtual environment:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows, activate it with `.venv\Scripts\activate`.

3. Install dependencies:

   ```sh
   python -m pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and set `DISCORD_TOKEN` to your bot token.
   Never commit `.env` or share your token.
5. Invite the bot to your server with only the permissions it needs. Review
   [FEATURES.txt](FEATURES.txt) for command-specific permission requirements.
6. Start the bot:

   ```sh
   python main.py
   ```

## Hosting

Run `python main.py` with Python 3.10+ on a host that supports persistent
processes. Configure the environment variables from `.env.example` in the
hosting provider's secret/environment-variable settings rather than committing
a `.env` file. The bot needs persistent local storage if warning history should
survive restarts; by default it stores warnings in `warnings.sqlite3`.

## Project files

- `main.py` — all Python bot implementation
- `FEATURES.txt` — detailed command and configuration guide
- `requirements.txt` — Python package dependencies
- `.env.example` — safe configuration template

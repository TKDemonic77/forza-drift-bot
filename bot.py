from dotenv import load_dotenv
load_dotenv()

import discord
from discord import app_commands
from discord.ext import commands
import json
import time
import os
import logging

# ---------------- LOGGING ---------------- #

logging.basicConfig(level=logging.INFO)

# ---------------- CONFIG ---------------- #

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "leaderboard.json"
COOLDOWN_SECONDS = 30

print("TOKEN LOADED:", bool(TOKEN))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable not set")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------- DATA ---------------- #

leaderboard = {
    "RWD": {},
    "AWD": {},
    "FWD": {}
}

DRIVE_TYPES = ["RWD", "AWD", "FWD"]
last_submit_time = {}

# ---------------- TRACKS ---------------- #

TRACKS = {
    "Brands Hatch": ["Grand Prix Circuit", "Indy Circuit"],
    "Circuit de Spa-Francorchamps": ["Full Circuit"],
    "Daytona International Speedway": ["Road Circuit", "Tri-Oval"],
    "Fujimi Kaido": ["Fujimi Circuit", "Reverse"],
    "Laguna Seca": ["Full Circuit", "Short Circuit"]
}

# ---------------- FILE HANDLING ---------------- #

def save_leaderboard():
    with open(DATA_FILE, "w") as f:
        json.dump(leaderboard, f, indent=4)

def load_leaderboard():
    if not os.path.exists(DATA_FILE):
        save_leaderboard()
        return

    global leaderboard
    try:
        with open(DATA_FILE, "r") as f:
            leaderboard.update(json.load(f))
    except json.JSONDecodeError:
        logging.warning("leaderboard.json corrupted — resetting")
        leaderboard = {"RWD": {}, "AWD": {}, "FWD": {}}
        save_leaderboard()

# ---------------- AUTOCOMPLETE ---------------- #

async def drive_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=d, value=d)
        for d in DRIVE_TYPES
        if current.lower() in d.lower()
    ]

async def track_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=t, value=t)
        for t in TRACKS
        if current.lower() in t.lower()
    ][:25]

async def layout_autocomplete(interaction: discord.Interaction, current: str):
    track = interaction.namespace.track
    if track not in TRACKS:
        return []

    return [
        app_commands.Choice(name=l, value=l)
        for l in TRACKS[track]
        if current.lower() in l.lower()
    ]

# ---------------- ADMIN CHECK ---------------- #

def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator

# ---------------- EVENTS ---------------- #

@bot.event
async def on_ready():
    load_leaderboard()
    synced = await tree.sync()
    logging.info("Synced commands:")
    for cmd in synced:
        logging.info(f"- {cmd.name}")
    logging.info(f"Logged in as {bot.user}")

# ---------------- SUBMIT ---------------- #

@tree.command(name="submit", description="Submit a drift score")
@app_commands.autocomplete(
    drive_type=drive_autocomplete,
    track=track_autocomplete,
    layout=layout_autocomplete
)
async def submit(
    interaction: discord.Interaction,
    drive_type: str,
    track: str,
    layout: str,
    score: int
):
    now = time.time()
    user = interaction.user.name

    if now - last_submit_time.get(user, 0) < COOLDOWN_SECONDS:
        await interaction.response.send_message(
            "Please wait before submitting again.",
            ephemeral=True
        )
        return

    if score < 1:
        await interaction.response.send_message(
            "Score must be greater than 0.",
            ephemeral=True
        )
        return

    if drive_type not in leaderboard:
        await interaction.response.send_message("Invalid drive type.", ephemeral=True)
        return

    if track not in TRACKS or layout not in TRACKS[track]:
        await interaction.response.send_message("Invalid track or layout.", ephemeral=True)
        return

    leaderboard.setdefault(drive_type, {}) \
               .setdefault(track, {}) \
               .setdefault(layout, {})

    current = leaderboard[drive_type][track][layout].get(user)

    if current is not None and score <= current:
        await interaction.response.send_message(
            f"Score not saved. Your PB here is {current:,}.",
            ephemeral=True
        )
        return

    leaderboard[drive_type][track][layout][user] = score
    last_submit_time[user] = now
    save_leaderboard()

    embed = discord.Embed(title="✅ Score Submitted", color=discord.Color.green())
    embed.add_field(name="Driver", value=user)
    embed.add_field(name="Drive", value=drive_type)
    embed.add_field(name="Track", value=track)
    embed.add_field(name="Layout", value=layout)
    embed.add_field(name="Score", value=f"{score:,}")
    await interaction.response.send_message(embed=embed)

# ---------------- LEADERBOARDS ---------------- #

@tree.command(name="leaderboard_drive", description="Best totals per drive type")
@app_commands.autocomplete(drive_type=drive_autocomplete)
async def leaderboard_drive(interaction: discord.Interaction, drive_type: str):
    totals = {}

    for track in leaderboard.get(drive_type, {}).values():
        for layout in track.values():
            for user, score in layout.items():
                totals[user] = totals.get(user, 0) + score

    sorted_scores = sorted(totals.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(title=f"{drive_type} Leaderboard", color=discord.Color.blue())
    for i, (u, s) in enumerate(sorted_scores[:10], 1):
        embed.add_field(name=f"#{i} {u}", value=f"{s:,}", inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="leaderboard_overall", description="Combined RWD + AWD + FWD leaderboard")
async def leaderboard_overall(interaction: discord.Interaction):
    totals = {}

    for drive in leaderboard.values():
        for track in drive.values():
            for layout in track.values():
                for user, score in layout.items():
                    totals[user] = totals.get(user, 0) + score

    sorted_scores = sorted(totals.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(title="🏆 Overall Leaderboard", color=discord.Color.gold())
    for i, (u, s) in enumerate(sorted_scores[:10], 1):
        embed.add_field(name=f"#{i} {u}", value=f"{s:,}", inline=False)

    await interaction.response.send_message(embed=embed)

# ---------------- MY STATS ---------------- #

@tree.command(name="my_stats", description="View your overall stats and rankings")
async def my_stats(interaction: discord.Interaction):
    user = interaction.user.name

    per_drive = {"RWD": 0, "AWD": 0, "FWD": 0}
    overall_total = 0

    for drive, tracks in leaderboard.items():
        for track in tracks.values():
            for layout in track.values():
                if user in layout:
                    per_drive[drive] += layout[user]
                    overall_total += layout[user]

    if overall_total == 0:
        await interaction.response.send_message("You have no recorded scores.")
        return

    def rank_for(total_map):
        sorted_users = sorted(total_map.items(), key=lambda x: x[1], reverse=True)
        return next(i for i, (u, _) in enumerate(sorted_users, 1) if u == user)

    overall_map = {}
    for drive in leaderboard.values():
        for track in drive.values():
            for layout in track.values():
                for u, s in layout.items():
                    overall_map[u] = overall_map.get(u, 0) + s

    embed = discord.Embed(title=f"📊 {user}'s Stats", color=discord.Color.purple())
    embed.add_field(
        name="Overall",
        value=f"{overall_total:,}  (#{rank_for(overall_map)})",
        inline=False
    )

    for d in DRIVE_TYPES:
        drive_map = {}
        for track in leaderboard.get(d, {}).values():
            for layout in track.values():
                for u, s in layout.items():
                    drive_map[u] = drive_map.get(u, 0) + s

        if user in drive_map:
            embed.add_field(
                name=d,
                value=f"{per_drive[d]:,}  (#{rank_for(drive_map)})",
                inline=True
            )

    await interaction.response.send_message(embed=embed)

# ---------------- ADMIN ---------------- #

@tree.command(name="delete_score", description="ADMIN: Delete a user's score")
@app_commands.autocomplete(
    drive_type=drive_autocomplete,
    track=track_autocomplete,
    layout=layout_autocomplete
)
async def delete_score(interaction: discord.Interaction, drive_type: str, track: str, layout: str, user: discord.User):
    if not is_admin(interaction):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return

    try:
        del leaderboard[drive_type][track][layout][user.name]
        save_leaderboard()
        await interaction.response.send_message("Score deleted.")
    except KeyError:
        await interaction.response.send_message("Score not found.", ephemeral=True)

@tree.command(name="reset_drive", description="ADMIN: Reset a drive leaderboard")
@app_commands.autocomplete(drive_type=drive_autocomplete)
async def reset_drive(interaction: discord.Interaction, drive_type: str):
    if not is_admin(interaction):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return

    leaderboard[drive_type] = {}
    save_leaderboard()
    await interaction.response.send_message(f"{drive_type} reset.")

@tree.command(name="reset_all", description="ADMIN: Reset ALL scores")
async def reset_all(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return

    leaderboard.clear()
    leaderboard.update({"RWD": {}, "AWD": {}, "FWD": {}})
    save_leaderboard()
    await interaction.response.send_message("All scores wiped.")

# ---------------- RUN ---------------- #

bot.run(TOKEN)
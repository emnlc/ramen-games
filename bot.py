import discord
from discord.ext import commands
from discord import app_commands

import subprocess
import docker

from dotenv import load_dotenv
import os

import json

load_dotenv()

docker_client = docker.from_env()
SERVER_LIST = "servers.json"
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GAME_MAP = {}

#################
## DISCORD BOT ##
#################
class Client(commands.Bot):
    async def on_ready(self):
        print(f"Logged on as {self.user.name}!")

        try:
            load_servers()
            guild = discord.Object(id=GUILD_ID)
            synced = await self.tree.sync(guild=guild)
            await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{len(GAME_MAP)} Servers"))
            print(f"Synced {len(synced)} commands to guild: {guild.id}")
        except Exception as e:
            print(f"Error syncing commands: {e}")
    
intents = discord.Intents.default()
intents.message_content = True
client = Client(command_prefix="!", intents=intents)
guild = discord.Object(id=GUILD_ID)

#######################
# SERVER LIST HELPERS #
#######################
def load_servers():
    try:
        with open(SERVER_LIST, "r") as file:
            GAME_MAP.update(json.load(file))
    except (FileNotFoundError, json.JSONDecodeError):
        GAME_MAP.clear()
        
def save_servers():
    with open(SERVER_LIST, "w") as file:
        json.dump(GAME_MAP, file)

######################
## START CONTAINERS ##
######################
@client.tree.command(name="start", description="Start game server", guild=guild)
async def start(interaction: discord.Interaction, game: str):
    if game.lower() not in GAME_MAP:
        await interaction.response.send_message(f"**{game.upper()}** server does not exist")
        return
    
    await interaction.response.defer(ephemeral=False)

    try:
        desired_container = GAME_MAP[game.lower()]
        
        # stop any running game server
        for g, c in GAME_MAP.items():
            if c != desired_container:
                container = docker_client.containers.get(c)
                if container.status == "running":
                    container.stop()
                    await interaction.followup.send(f"**{g.upper()}** shut down")
        
        container = docker_client.containers.get(desired_container)
        
        if container.status == "running":
            await interaction.followup.send(f"**{game.upper()}** is already running")
            return

        container.start()
        await interaction.followup.send(f"**{game.upper()}** is now running")
    except docker.errors.NotFound:
        await interaction.followup.send(f"**{game.upper()}** server does not exist")
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")
    
#####################
## STOP CONTAINERS ##
#####################
@client.tree.command(name="stop", description="Stop game server", guild=guild)
async def stop(interaction: discord.Interaction, game: str):
    if game.lower() not in GAME_MAP:
        await interaction.response.send_message(f"**{game.upper()}** server does not exist")
        return

    await interaction.response.defer(ephemeral=False)

    try:
        container_name = GAME_MAP[game.lower()]
        container = docker_client.containers.get(container_name)
        container.stop()
        result = container.wait()
        
        if result.get("StatusCode", 1) == 0:
            await interaction.followup.send(f"**{game.upper()}** server shut down")
        else:
            await interaction.followup.send(f"**{game.upper()}** exited, status {result['StatusCode']}.")
    except docker.errors.NotFound:
        await interaction.response.send_message(f"**{game.upper()}** server does not exist")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

######################
## CONTAINER STATUS ##
######################
@client.tree.command(name="status", description="Game server status", guild=guild)
async def status(interaction: discord.Interaction, game: str):    
    if game.lower() not in GAME_MAP:
        await interaction.response.send_message(f"**{game.upper()}** server does not exist")
        return

    try:
        container_name = GAME_MAP[game.lower()]
        container = docker_client.containers.get(container_name)
        status = container.status
        msg_status = "ON" if status == "running" else ("OFF" if status == "exited" else "UNKNOWN")
        
        await interaction.response.send_message(f"**{game.upper()}**: {msg_status}")
        
    except docker.errors.NotFound:
        await interaction.response.send_message(f"**{game.upper()}** server does not exist")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

################################
## LIST ALL SERVER CONTAINERS ##
################################
@client.tree.command(name="servers", description="List available game servers", guild=guild)
async def servers(interaction: discord.Interaction):
    res = "\n".join([f"**{container_name.upper()}**" for container_name in GAME_MAP.keys()])
    await interaction.response.send_message(f"Available Servers:\n{res}")

#########################
## LIST ALL CONTAINERS ##
#########################
@client.tree.command(name="containers", description="List running containers", guild=guild)
async def all_containers(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("You cannot run this command", ephemeral=True)
        return
    
    containers = docker_client.containers.list()
    
    if not containers:
        response = "Nothing running"
    else:
        response = "\n".join([f"**{container.name}**" for container in containers])
    
    await interaction.response.send_message(f"Running Containers:\n{response}", ephemeral=True)

####################
## ADD NEW SERVER ##
####################
@client.tree.command(name="add", description="Add server to server list", guild=guild)
async def add_server(interaction: discord.Interaction, game: str, container_name: str):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("You cannot run this command", ephemeral=True)
        return
    if game.lower() in GAME_MAP:
        await interaction.response.send_message(f"**{game.upper()}** already in server list", ephemeral=True)
        return
    
    GAME_MAP[game.lower()] = container_name
    res = "\n".join([f"`{container_name}`" for container_name in GAME_MAP.values()])
    await interaction.response.send_message(f"**{game.upper()}** added to server list\n\n**Updated Server List**\n{res}", ephemeral=True)
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{len(GAME_MAP)} Servers"))
    save_servers()

###################
## DELETE SERVER ##
###################
@client.tree.command(name="delete", description="Delete server from server list", guild=guild)
async def delete_server(interaction: discord.Interaction, game: str):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("You cannot run this command", ephemeral=True)
        return
    
    if game.lower() not in GAME_MAP:
        await interaction.response.send_message(f"**{game.upper()}** not in server list", ephemeral=True)
        return

    del GAME_MAP[game.lower()]
    res = "\n".join([f"`{container_name}`" for container_name in GAME_MAP.values()])
    await interaction.response.send_message(f"**{game.upper()}** deleted from server list\n\n**Updated Server List**\n{res}", ephemeral=True)
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{len(GAME_MAP)} Servers"))
    save_servers()

client.run(TOKEN)
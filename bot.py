import os
import discord
from discord.ext import commands
from discord import app_commands
import discord.app_commands
import asyncio
import yt_dlp as youtube_dl
from dotenv import load_dotenv
from collections import deque

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'auto',
}
ffmpeg_options = {
    'options': '-vn',
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

music_queues = {}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream)
        )
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(
            discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data
        )

def play_next(interaction, error):
    if error:
        print(f'Error in playback: {error}')
    guild = interaction.guild
    guild_id = guild.id
    voice_client = guild.voice_client
    if voice_client and guild_id in music_queues and music_queues[guild_id]:
        next_song = music_queues[guild_id].popleft()
        try:
            voice_client.play(
                next_song['player'],
                after=lambda e: play_next(interaction, e) if not e else print(f'Player error: {e}')
            )
            coro = interaction.followup.send(f'Now playing: {next_song["title"]}')
            asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop())
        except Exception as e:
            print(f'Error playing next song: {e}')
            coro = interaction.followup.send(f'An error occurred: {e}')
            asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop())
    elif voice_client:
        coro = interaction.followup.send('No more songs in the queue.')
        asyncio.run_coroutine_threadsafe(coro, asyncio.get_event_loop())
    else:
        print('Voice client not connected.')


@bot.tree.command(name='play', description='Plays a song from YouTube')
@app_commands.describe(url='The URL or search term for the song')
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    
    user = interaction.user
    guild = interaction.guild

    if not user.voice:
        await interaction.followup.send("You are not connected to a voice channel.")
        return

    channel = user.voice.channel

    voice_client = guild.voice_client

    if not voice_client:
        voice_client = await channel.connect()

    guild_id = guild.id

    if guild_id not in music_queues:
        music_queues[guild_id] = deque()

    async with interaction.channel.typing():
        try:
            player = await YTDLSource.from_url(url, loop=asyncio.get_event_loop(), stream=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred while processing the song: {e}")
            return

        song = {
            'title': player.title,
            'player': player
        }

        if voice_client.is_playing() or voice_client.is_paused():
            music_queues[guild_id].append(song)
            embed = discord.Embed(
                title="Song Queued",
                description=f"[{player.title}]({player.url})",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=player.data.get('thumbnail'))
            embed.set_footer(text=f"Position in queue: {len(music_queues[guild_id])}")
            await interaction.followup.send(embed=embed)

        else:
            try:
                voice_client.play(
                    player, after=lambda e: play_next(interaction, e) if not e else print(f'Player error: {e}')
                )
                embed = discord.Embed(
                    title="Now Playing",
                    description=f"[{player.title}]({player.url})",
                    color=discord.Color.green()
                )
                embed.set_thumbnail(url=player.data.get('thumbnail'))
                embed.set_footer(
                    text=f"Requested by {interaction.user.display_name}",
                    icon_url=interaction.user.avatar.url if interaction.user.avatar else None
                )
                await interaction.followup.send(embed=embed)
            except Exception as e:
                await interaction.followup.send(f'An error occurred while playing the song: {e}')
                print(f'Error: {e}')

@bot.tree.command(name='stop', description='Stops the song')
async def stop(interaction: discord.Interaction):
    guild = interaction.guild
    voice_client = guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("Song stopped.")
    else:
        await interaction.response.send_message("No music is playing.")

@bot.tree.command(name='skip', description='Skips the current song')
async def skip(interaction: discord.Interaction):
    guild = interaction.guild
    voice_client = guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("Song skipped.")
    else:
        await interaction.response.send_message("No music is playing.")

@bot.tree.command(name='queue', description='Displays the current music queue')
async def queue_(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in music_queues and music_queues[guild_id]:
        queue_list = list(music_queues[guild_id])
        msg = 'Current queue:\n'
        for idx, song in enumerate(queue_list, 1):
            msg += f"{idx}. {song['title']}\n"
        await interaction.response.send_message(msg)
    else:
        await interaction.response.send_message("The queue is empty.")

@bot.tree.command(name='clear', description='Clears the music queue')
async def clear(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in music_queues:
        music_queues[guild_id].clear()
        await interaction.response.send_message("Queue cleared.")
    else:
        await interaction.response.send_message("The queue is already empty.")

@bot.tree.command(name='quit', description='Disconnects the bot from voice channel')
async def quit(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = interaction.guild.voice_client
    if voice_client:
        await voice_client.disconnect()
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        await interaction.response.send_message("Disconnected from the voice channel.")
    else:
        await interaction.response.send_message("Bot is not connected to any voice channel.")

@bot.tree.command(name='golira', description='Uga buga?!')
async def golira(interaction: discord.Interaction):
    golira = """
    ▒▒▒▒▒▄██████████▄▒▒▒▒▒
    ▒▒▒▄██████████████▄▒▒▒
    ▒▒██████████████████▒▒
    ▒▐███▀▀▀▀▀██▀▀▀▀▀███▌▒
    ▒███▒▒▌■▐▒▒▒▒▌■▐▒▒███▒
    ▒▐██▄▒▀▀▀▒▒▒▒▀▀▀▒▄██▌▒
    ▒▒▀████▒▄▄▒▒▄▄▒████▀▒▒
    ▒▒▐███▒▒▒▀▒▒▀▒▒▒███▌▒▒
    ▒▒███▒▒▒▒▒▒▒▒▒▒▒▒███▒▒
    ▒▒▒██▒▒▀▀▀▀▀▀▀▀▒▒██▒▒▒
    ▒▒▒▐██▄▒▒▒▒▒▒▒▒▄██▌▒▒▒
    ▒▒▒▒▀████████████▀▒▒▒▒
    """
    await interaction.response.send_message(golira)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'Logged in as {bot.user}')

bot.run(TOKEN)

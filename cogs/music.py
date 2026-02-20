import asyncio
import re
import logging
from typing import Optional
from urllib.parse import urlparse

import discord
import wavelink
from discord import app_commands
from discord.ext import commands
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from config import Config

logger = logging.getLogger('MusicBot')

URL_REGEX = re.compile(r'https?://(?:www\.)?.+')

class MusicQueue:
    def __init__(self):
        self._queue = []
        self.position = 0
        self.loop_mode = "off"  # off, track, queue
        
    @property
    def is_empty(self):
        return len(self._queue) == 0
    
    @property
    def current_track(self):
        if 0 <= self.position < len(self._queue):
            return self._queue[self.position]
        return None
    
    @property
    def next_track(self):
        if self.loop_mode == "track":
            return self.current_track
        
        next_pos = self.position + 1
        if next_pos >= len(self._queue):
            if self.loop_mode == "queue":
                next_pos = 0
            else:
                return None
        
        if 0 <= next_pos < len(self._queue):
            return self._queue[next_pos]
        return None
    
    def add(self, track):
        if len(self._queue) >= Config.MAX_QUEUE_SIZE:
            return False
        self._queue.append(track)
        return True
    
    def add_many(self, tracks):
        added = 0
        for track in tracks:
            if self.add(track):
                added += 1
        return added
    
    def remove(self, index):
        if 0 <= index < len(self._queue):
            removed = self._queue.pop(index)
            if index <= self.position and self.position > 0:
                self.position -= 1
            return removed
        return None
    
    def clear(self):
        self._queue.clear()
        self.position = 0
        
    def skip(self, count=1):
        self.position += count - 1
        if self.position >= len(self._queue):
            if self.loop_mode == "queue":
                self.position = 0
            else:
                self.position = len(self._queue)
    
    def previous(self):
        if self.position > 0:
            self.position -= 2
            return True
        return False
    
    def shuffle(self):
        import random
        current = self.current_track
        remaining = self._queue[self.position + 1:]
        random.shuffle(remaining)
        self._queue = self._queue[:self.position + 1] + remaining
    
    def get_queue_list(self, start=0, limit=10):
        end = min(start + limit, len(self._queue))
        return self._queue[start:end], len(self._queue)
    
    def jump(self, position):
        if 0 <= position < len(self._queue):
            self.position = position - 1
            return True
        return False


class MusicPlayer:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        self.queue = MusicQueue()
        self.volume = Config.DEFAULT_VOLUME
        self.text_channel = None
        self._destroyed = False
        self._24_7_mode = False
        self._voice_channel_id = None
        self._last_activity = None
        
    async def destroy(self):
        self._destroyed = True
        player = wavelink.Pool.get_node().get_player(self.guild_id)
        if player:
            await player.disconnect()


class SongSelectView(discord.ui.View):
    """View для вибору пісні з результатів пошуку"""
    def __init__(self, tracks, ctx, music_cog, timeout=60):
        super().__init__(timeout=timeout)
        self.tracks = tracks[:5]  # Максимум 5 результатів
        self.ctx = ctx
        self.music_cog = music_cog
        self.selected_track = None
        
        # Додаємо кнопки для кожного треку
        for i, track in enumerate(self.tracks):
            duration = music_cog.format_duration(track.length)
            title = track.title[:30] + "..." if len(track.title) > 30 else track.title
            button = discord.ui.Button(
                label=f"{i+1}. {title}",
                description=f"{track.author} • {duration}",
                style=discord.ButtonStyle.primary if i == 0 else discord.ButtonStyle.secondary,
                custom_id=f"song_select_{i}"
            )
            button.callback = self.make_callback(i)
            self.add_item(button)
        
        # Кнопка скасування
        cancel_btn = discord.ui.Button(
            label="❌ Скасувати",
            style=discord.ButtonStyle.danger,
            custom_id="song_cancel"
        )
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)
    
    def make_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                await interaction.response.send_message("❌ Це не ваш вибір!", ephemeral=True)
                return
            
            self.selected_track = self.tracks[index]
            await interaction.response.defer()
            self.stop()
        return callback
    
    async def cancel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Це не ваш вибір!", ephemeral=True)
            return
        
        await interaction.response.edit_message(content="❌ Вибір скасовано.", view=None)
        self.stop()


class MusicControlsView(discord.ui.View):
    """View з кнопками керування музикою"""
    def __init__(self, music_cog, guild_id, timeout=None):
        super().__init__(timeout=timeout)
        self.music_cog = music_cog
        self.guild_id = guild_id
        self.message = None
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Перевірка чи користувач у голосовому каналі"""
        player = wavelink.Pool.get_node().get_player(self.guild_id)
        if not player:
            await interaction.response.send_message("❌ Бот не у голосовому каналі!", ephemeral=True)
            return False
        
        if not interaction.user.voice or interaction.user.voice.channel != player.channel:
            await interaction.response.send_message("❌ Ви маєте бути у тому ж голосовому каналі!", ephemeral=True)
            return False
        
        return True
    
    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary, custom_id="prev_btn")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        music_player = self.music_cog.get_player(self.guild_id)
        
        if music_player.queue.previous():
            player = wavelink.Pool.get_node().get_player(self.guild_id)
            if player:
                await player.skip()
            await interaction.followup.send("⏮️ Попередній трек!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Немає попереднього треку!", ephemeral=True)
    
    @discord.ui.button(label="⏯️", style=discord.ButtonStyle.primary, custom_id="play_pause_btn")
    async def play_pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = wavelink.Pool.get_node().get_player(self.guild_id)
        
        if player.paused:
            await player.pause(False)
            await interaction.followup.send("▶️ Музику продовжено!", ephemeral=True)
        else:
            await player.pause(True)
            await interaction.followup.send("⏸️ Музику призупинено!", ephemeral=True)
    
    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary, custom_id="skip_btn")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = wavelink.Pool.get_node().get_player(self.guild_id)
        
        if player and player.playing:
            await player.skip()
            await interaction.followup.send("⏭️ Трек пропущено!", ephemeral=True)
        else:
            await interaction.followup.send("❌ Зараз нічого не грає!", ephemeral=True)
    
    @discord.ui.button(label="🔁", style=discord.ButtonStyle.secondary, custom_id="loop_btn")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        music_player = self.music_cog.get_player(self.guild_id)
        
        modes = ["off", "track", "queue"]
        current_idx = modes.index(music_player.queue.loop_mode)
        next_mode = modes[(current_idx + 1) % len(modes)]
        music_player.queue.loop_mode = next_mode
        
        emojis = {"off": "❌", "track": "🔂", "queue": "🔁"}
        await interaction.followup.send(f"{emojis[next_mode]} Режим повтору: **{next_mode}**", ephemeral=True)
    
    @discord.ui.button(label="🔀", style=discord.ButtonStyle.secondary, custom_id="shuffle_btn")
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        music_player = self.music_cog.get_player(self.guild_id)
        
        if music_player.queue.is_empty:
            await interaction.followup.send("❌ Черга порожня!", ephemeral=True)
            return
        
        music_player.queue.shuffle()
        await interaction.followup.send("🔀 Чергу перемішано!", ephemeral=True)
    
    @discord.ui.button(label="⏹️", style=discord.ButtonStyle.danger, custom_id="stop_btn")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        player = wavelink.Pool.get_node().get_player(self.guild_id)
        
        if player:
            music_player = self.music_cog.get_player(self.guild_id)
            music_player.queue.clear()
            await player.stop()
            await player.disconnect()
            
            if self.guild_id in self.music_cog.players:
                del self.music_cog.players[self.guild_id]
            
            await interaction.followup.send("⏹️ Музику зупинено!", ephemeral=True)
    
    @discord.ui.button(label="📋", style=discord.ButtonStyle.secondary, custom_id="queue_btn")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        music_player = self.music_cog.get_player(self.guild_id)
        
        if music_player.queue.is_empty:
            await interaction.followup.send("❌ Черга порожня!", ephemeral=True)
            return
        
        tracks, total = music_player.queue.get_queue_list(0, 10)
        
        embed = discord.Embed(
            title="📋 Черга відтворення",
            color=discord.Color.blue()
        )
        
        description = []
        for i, track in enumerate(tracks):
            prefix = "▶️ " if i == music_player.queue.position else f"{i + 1}. "
            duration = self.music_cog.format_duration(track.length)
            title = track.title[:40] + "..." if len(track.title) > 40 else track.title
            description.append(f"{prefix}**{title}** ({duration})")
        
        embed.description = "\n".join(description)
        embed.set_footer(text=f"Всього: {total} треків | Режим: {music_player.queue.loop_mode}")
        
        await interaction.followup.send(embed=embed, ephemeral=True)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players = {}
        self.spotify = None
        self.control_views = {}  # guild_id -> MusicControlsView
        
        # Ініціалізація Spotify
        if Config.SPOTIFY_CLIENT_ID and Config.SPOTIFY_CLIENT_SECRET:
            try:
                self.spotify = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=Config.SPOTIFY_CLIENT_ID,
                        client_secret=Config.SPOTIFY_CLIENT_SECRET
                    )
                )
                logger.info("Spotify API ініціалізовано")
            except Exception as e:
                logger.error(f"Помилка ініціалізації Spotify: {e}")
        
        # Запускаємо підключення до Lavalink
        bot.loop.create_task(self.connect_nodes())
        
        # Запускаємо перевірку 24/7 режиму
        bot.loop.create_task(self._24_7_checker())
    
    async def connect_nodes(self):
        await self.bot.wait_until_ready()
        
        try:
            node = wavelink.Node(
                uri=f"{'https' if Config.LAVALINK_SSL else 'http'}://{Config.LAVALINK_HOST}:{Config.LAVALINK_PORT}",
                password=Config.LAVALINK_PASSWORD
            )
            await wavelink.Pool.connect(client=self.bot, nodes=[node])
            logger.info(f"Підключено до Lavalink: {Config.LAVALINK_HOST}")
        except Exception as e:
            logger.error(f"Помилка підключення до Lavalink: {e}")
    
    async def _24_7_checker(self):
        """Перевірка та автоматичне перепідключення для 24/7 режиму"""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                for guild_id, music_player in list(self.players.items()):
                    if music_player._24_7_mode and music_player._voice_channel_id:
                        player = wavelink.Pool.get_node().get_player(guild_id)
                        guild = self.bot.get_guild(guild_id)
                        
                        if guild and not player:
                            # Бот відключився, але 24/7 увімкнено - перепідключаємось
                            voice_channel = guild.get_channel(music_player._voice_channel_id)
                            if voice_channel:
                                try:
                                    await voice_channel.connect(cls=wavelink.Player)
                                    logger.info(f"24/7: Перепідключено до {voice_channel.name}")
                                    
                                    # Відновлюємо відтворення якщо була черга
                                    if not music_player.queue.is_empty and music_player.queue.current_track:
                                        new_player = wavelink.Pool.get_node().get_player(guild_id)
                                        if new_player:
                                            await new_player.play(music_player.queue.current_track)
                                except Exception as e:
                                    logger.error(f"24/7: Помилка перепідключення: {e}")
                
                await asyncio.sleep(30)  # Перевірка кожні 30 секунд
            except Exception as e:
                logger.error(f"24/7 checker error: {e}")
                await asyncio.sleep(30)
    
    def get_player(self, guild_id) -> MusicPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = MusicPlayer(self.bot, guild_id)
        return self.players[guild_id]
    
    async def send_response(self, ctx: commands.Context, content=None, *, embed=None, ephemeral=False):
        """Універсальна функція для відправки відповіді"""
        try:
            if ctx.interaction:
                if ctx.interaction.response.is_done():
                    await ctx.interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
                else:
                    await ctx.interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
            else:
                await ctx.send(content=content, embed=embed)
        except discord.HTTPException as e:
            if e.code == 40060:
                try:
                    await ctx.interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
                except Exception as e2:
                    logger.error(f"Не вдалося відправити повідомлення: {e2}")
            else:
                raise
    
    def get_spotify_tracks(self, query: str):
        """Конвертує Spotify посилання в пошукові запити для YouTube"""
        if not self.spotify:
            return None
            
        try:
            if "track" in query:
                track_id = query.split("/track/")[1].split("?")[0]
                track = self.spotify.track(track_id)
                search_query = f"{track['name']} {' '.join([a['name'] for a in track['artists']])}"
                return [search_query]
                
            elif "playlist" in query:
                playlist_id = query.split("/playlist/")[1].split("?")[0]
                results = self.spotify.playlist_tracks(playlist_id)
                tracks = []
                for item in results['items']:
                    track = item['track']
                    if track:
                        search_query = f"{track['name']} {' '.join([a['name'] for a in track['artists']])}"
                        tracks.append(search_query)
                return tracks
                
            elif "album" in query:
                album_id = query.split("/album/")[1].split("?")[0]
                album = self.spotify.album(album_id)
                tracks = []
                for track in album['tracks']['items']:
                    search_query = f"{track['name']} {' '.join([a['name'] for a in track['artists']])}"
                    tracks.append(search_query)
                return tracks
                
        except Exception as e:
            logger.error(f"Spotify помилка: {e}")
            return None
        
        return None
    
    async def search_tracks(self, query: str, requester: discord.Member, max_results: int = 5):
        """Пошук треків з різних джерел"""
        
        # Перевіряємо чи це Spotify
        if "spotify.com" in query and self.spotify:
            spotify_tracks = self.get_spotify_tracks(query)
            if spotify_tracks:
                tracks = []
                for search_query in spotify_tracks[:50]:
                    try:
                        results = await wavelink.Playable.search(search_query, source=wavelink.TrackSource.YouTube)
                        if results:
                            track = results[0]
                            track.requester = requester
                            tracks.append(track)
                    except:
                        continue
                return tracks
            return None
        
        # Звичайний пошук або YouTube/SoundCloud
        try:
            if URL_REGEX.match(query):
                # Пряме посилання - повертаємо одразу
                if "soundcloud.com" in query:
                    results = await wavelink.Playable.search(query, source=wavelink.TrackSource.SoundCloud)
                else:
                    # YouTube або інші джерела
                    results = await wavelink.Playable.search(query)
                
                if results:
                    if isinstance(results, wavelink.Playlist):
                        for track in results.tracks:
                            track.requester = requester
                        return list(results.tracks)
                    else:
                        for track in results:
                            track.requester = requester
                        return results
                return None
            else:
                # Пошук по назві (YouTube) - повертаємо кілька результатів для вибору
                results = await wavelink.Playable.search(f"ytsearch:{query}")
                
                if results:
                    tracks = []
                    for track in results[:max_results]:
                        track.requester = requester
                        tracks.append(track)
                    return tracks
                return None
            
        except Exception as e:
            logger.error(f"Помилка пошуку: {e}")
            return None
    
    async def play_next(self, player: wavelink.Player):
        """Програває наступний трек"""
        guild_id = player.guild.id
        music_player = self.get_player(guild_id)
        
        next_track = music_player.queue.next_track
        
        if next_track:
            music_player.queue.position += 1
            await player.play(next_track)
            
            # Оновлюємо повідомлення з кнопками
            if music_player.text_channel:
                embed = self.create_now_playing_embed(next_track, music_player.queue)
                await self.send_or_update_controls(music_player.text_channel, embed, guild_id)
        else:
            # Черга закінчилась
            if not music_player._24_7_mode:
                await player.disconnect()
                if guild_id in self.players:
                    del self.players[guild_id]
                # Видаляємо кнопки
                if guild_id in self.control_views:
                    del self.control_views[guild_id]
    
    async def send_or_update_controls(self, channel, embed, guild_id):
        """Відправляє або оновлює повідомлення з кнопками керування"""
        try:
            # Видаляємо старе повідомлення з кнопками якщо є
            if guild_id in self.control_views:
                old_view = self.control_views[guild_id]
                if old_view.message:
                    try:
                        await old_view.message.delete()
                    except:
                        pass
            
            # Створюємо нові кнопки
            view = MusicControlsView(self, guild_id)
            self.control_views[guild_id] = view
            
            # Відправляємо нове повідомлення
            view.message = await channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Помилка відправки кнопок: {e}")
    
    def create_now_playing_embed(self, track: wavelink.Playable, queue: MusicQueue):
        embed = discord.Embed(
            title="▶️ Зараз грає",
            description=f"**[{track.title}]({track.uri})**",
            color=discord.Color.green()
        )
        
        if hasattr(track, 'author') and track.author:
            embed.add_field(name="Виконавець", value=track.author, inline=True)
        
        duration = self.format_duration(track.length)
        embed.add_field(name="Тривалість", value=duration, inline=True)
        
        if hasattr(track, 'requester') and track.requester:
            embed.add_field(name="Замовив", value=track.requester.mention, inline=True)
        
        # Прогрес бар
        if track.length:
            embed.add_field(
                name="Прогрес",
                value=f"0:00 / {duration}",
                inline=False
            )
        
        # Обкладинка
        if hasattr(track, 'artwork') and track.artwork:
            embed.set_thumbnail(url=track.artwork)
        
        # Інформація про чергу
        remaining = len(queue._queue) - queue.position - 1
        if remaining > 0:
            embed.set_footer(text=f"У черзі ще {remaining} трек(ів) | Режим: {queue.loop_mode}")
        else:
            embed.set_footer(text=f"Режим: {queue.loop_mode}")
            
        return embed
    
    def format_duration(self, ms: int) -> str:
        if not ms:
            return "∞"
        seconds = ms // 1000
        minutes = seconds // 60
        hours = minutes // 60
        if hours > 0:
            return f"{hours}:{minutes % 60:02d}:{seconds % 60:02d}"
        return f"{minutes}:{seconds % 60:02d}"
    
    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """Обробник закінчення треку"""
        if not payload.player:
            return
            
        await self.play_next(payload.player)
    
    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        """Обробник помилки треку"""
        logger.error(f"Помилка відтворення: {payload.exception}")
        if payload.player:
            await self.play_next(payload.player)
    
    @commands.hybrid_command(name="play", description="Програти музику з YouTube, Spotify або SoundCloud")
    @app_commands.describe(query="Назва пісні або посилання")
    async def play(self, ctx: commands.Context, *, query: str):
        """Програти музику"""
        
        # Перевірка голосового каналу
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await self.send_response(ctx, "❌ Ви маєте бути у голосовому каналі!", ephemeral=True)
        
        voice_channel = ctx.author.voice.channel
        
        # Підключаємось до каналу
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player:
            try:
                player = await voice_channel.connect(cls=wavelink.Player)
            except Exception as e:
                return await self.send_response(ctx, f"❌ Не вдалось підключитись: {e}", ephemeral=True)
        elif player.channel != voice_channel:
            await player.move_to(voice_channel)
        
        # Ініціалізуємо плеєр для сервера
        music_player = self.get_player(ctx.guild.id)
        music_player.text_channel = ctx.channel
        music_player._voice_channel_id = voice_channel.id
        
        # Пошук треків
        if ctx.interaction:
            await ctx.interaction.response.defer()
        
        # Якщо це URL - додаємо одразу, інакше показуємо вибір
        is_url = URL_REGEX.match(query)
        tracks = await self.search_tracks(query, ctx.author, max_results=5 if not is_url else 1)
        
        if not tracks:
            return await self.send_response(ctx, "❌ Нічого не знайдено!", ephemeral=True)
        
        # Якщо це URL або тільки один результат - додаємо одразу
        if is_url or len(tracks) == 1:
            track = tracks[0]
            music_player.queue.add(track)
            
            embed = discord.Embed(
                title="✅ Додано в чергу",
                description=f"**[{track.title}]({track.uri})**",
                color=discord.Color.blue()
            )
            if hasattr(track, 'author'):
                embed.add_field(name="Виконавець", value=track.author, inline=True)
            embed.add_field(name="Тривалість", value=self.format_duration(track.length), inline=True)
            embed.add_field(name="Позиція в черзі", value=len(music_player.queue._queue), inline=True)
            
            await self.send_response(ctx, embed=embed)
        else:
            # Показуємо вибір пісні
            view = SongSelectView(tracks, ctx, self)
            embed = discord.Embed(
                title="🔍 Результати пошуку",
                description=f"Оберіть пісню для відтворення:",
                color=discord.Color.blue()
            )
            
            select_msg = await ctx.send(embed=embed, view=view)
            await view.wait()
            
            # Видаляємо повідомлення з вибором
            try:
                await select_msg.delete()
            except:
                pass
            
            if not view.selected_track:
                return  # Користувач скасував
            
            track = view.selected_track
            music_player.queue.add(track)
            
            embed = discord.Embed(
                title="✅ Додано в чергу",
                description=f"**[{track.title}]({track.uri})**",
                color=discord.Color.blue()
            )
            if hasattr(track, 'author'):
                embed.add_field(name="Виконавець", value=track.author, inline=True)
            embed.add_field(name="Тривалість", value=self.format_duration(track.length), inline=True)
            embed.add_field(name="Позиція в черзі", value=len(music_player.queue._queue), inline=True)
            
            await ctx.send(embed=embed)
        
        # Якщо нічого не грає - починаємо
        if not player.playing:
            await self.play_next(player)
    
    @commands.hybrid_command(name="24_7", description="Увімкнути/вимкнути режим 24/7")
    @app_commands.describe(enabled="Увімкнути (true) або вимкнути (false)")
    async def mode_24_7(self, ctx: commands.Context, enabled: bool = True):
        """Режим 24/7 - бот залишається в каналі навіть коли нічого не грає"""
        music_player = self.get_player(ctx.guild.id)
        music_player._24_7_mode = enabled
        
        # Зберігаємо поточний голосовий канал
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        if player and player.channel:
            music_player._voice_channel_id = player.channel.id
        
        status = "✅ увімкнено" if enabled else "❌ вимкнено"
        embed = discord.Embed(
            title="🕐 Режим 24/7",
            description=f"Режим 24/7 {status}",
            color=discord.Color.green() if enabled else discord.Color.red()
        )
        
        if enabled:
            embed.add_field(
                name="Примітка",
                value="Бот буде автоматично перепідключатися до голосового каналу",
                inline=False
            )
        
        await self.send_response(ctx, embed=embed)
    
    @commands.hybrid_command(name="skip", description="Пропустити поточний трек")
    async def skip(self, ctx: commands.Context):
        """Пропустити трек"""
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player or not player.playing:
            return await self.send_response(ctx, "❌ Зараз нічого не грає!", ephemeral=True)
        
        await player.skip()
        await self.send_response(ctx, "⏭️ Трек пропущено!")
    
    @commands.hybrid_command(name="stop", description="Зупинити музику та очистити чергу")
    async def stop(self, ctx: commands.Context):
        """Зупинити музику"""
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player:
            return await self.send_response(ctx, "❌ Бот не у голосовому каналі!", ephemeral=True)
        
        music_player = self.get_player(ctx.guild.id)
        music_player.queue.clear()
        music_player._24_7_mode = False  # Вимикаємо 24/7 при зупинці
        
        await player.stop()
        await player.disconnect()
        del self.players[ctx.guild.id]
        
        # Видаляємо кнопки
        if ctx.guild.id in self.control_views:
            del self.control_views[ctx.guild.id]
        
        await self.send_response(ctx, "⏹️ Музику зупинено та чергу очищено!")
    
    @commands.hybrid_command(name="pause", description="Призупинити музику")
    async def pause(self, ctx: commands.Context):
        """Призупинити"""
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player or not player.playing:
            return await self.send_response(ctx, "❌ Зараз нічого не грає!", ephemeral=True)
        
        if player.paused:
            return await self.send_response(ctx, "❌ Музика вже призупинена!", ephemeral=True)
        
        await player.pause(True)
        await self.send_response(ctx, "⏸️ Музику призупинено!")
    
    @commands.hybrid_command(name="resume", description="Продовжити музику")
    async def resume(self, ctx: commands.Context):
        """Продовжити"""
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player:
            return await self.send_response(ctx, "❌ Бот не у голосовому каналі!", ephemeral=True)
        
        if not player.paused:
            return await self.send_response(ctx, "❌ Музика вже грає!", ephemeral=True)
        
        await player.pause(False)
        await self.send_response(ctx, "▶️ Музику продовжено!")
    
    @commands.hybrid_command(name="queue", description="Показати чергу")
    async def queue(self, ctx: commands.Context, page: int = 1):
        """Показати чергу"""
        music_player = self.get_player(ctx.guild.id)
        
        if music_player.queue.is_empty:
            return await self.send_response(ctx, "❌ Черга порожня!", ephemeral=True)
        
        tracks, total = music_player.queue.get_queue_list((page - 1) * 10, 10)
        
        embed = discord.Embed(
            title="📋 Черга відтворення",
            color=discord.Color.blue()
        )
        
        description = []
        start_idx = (page - 1) * 10
        
        for i, track in enumerate(tracks):
            idx = start_idx + i
            prefix = "▶️ " if idx == music_player.queue.position else f"{idx + 1}. "
            duration = self.format_duration(track.length)
            title = track.title[:40] + "..." if len(track.title) > 40 else track.title
            description.append(f"{prefix}**{title}** ({duration})")
        
        embed.description = "\n".join(description)
        embed.set_footer(text=f"Сторінка {page}/{(total // 10) + 1} | Всього: {total} треків")
        
        await self.send_response(ctx, embed=embed)
    
    @commands.hybrid_command(name="loop", description="Увімкнути/вимкнути повтор")
    @app_commands.describe(mode="Режим повтору: off, track, queue")
    async def loop(self, ctx: commands.Context, mode: str = "off"):
        """Режим повтору"""
        if mode not in ["off", "track", "queue"]:
            return await self.send_response(ctx, "❌ Доступні режими: `off`, `track`, `queue`", ephemeral=True)
        
        music_player = self.get_player(ctx.guild.id)
        music_player.queue.loop_mode = mode
        
        emojis = {"off": "❌", "track": "🔂", "queue": "🔁"}
        await self.send_response(ctx, f"{emojis[mode]} Режим повтору: **{mode}**")
    
    @commands.hybrid_command(name="shuffle", description="Перемішати чергу")
    async def shuffle(self, ctx: commands.Context):
        """Перемішати"""
        music_player = self.get_player(ctx.guild.id)
        
        if music_player.queue.is_empty:
            return await self.send_response(ctx, "❌ Черга порожня!", ephemeral=True)
        
        music_player.queue.shuffle()
        await self.send_response(ctx, "🔀 Чергу перемішано!")
    
    @commands.hybrid_command(name="volume", description="Змінити гучність (0-100)")
    @app_commands.describe(volume="Рівень гучності")
    async def volume(self, ctx: commands.Context, volume: int):
        """Гучність"""
        if not 0 <= volume <= 100:
            return await self.send_response(ctx, "❌ Гучність має бути від 0 до 100!", ephemeral=True)
        
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player:
            return await self.send_response(ctx, "❌ Бот не у голосовому каналі!", ephemeral=True)
        
        await player.set_volume(volume)
        music_player = self.get_player(ctx.guild.id)
        music_player.volume = volume
        
        bar = "█" * (volume // 10) + "░" * (10 - volume // 10)
        await self.send_response(ctx, f"🔊 Гучність: `{bar}` {volume}%")
    
    @commands.hybrid_command(name="nowplaying", description="Інформація про поточний трек")
    async def nowplaying(self, ctx: commands.Context):
        """Зараз грає"""
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player or not player.current:
            return await self.send_response(ctx, "❌ Зараз нічого не грає!", ephemeral=True)
        
        music_player = self.get_player(ctx.guild.id)
        embed = self.create_now_playing_embed(player.current, music_player.queue)
        await self.send_response(ctx, embed=embed)
    
    @commands.hybrid_command(name="remove", description="Видалити трек з черги")
    @app_commands.describe(position="Позиція треку в черзі")
    async def remove(self, ctx: commands.Context, position: int):
        """Видалити трек"""
        music_player = self.get_player(ctx.guild.id)
        
        if position < 1 or position > len(music_player.queue._queue):
            return await self.send_response(ctx, "❌ Невірна позиція!", ephemeral=True)
        
        removed = music_player.queue.remove(position - 1)
        if removed:
            await self.send_response(ctx, f"🗑️ Видалено: **{removed.title}**")
        else:
            await self.send_response(ctx, "❌ Не вдалось видалити трек!", ephemeral=True)
    
    @commands.hybrid_command(name="jump", description="Перейти до конкретного треку")
    async def jump(self, ctx: commands.Context, position: int):
        """Перейти до треку"""
        music_player = self.get_player(ctx.guild.id)
        
        if not music_player.queue.jump(position - 1):
            return await self.send_response(ctx, "❌ Невірна позиція!", ephemeral=True)
        
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        if player:
            await player.skip()
        
        await self.send_response(ctx, f"⏭️ Перехід до треку #{position}")
    
    @commands.hybrid_command(name="disconnect", description="Відключити бота від каналу")
    async def disconnect(self, ctx: commands.Context):
        """Відключити"""
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player:
            return await self.send_response(ctx, "❌ Бот не у голосовому каналі!", ephemeral=True)
        
        music_player = self.get_player(ctx.guild.id)
        music_player._24_7_mode = False
        
        if ctx.guild.id in self.players:
            del self.players[ctx.guild.id]
        
        # Видаляємо кнопки
        if ctx.guild.id in self.control_views:
            del self.control_views[ctx.guild.id]
        
        await player.disconnect()
        await self.send_response(ctx, "👋 Бот відключено!")
    
    @commands.hybrid_command(name="controls", description="Показати панель керування з кнопками")
    async def controls(self, ctx: commands.Context):
        """Показати панель керування"""
        player = wavelink.Pool.get_node().get_player(ctx.guild.id)
        
        if not player or not player.current:
            return await self.send_response(ctx, "❌ Зараз нічого не грає!", ephemeral=True)
        
        music_player = self.get_player(ctx.guild.id)
        embed = self.create_now_playing_embed(player.current, music_player.queue)
        
        # Відправляємо з кнопками
        view = MusicControlsView(self, ctx.guild.id)
        self.control_views[ctx.guild.id] = view
        view.message = await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
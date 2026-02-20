import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    # ОНОВЛЕНО: Новий робочий сервер
    LAVALINK_HOST = os.getenv('LAVALINK_HOST', 'lavalinkv4.serenetia.com')
    LAVALINK_PORT = int(os.getenv('LAVALINK_PORT', '443'))
    LAVALINK_PASSWORD = os.getenv('LAVALINK_PASSWORD', 'https://dsc.gg/ajidevserver')
    LAVALINK_SSL = os.getenv('LAVALINK_SSL', 'true').lower() == 'true'
    
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    DEFAULT_VOLUME = 50
    MAX_QUEUE_SIZE = 100
    YTDL_PROXY = os.getenv('YTDL_PROXY', '')
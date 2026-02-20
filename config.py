import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Discord
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    # Lavalink (для Railway використовуйте публічний сервер або власний)
    # Можна використати безкоштовні публічні сервери або встановити свій
    LAVALINK_HOST = os.getenv('LAVALINK_HOST', 'lavalink-v4.teramont.net')
    LAVALINK_PORT = int(os.getenv('LAVALINK_PORT', '443'))
    LAVALINK_PASSWORD = os.getenv('LAVALINK_PASSWORD', 'eHKuFcz67k4lBS64')
    LAVALINK_SSL = os.getenv('LAVALINK_SSL', 'true').lower() == 'true'
    
    # Spotify API (для пошуку та плейлистів)
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    # Налаштування бота
    DEFAULT_VOLUME = 50
    MAX_QUEUE_SIZE = 100
    
    # Проксі (опціонально, для обходу блокувань)
    YTDL_PROXY = os.getenv('YTDL_PROXY', '')
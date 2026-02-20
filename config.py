import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Discord
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    # Lavalink (для Railway використовуйте публічний сервер або власний)
    # Можна використати безкоштовні публічні сервери або встановити свій
    # 
    # РОБОЧІ ПУБЛІЧНІ СЕРВЕРИ (оновлено 20.02.2026):
    # 
    # Варіант 1 (Рекомендовано):
    # LAVALINK_HOST = 'lavalinkv4.serenetia.com'
    # LAVALINK_PORT = 443
    # LAVALINK_PASSWORD = 'https://dsc.gg/ajidevserver'
    # LAVALINK_SSL = 'true'
    #
    # Варіант 2:
    # LAVALINK_HOST = 'lavalink.jirayu.net'
    # LAVALINK_PORT = 443
    # LAVALINK_PASSWORD = 'youshallnotpass'
    # LAVALINK_SSL = 'true'
    #
    # Варіант 3:
    # LAVALINK_HOST = 'lava-v3.millohost.my.id'
    # LAVALINK_PORT = 443
    # LAVALINK_PASSWORD = 'https://discord.gg/mjS5J2K3ep'
    # LAVALINK_SSL = 'true'
    #
    # Старий сервер (НЕ ПРАЦЮЄ):
    # lavalink-v4.teramont.net - більше не доступний!
    
    LAVALINK_HOST = os.getenv('LAVALINK_HOST', 'lavalinkv4.serenetia.com')
    LAVALINK_PORT = int(os.getenv('LAVALINK_PORT', '443'))
    LAVALINK_PASSWORD = os.getenv('LAVALINK_PASSWORD', 'https://dsc.gg/ajidevserver')
    LAVALINK_SSL = os.getenv('LAVALINK_SSL', 'true').lower() == 'true'
    
    # Spotify API (для пошуку та плейлистів)
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    # Налаштування бота
    DEFAULT_VOLUME = 50
    MAX_QUEUE_SIZE = 100
    
    # Проксі (опціонально, для обходу блокувань)
    YTDL_PROXY = os.getenv('YTDL_PROXY', '')
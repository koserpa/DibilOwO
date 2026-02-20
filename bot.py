import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

from config import Config

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MusicBot')

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # Обов'язково для префіксних команд!
        intents.voice_states = True
        
        super().__init__(
            command_prefix='!',  # Префікс тільки !
            intents=intents,
            help_command=None,
            case_insensitive=True  # Команди не чутливі до регістру
        )
        
    async def setup_hook(self):
        # Завантаження когів
        await self.load_extension('cogs.music')
        logger.info("Музичний ког завантажено")
        
        # Синхронізація слеш-команд (опціонально)
        try:
            synced = await self.tree.sync()
            logger.info(f"Синхронізовано {len(synced)} слеш-команд")
        except Exception as e:
            logger.error(f"Помилка синхронізації: {e}")
    
    async def on_ready(self):
        logger.info(f'{self.user} успішно запущено!')
        logger.info(f'ID бота: {self.user.id}')
        logger.info(f'Префікс команд: !')
        activity = discord.Activity(
            type=discord.ActivityType.listening,
            name="музику | !play"
        )
        await self.change_presence(activity=activity)

    async def on_command_error(self, ctx, error):
        """Обробник помилок команд"""
        if isinstance(error, commands.CommandNotFound):
            return
        
        # Ігноруємо помилки, які вже були оброблені
        if isinstance(error, commands.CommandInvokeError):
            if isinstance(error.original, discord.HTTPException):
                if error.original.code == 40060:  # Interaction already acknowledged
                    logger.warning(f"Interaction вже був acknowledged для команди {ctx.command}")
                    return
        
        embed = discord.Embed(
            title="❌ Помилка",
            color=discord.Color.red()
        )
        
        if isinstance(error, commands.MissingPermissions):
            embed.description = "У вас недостатньо прав для цієї команди!"
        elif isinstance(error, commands.BotMissingPermissions):
            embed.description = "У бота недостатньо прав для виконання цієї дії!"
        elif isinstance(error, commands.MissingRequiredArgument):
            embed.description = f"Відсутній обов'язковий аргумент: `{error.param.name}`"
        elif isinstance(error, commands.CheckFailure):
            embed.description = "У вас недостатньо прав для цієї команди!"
        elif isinstance(error, commands.CommandOnCooldown):
            embed.description = f"Зачекайте {error.retry_after:.1f} секунд перед наступним використанням!"
        else:
            embed.description = f"Сталася помилка: {str(error)}"
            logger.error(f"Помилка команди: {error}", exc_info=True)
        
        # Перевіряємо чи interaction вже був acknowledged (для слеш-команд)
        try:
            if ctx.interaction:
                if not ctx.interaction.response.is_done():
                    await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await ctx.interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
        except discord.HTTPException as e:
            if e.code == 40060:
                logger.warning("Не вдалося відправити повідомлення про помилку: interaction вже acknowledged")
            else:
                logger.error(f"Помилка відправки повідомлення про помилку: {e}")
        except Exception as e:
            logger.error(f"Неочікувана помилка в on_command_error: {e}")
    
    async def on_message(self, message):
        """Обробник повідомлень - для префіксних команд"""
        # Ігноруємо повідомлення від ботів
        if message.author.bot:
            return
        
        # Обробляємо команди
        await self.process_commands(message)

def main():
    if not Config.TOKEN:
        logger.error("DISCORD_TOKEN не знайдено! Перевірте змінні середовища.")
        sys.exit(1)
    
    bot = MusicBot()
    
    try:
        bot.run(Config.TOKEN, reconnect=True)
    except discord.LoginFailure:
        logger.error("Невірний токен Discord!")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Критична помилка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
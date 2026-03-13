import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import TYPE_CHECKING
from src.modules.thread_favorites.services.favorites_service import FavoritesService

if TYPE_CHECKING:
    from src.bot import MyBot

logger = logging.getLogger(__name__)


class ContextMenuCog(commands.Cog):
    def __init__(self, bot: "MyBot", favorites_service: FavoritesService):
        self.bot = bot
        self.favorites_service = favorites_service
        self.favorite_thread_ctx_menu = app_commands.ContextMenu(
            name="⭐ 收藏此帖",
            callback=self.favorite_this_thread,
        )
        self.bot.tree.add_command(self.favorite_thread_ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.favorite_thread_ctx_menu.name, type=self.favorite_thread_ctx_menu.type
        )

    async def favorite_this_thread(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        """Adds a thread to the user's favorites."""
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "❌ 这个命令只能在帖子（子区）里使用。", ephemeral=True
            )
            return

        thread = interaction.channel
        try:
            success = await self.favorites_service.add_favorite(
                interaction.user.id, thread
            )
            if success:
                await interaction.response.send_message(
                    f"✅ 帖子 **{thread.name}** 已成功添加到你的收藏夹！",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"🤔 帖子 **{thread.name}** 已在你的收藏夹中。", ephemeral=True
                )
        except Exception:
            logger.error(f"收藏帖子失败 (thread_id: {thread.id})", exc_info=True)
            await interaction.response.send_message(
                "操作失败，发生了未知错误。", ephemeral=True
            )


async def setup(bot: "MyBot"):
    if hasattr(bot, "favorites_service"):
        await bot.add_cog(ContextMenuCog(bot, bot.favorites_service))  # type: ignore
    else:
        logger.error(
            "FavoritesService 未在机器人实例上初始化，无法加载 ContextMenuCog。"
        )

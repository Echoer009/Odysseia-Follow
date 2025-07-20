import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import TYPE_CHECKING

# --- Service Imports ---
from src.modules.author_follow.services.author_follow_service import AuthorFollowService
from src.modules.user_profile_feature.services.profile_service import ProfileService

# --- UI Imports ---
from .views import MainMenuView

if TYPE_CHECKING:
    from src.bot import OdysseiaBot

logger = logging.getLogger(__name__)

class UserProfileCog(commands.Cog):
    def __init__(self, bot: "OdysseiaBot"):
        self.bot = bot
        self.author_follow_service: AuthorFollowService = bot.author_follow_service
        self.profile_service: ProfileService = bot.profile_service

    @app_commands.command(name="我的关注", description="在私信中管理您关注的作者和频道订阅")
    async def my_follows(self, interaction: discord.Interaction):
        try:
            # Defer interaction to avoid timeout, and make it thinking
            await interaction.response.defer(ephemeral=True, thinking=True)

            # Create the main menu view
            view = MainMenuView(self)
            embed = view.create_embed()

            # Send the view to the user's DMs
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except discord.Forbidden:
            # This exception is less likely now but kept for safety.
            await interaction.followup.send(
                "❌ 我无法给你发送私信。请检查你的隐私设置（允许来自服务器成员的私信）然后重试。",
                ephemeral=True
            )
        except Exception as e:
            log_context = {
                'user_id': interaction.user.id,
                'guild_id': interaction.guild_id,
                'command': '/我的关注'
            }
            logger.error("执行 /我的关注 命令失败", extra=log_context, exc_info=True)
            # Check if the interaction is still valid before sending a followup
            if not interaction.is_expired():
                await interaction.followup.send("发生了一个未知错误，请联系管理员。", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(UserProfileCog(bot))
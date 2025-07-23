import discord
from discord import app_commands
from discord.ext import commands
from src.modules.author_follow.services.author_follow_service import AuthorFollowService, FollowResult, UnfollowResult
import traceback
import asyncio
import os
import logging
from typing import TYPE_CHECKING
from src.core.utils import retry_on_discord_error

if TYPE_CHECKING:
    from src.bot import OdysseiaBot

logger = logging.getLogger(__name__)

# --- 辅助方法，用于生成响应 ---
async def _handle_follow_response(interaction: discord.Interaction, result: FollowResult, author: discord.User | discord.Member):
    """根据关注结果发送响应消息"""
    author_name = author.display_name if author else "未知作者"
    if result == FollowResult.SUCCESS:
        await interaction.response.send_message(f"✅ 成功关注作者 **{author_name}**！", ephemeral=True)
    elif result == FollowResult.ALREADY_FOLLOWED:
        await interaction.response.send_message(f"🤔 您已经关注过作者 **{author_name}** 了。", ephemeral=True)
    elif result == FollowResult.CANNOT_FOLLOW_SELF:
        await interaction.response.send_message("您不能关注自己~", ephemeral=True)

async def _handle_unfollow_response(interaction: discord.Interaction, result: UnfollowResult, author: discord.User | discord.Member):
    """根据取关结果发送响应消息"""
    author_name = author.display_name if author else "未知作者"
    if result == UnfollowResult.SUCCESS:
        await interaction.response.send_message(f"✅ 已取消关注作者 **{author_name}**。", ephemeral=True)
    elif result == UnfollowResult.NOT_FOLLOWED:
        await interaction.response.send_message("🤔 您之前没有关注过这位作者。", ephemeral=True)

# --- AuthorTracker Cog ---
class AuthorTracker(commands.Cog):
    def __init__(self, bot: "OdysseiaBot"):
        self.bot = bot
        self.author_follow_service: AuthorFollowService = bot.author_follow_service

        # --- 正确的右键菜单注册方式 ---
        self.follow_menu = app_commands.ContextMenu(
            name="⭐ 关注此消息作者",
            callback=self.follow_this_author_context,
        )
        self.unfollow_menu = app_commands.ContextMenu(
            name="➖ 取关此消息作者",
            callback=self.unfollow_this_author_context,
        )
        self.bot.tree.add_command(self.follow_menu)
        self.bot.tree.add_command(self.unfollow_menu)

    async def cog_unload(self):
        """当 Cog 被卸载时，清理命令，以支持热重载"""
        self.bot.tree.remove_command(self.follow_menu.name, type=self.follow_menu.type)
        self.bot.tree.remove_command(self.unfollow_menu.name, type=self.unfollow_menu.type)

    # --- 右键菜单命令的回调方法  ---
    async def follow_this_author_context(self, interaction: discord.Interaction, message: discord.Message):
        try:
            author = message.author
            result = await self.author_follow_service.follow_author(interaction.user.id, author.id, author.name)
            await _handle_follow_response(interaction, result, author)
        except Exception as e:
            log_context = {
                'user_id': interaction.user.id,
                'guild_id': interaction.guild_id,
                'target_user_id': message.author.id,
                'command': '右键菜单: 关注此消息作者'
            }
            logger.error("右键菜单命令执行失败", extra=log_context, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    async def unfollow_this_author_context(self, interaction: discord.Interaction, message: discord.Message):
        try:
            author = message.author
            result = await self.author_follow_service.unfollow_author(interaction.user.id, author.id)
            await _handle_unfollow_response(interaction, result, author)
        except Exception as e:
            log_context = {
                'user_id': interaction.user.id,
                'guild_id': interaction.guild_id,
                'target_user_id': message.author.id,
                'command': '右键菜单: 取关此消息作者'
            }
            logger.error("右键菜单命令执行失败", extra=log_context, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        try:
            if thread.parent_id not in self.bot.resource_channel_ids:
                return
            
            log_context = {
                'thread_id': thread.id,
                'thread_name': thread.name,
                'guild_id': thread.guild.id,
                'channel_id': thread.parent_id,
                'author_id': thread.owner_id
            }
            logger.info("在受监控频道中检测到新帖子", extra=log_context)

            author_id = thread.owner_id
            if not author_id:
                return

            author = thread.owner or await retry_on_discord_error(
                lambda: self.bot.fetch_user(author_id),
                f"获取作者信息 (ID: {author_id})"
            )
            if not author:
                logger.warning("无法找到作者用户对象", extra={'author_id': author_id})
                return
            
            await self.author_follow_service.process_new_thread(
                thread.id, author.id, author.name, thread.created_at
            )
            logger.info("服务层已处理新帖子", extra=log_context)

            follower_ids = await self.author_follow_service.get_author_followers(author_id)
            if not follower_ids:
                return
                
            await self.ghost_ping_users(thread, follower_ids)
        except Exception as e:
            log_context = {'thread_id': thread.id, 'guild_id': thread.guild.id}
            logger.error("处理 on_thread_create (作者关注) 时出错", extra=log_context, exc_info=True)

    async def ghost_ping_users(self, thread: discord.Thread, user_ids: list[int]):
        try:
            initial_delay = int(os.getenv('GHOST_PING_INITIAL_DELAY_SECONDS', '5'))
            chunk_size = int(os.getenv('GHOST_PING_CHUNK_SIZE', '50'))
            chunk_delay = float(os.getenv('GHOST_PING_CHUNK_DELAY_SECONDS', '1.5'))
        except (ValueError, TypeError):
            initial_delay, chunk_size, chunk_delay = 5, 50, 1.5

        log_context = {
            'thread_id': thread.id,
            'guild_id': thread.guild.id,
            'total_users': len(user_ids),
            'chunk_size': chunk_size,
            'delay': initial_delay
        }
        logger.info("准备为作者关注者发送幽灵提及", extra=log_context)
        await asyncio.sleep(initial_delay)
        
        for i in range(0, len(user_ids), chunk_size):
            chunk = user_ids[i:i + chunk_size]
            ping_message = " ".join([f"<@{user_id}>" for user_id in chunk])
            try:
                message = await retry_on_discord_error(
                    lambda: thread.send(ping_message),
                    f"发送作者关注幽灵提及到频道 {thread.id}"
                )
                await retry_on_discord_error(
                    lambda: message.delete(),
                    f"删除作者关注幽灵提及在频道 {thread.id}"
                )
                log_context['chunk_user_ids'] = chunk
                logger.info("成功为作者关注者发送幽灵提及", extra=log_context)
            except discord.errors.DiscordServerError:
                logger.error(f"为频道 {thread.id} 发送或删除作者关注幽灵提及最终失败", extra=log_context, exc_info=True)
            except Exception as e:
                log_context['chunk_user_ids'] = chunk
                logger.error("为作者关注发送幽灵提及失败", extra=log_context, exc_info=True)
            
            if len(user_ids) > chunk_size:
                await asyncio.sleep(chunk_delay)

    @app_commands.command(name="关注本贴作者", description="关注当前帖子的作者以接收作者新帖子的更新通知")
    @app_commands.checks.cooldown(1, float(os.getenv('FOLLOW_COMMAND_COOLDOWN_SECONDS', '5.0')))
    async def follow_author(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("此命令只能在论坛帖子中使用。", ephemeral=True)
            return
        try:
            author = interaction.channel.owner or await retry_on_discord_error(
                lambda: self.bot.fetch_user(interaction.channel.owner_id),
                f"获取帖子作者信息 (ID: {interaction.channel.owner_id})"
            )
            if not author:
                await interaction.response.send_message("❌ 无法找到该帖子的作者信息，操作失败。", ephemeral=True)
                return

            result = await self.author_follow_service.follow_author(interaction.user.id, author.id, author.name)
            await _handle_follow_response(interaction, result, author)
        except Exception as e:
            log_context = {
                'user_id': interaction.user.id,
                'guild_id': interaction.guild_id,
                'channel_id': interaction.channel_id,
                'command': '/关注本贴作者'
            }
            logger.error("斜杠命令执行失败", extra=log_context, exc_info=True)
            await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    @app_commands.command(name="取关本贴作者", description="取消关注当前帖子的作者")
    @app_commands.checks.cooldown(1, float(os.getenv('FOLLOW_COMMAND_COOLDOWN_SECONDS', '5.0')))
    async def unfollow_author(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ 此命令只能在论坛帖子中使用。", ephemeral=True)
            return
        try:
            author = interaction.channel.owner or await retry_on_discord_error(
                lambda: self.bot.fetch_user(interaction.channel.owner_id),
                f"获取帖子作者信息 (ID: {interaction.channel.owner_id})"
            )
            result = await self.author_follow_service.unfollow_author(interaction.user.id, interaction.channel.owner_id)
            await _handle_unfollow_response(interaction, result, author)
        except Exception as e:
            log_context = {
                'user_id': interaction.user.id,
                'guild_id': interaction.guild_id,
                'channel_id': interaction.channel_id,
                'command': '/取关本贴作者'
            }
            logger.error("斜杠命令执行失败", extra=log_context, exc_info=True)
            await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

async def setup(bot: "OdysseiaBot"):
    await bot.add_cog(AuthorTracker(bot))
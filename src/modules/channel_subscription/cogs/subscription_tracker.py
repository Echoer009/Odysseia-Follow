import discord
from discord.ext import commands
import logging
import os
import asyncio
from typing import List, TYPE_CHECKING

# --- Service and View Imports ---
from src.core.utils import retry_on_discord_error
from src.modules.channel_subscription.services.subscription_service import SubscriptionService
from src.modules.user_profile_feature.cogs.views import SubscriptionManageView, SubscriptionMenuView

if TYPE_CHECKING:
    from src.bot import OdysseiaBot
    from src.modules.user_profile_feature.cogs.profile_cog import UserProfileCog

logger = logging.getLogger(__name__)

class SubscriptionTracker(commands.Cog, name="SubscriptionTracker"):
    def __init__(self, bot: "OdysseiaBot"):
        self.bot = bot
        self.subscription_service: SubscriptionService = bot.subscription_service

    async def get_target_forum_channels(self) -> List[discord.ForumChannel]:
        """获取所有配置的、机器人可见的论坛频道"""
        channels = []
        if not self.bot.guild_ids:
            return []
        for guild_id in self.bot.guild_ids:
            guild = self.bot.get_guild(guild_id)
            if guild:
                channels.extend(ch for ch in guild.forums if ch.id in self.bot.resource_channel_ids)
        return channels

    async def create_subscription_embed(self, user_id: int, channel_id: int) -> discord.Embed:
        """创建显示用户频道订阅设置的 Embed"""
        channel = self.bot.get_channel(channel_id)
        channel_name = channel.name if channel else f"未知频道 (ID: {channel_id})"
        
        subscription = await self.subscription_service.get_subscription(user_id, channel_id)
        
        is_subscribed = subscription.get('is_subscribed', False) if subscription else False
        followed_kws = subscription.get('followed_keywords', []) if subscription else []
        blocked_kws = subscription.get('blocked_keywords', []) if subscription else []

        status_text = "✅ **已关注**" if is_subscribed else "❌ **未关注**"
        
        embed = discord.Embed(
            title=f"管理频道: {channel_name}",
            description=(
                f"当前状态: {status_text}\n\n"
                "**通知规则:**\n"
                "1. **关键词模式**: 设置关注词后，仅当新帖标题或标签匹配时才会通知。\n"
                "2. **全量模式**: 不设置任何关注词时，接收所有新帖通知。\n"
                "3. **屏蔽词优先**: 任何匹配屏蔽词的帖子都**不会**被通知。"
            ),
            color=discord.Color.blue()
        )
        embed.add_field(
            name="✅ 关注的关键词 (匹配则通知)",
            value=f"`{'`, `'.join(followed_kws)}`" if followed_kws else "未设置 (接收此频道全部通知)",
            inline=False
        )
        embed.add_field(
            name="🚫 屏蔽的关键词 (匹配则忽略)",
            value=f"`{'`, `'.join(blocked_kws)}`" if blocked_kws else "无",
            inline=False
        )
        embed.set_footer(text="使用下面的按钮来管理关键词或取消关注。")
        return embed

    async def send_main_subscription_view(self, interaction: discord.Interaction, profile_cog: 'UserProfileCog'):
        """发送频道订阅主菜单，显示用户已订阅的频道"""
        await interaction.response.defer() # Defer here to handle all cases
        
        try:
            subscribed_channels_data = await self.bot.db.get_subscribed_channels_for_user(interaction.user.id)
            
            # 从 Discord API 获取频道对象
            subscribed_channels = []
            for sub_data in subscribed_channels_data:
                channel = self.bot.get_channel(sub_data['channel_id'])
                if channel:
                    subscribed_channels.append(channel)

            view = SubscriptionMenuView(self, profile_cog, interaction.user.id, subscribed_channels)
            embed = view.create_embed()
            
            await interaction.edit_original_response(embed=embed, view=view, content=None)
        except Exception as e:
            log_context = {'user_id': interaction.user.id, 'guild_id': interaction.guild_id}
            logger.error("发送频道订阅主菜单失败", extra=log_context, exc_info=True)
            await interaction.edit_original_response(content="❌ 加载您的频道订阅列表失败，请稍后再试。", embed=None, view=None)

    async def send_subscription_manage_ui(self, interaction: discord.Interaction, user_id: int, channel_id: int, profile_cog: 'UserProfileCog'):
        """发送订阅管理界面"""
        embed = await self.create_subscription_embed(user_id, channel_id)
        view = SubscriptionManageView(self, profile_cog, user_id, channel_id)
        
        message = await interaction.edit_original_response(embed=embed, view=view, content=None)
        view.message = message

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id not in self.bot.resource_channel_ids:
            return

        try:
            users_to_notify = await self.subscription_service.process_new_thread(thread)
            if users_to_notify:
                await self.ghost_ping_users(thread, users_to_notify)
        except Exception as e:
            log_context = {'thread_id': thread.id, 'guild_id': thread.guild.id}
            logger.error("处理 on_thread_create (频道订阅) 时出错", extra=log_context, exc_info=True)

    async def ghost_ping_users(self, thread: discord.Thread, user_ids: list[int]):
        try:
            initial_delay = int(os.getenv('GHOST_PING_INITIAL_DELAY_SECONDS', '3'))
            chunk_size = int(os.getenv('GHOST_PING_CHUNK_SIZE', '50'))
            chunk_delay = float(os.getenv('GHOST_PING_CHUNK_DELAY_SECONDS', '1.5'))
        except (ValueError, TypeError):
            initial_delay, chunk_size, chunk_delay = 3, 50, 1.5

        log_context = {
            'thread_id': thread.id,
            'guild_id': thread.guild.id,
            'total_users': len(user_ids),
            'chunk_size': chunk_size,
            'delay': initial_delay
        }
        logger.info("准备为频道订阅者发送幽灵提及", extra=log_context)
        await asyncio.sleep(initial_delay)
        
        for i in range(0, len(user_ids), chunk_size):
            chunk = user_ids[i:i + chunk_size]
            ping_message = " ".join([f"<@{user_id}>" for user_id in chunk])
            try:
                try:
                    # 使用重试逻辑发送消息
                    message = await retry_on_discord_error(
                        lambda: thread.send(ping_message),
                        operation_name=f"发送幽灵提及到频道 {thread.id} (Chunk {i//chunk_size + 1})"
                    )
                    # 使用重试逻辑删除消息
                    await retry_on_discord_error(
                        lambda: message.delete(),
                        operation_name=f"删除幽灵提及在频道 {thread.id} (Chunk {i//chunk_size + 1})"
                    )
                    log_context['chunk_user_ids'] = chunk
                    logger.info("成功为频道订阅发送幽灵提及", extra=log_context)
                except discord.errors.DiscordServerError:
                    # 如果重试最终失败，只记录错误，不中断循环
                    logger.error(f"为频道 {thread.id} 发送或删除幽灵提及最终失败", extra=log_context, exc_info=True)
            except discord.Forbidden:
                logger.error("因权限不足，为频道订阅发送幽灵提及失败", extra=log_context, exc_info=True)
                break
            except Exception as e:
                log_context['chunk_user_ids'] = chunk
                logger.error("为频道订阅发送幽灵提及失败", extra=log_context, exc_info=True)
            
            if len(user_ids) > chunk_size:
                await asyncio.sleep(chunk_delay)


async def setup(bot: "OdysseiaBot"):
    await bot.add_cog(SubscriptionTracker(bot))
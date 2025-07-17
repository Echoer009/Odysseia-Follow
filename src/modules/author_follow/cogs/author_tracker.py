import discord
from discord import app_commands
from discord.ext import commands
from src.modules.author_follow.services.author_follow_service import AuthorFollowService, FollowResult, UnfollowResult
import traceback
import asyncio
import os
import logging

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
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.author_follow_service: AuthorFollowService = bot.author_follow_service

        # --- 正确的右键菜单注册方式 ---
        # 1. 创建 ContextMenu 对象并绑定回调
        self.follow_menu = app_commands.ContextMenu(
            name="关注此消息作者",
            callback=self.follow_this_author_context,
        )
        self.unfollow_menu = app_commands.ContextMenu(
            name="取关此消息作者",
            callback=self.unfollow_this_author_context,
        )
        # 2. 将它们添加到机器人的命令树
        self.bot.tree.add_command(self.follow_menu)
        self.bot.tree.add_command(self.unfollow_menu)

    async def cog_unload(self):
        """当 Cog 被卸载时，清理命令，以支持热重载"""
        self.bot.tree.remove_command(self.follow_menu.name, type=self.follow_menu.type)
        self.bot.tree.remove_command(self.unfollow_menu.name, type=self.unfollow_menu.type)

    # --- 右键菜单命令的回调方法 (注意：这里没有装饰器) ---
    async def follow_this_author_context(self, interaction: discord.Interaction, message: discord.Message):
        try:
            author = message.author
            result = await self.author_follow_service.follow_author(interaction.user.id, author.id, author.name)
            await _handle_follow_response(interaction, result, author)
        except Exception as e:
            logger.error(f"消息命令 '关注此消息作者' 执行失败: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    async def unfollow_this_author_context(self, interaction: discord.Interaction, message: discord.Message):
        try:
            author = message.author
            result = await self.author_follow_service.unfollow_author(interaction.user.id, author.id)
            await _handle_unfollow_response(interaction, result, author)
        except Exception as e:
            logger.error(f"消息命令 '取关此消息作者' 执行失败: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        try:
            # --- 修改这里，从 bot 对象获取配置 ---
            if thread.parent_id not in self.bot.resource_channel_ids:
                return
            
            logger.info(f"检测到受监控频道中的新帖子: '{thread.name}' (ID: {thread.id})")

            author_id = thread.owner_id
            if not author_id:
                return

            author = thread.owner
            if not author:
                try:
                    author = await self.bot.fetch_user(author_id)
                except discord.NotFound:
                    logger.error(f"无法找到 ID 为 {author_id} 的用户，无法记录帖子。")
                    return
            
            # --- 调用服务层来处理业务逻辑 ---
            await self.author_follow_service.process_new_thread(
                thread.id, author.id, author.name, thread.created_at
            )
            logger.info(f"服务层已处理新帖子，作者: {author.name} ({author.id})")

            # --- 通知逻辑 ---
            parent_name = thread.parent.name if thread.parent else "未知频道"
            logger.info(f"作者 {author.name} ({author_id}) 在频道 {parent_name} 发布了新帖: {thread.name}")
            follower_ids = await self.author_follow_service.get_author_followers(author_id)
            if not follower_ids:
                logger.info(f"作者 {author_id} 没有关注者，无需通知。")
                return
            await self.ghost_ping_users(thread, follower_ids)
        except Exception as e:
            logger.error(f"处理 on_thread_create 事件时发生错误 (线程ID: {thread.id})", exc_info=True)

    async def ghost_ping_users(self, thread: discord.Thread, user_ids: list[int]):
        # --- Ghost Ping 风险提示 ---
        # Ghost Ping (发送提及消息后立刻删除) 是一种灰色地带行为。
        # 虽然可以有效通知用户，但过度使用或被滥用可能导致机器人被Discord限制或封禁。
        # 以下措施有助于降低风险：
        # 1. 合理的分块大小 (chunk_size)
        # 2. 在每次发送之间设置延迟 (chunk_delay)
        # 3. 仅在绝对必要时使用
        # 4. 确保用户是自愿选择接收通知的 (通过关注功能)
        # ---------------------------------
        
        # 从环境变量获取配置，提供合理的默认值
        try:
            initial_delay = int(os.getenv('GHOST_PING_INITIAL_DELAY_SECONDS', '5'))
            chunk_size = int(os.getenv('GHOST_PING_CHUNK_SIZE', '50'))
            chunk_delay = float(os.getenv('GHOST_PING_CHUNK_DELAY_SECONDS', '1.5'))
        except (ValueError, TypeError):
            initial_delay, chunk_size, chunk_delay = 5, 50, 1.5

        logger.info(f"准备在帖子 {thread.id} 中通知 {len(user_ids)} 位用户。初始延迟: {initial_delay}s, 分块大小: {chunk_size}, 块间延迟: {chunk_delay}s。")
        await asyncio.sleep(initial_delay)
        
        for i in range(0, len(user_ids), chunk_size):
            chunk = user_ids[i:i + chunk_size]
            ping_message = " ".join([f"<@{user_id}>" for user_id in chunk])
            try:
                message = await thread.send(ping_message)
                await message.delete()
                logger.info(f"成功发送并删除了对 {len(chunk)} 位用户的提及。")
            except discord.Forbidden:
                logger.error(f"发送幽灵提及失败：权限不足。请确保机器人在频道 {thread.parent.name} ({thread.parent_id}) 中有 '发送消息' 和 '管理消息' 的权限。")
                break # 如果没有权限，后续尝试也可能失败，直接中断
            except Exception as e:
                logger.error(f"发送幽灵提及失败: {e}", exc_info=True)
            
            # 在处理完一个分块后等待，以避免API滥用
            if len(user_ids) > chunk_size:
                await asyncio.sleep(chunk_delay)

    @app_commands.command(name="关注本贴作者", description="关注当前帖子的作者以接收作者新帖子的更新通知")
    @app_commands.checks.cooldown(1, 5.0)
    async def follow_author(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("此命令只能在论坛帖子中使用。", ephemeral=True)
            return
        try:
            # --- 修改这里，增加健壮性 ---
            author = interaction.channel.owner
            # 如果缓存中没有作者信息，尝试从API获取
            if not author:
                try:
                    author = await self.bot.fetch_user(interaction.channel.owner_id)
                except discord.NotFound:
                    await interaction.response.send_message("❌ 无法找到该帖子的作者信息，操作失败。", ephemeral=True)
                    return
            
            # 如果仍然没有作者信息（非常罕见），则退出
            if not author:
                await interaction.response.send_message("❌ 未能获取作者信息，请稍后再试。", ephemeral=True)
                return

            result = await self.author_follow_service.follow_author(interaction.user.id, author.id, author.name)
            await _handle_follow_response(interaction, result, author)
        except Exception as e:
            logger.error(f"命令 /关注本贴作者 执行失败: {e}", exc_info=True)
            await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    @app_commands.command(name="取关本贴作者", description="取消关注当前帖子的作者")
    @app_commands.checks.cooldown(1, 5.0)
    async def unfollow_author(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ 此命令只能在论坛帖子中使用。", ephemeral=True)
            return
        try:
            author = interaction.channel.owner
            if not author:
                try:
                    # 如果缓存中没有，尝试从API获取
                    author = await self.bot.fetch_user(interaction.channel.owner_id)
                except discord.NotFound:
                    # 即使找不到用户信息，仍然可以尝试用ID取关
                    pass # 此时 author 依然是 None，后续会显示“未知作者”，但操作可以继续

            result = await self.author_follow_service.unfollow_author(interaction.user.id, interaction.channel.owner_id)
            await _handle_unfollow_response(interaction, result, author)
        except Exception as e:
            logger.error(f"命令 /取关本贴作者 执行失败: {e}", exc_info=True)
            await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AuthorTracker(bot))
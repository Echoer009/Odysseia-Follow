import discord
from discord.ext import commands
from discord import app_commands
from ..services.author_follow_service import AuthorFollowService, FollowResult, UnfollowResult
import traceback
import asyncio
import os

resource_channel_ids_str = os.getenv('RESOURCE_CHANNEL_IDS', '')
RESOURCE_CHANNEL_IDS = {int(id.strip()) for id in resource_channel_ids_str.split(',') if id.strip()}

if not RESOURCE_CHANNEL_IDS:
    print("警告：在 .env 文件中未配置任何有效的 RESOURCE_CHANNEL_IDS！机器人将不会监听任何频道。")

# --- 辅助方法，用于生成响应 (推荐的重构) ---
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
            print(f"消息命令 '关注此消息作者' 执行失败: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    async def unfollow_this_author_context(self, interaction: discord.Interaction, message: discord.Message):
        try:
            author = message.author
            result = await self.author_follow_service.unfollow_author(interaction.user.id, author.id)
            await _handle_unfollow_response(interaction, result, author)
        except Exception as e:
            print(f"消息命令 '取关此消息作者' 执行失败: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        try:
            if thread.parent_id not in RESOURCE_CHANNEL_IDS:
                return
            author_id = thread.owner_id
            if not author_id:
                return
            
            await self.bot.db.add_post(thread.id, author_id, thread.created_at)

            parent_name = thread.parent.name if thread.parent else "未知频道"
            print(f"检测到作者 {author_id} 在受监听的频道 {parent_name} 中发布了新帖: {thread.name}")
            follower_ids = await self.author_follow_service.get_author_followers(author_id)
            if not follower_ids:
                print(f"作者 {author_id} 没有关注者，无需通知。")
                return
            await self.ghost_ping_users(thread, follower_ids)
        except Exception as e:
            print(f"处理 on_thread_create 事件时发生错误 (线程ID: {thread.id}): {e}")
            traceback.print_exc()

    async def ghost_ping_users(self, thread: discord.Thread, user_ids: list[int]):
        print(f"准备在帖子 {thread.id} 中通知 {len(user_ids)} 位用户。")
        await asyncio.sleep(5)
        chunk_size = 50
        for i in range(0, len(user_ids), chunk_size):
            chunk = user_ids[i:i + chunk_size]
            ping_message = " ".join([f"<@{user_id}>" for user_id in chunk])
            try:
                message = await thread.send(ping_message)
                await message.delete()
                print(f"成功发送并删除了对 {len(chunk)} 位用户的提及。")
            except Exception as e:
                print(f"发送幽灵提及失败: {e}")
            await asyncio.sleep(1)

    @app_commands.command(name="关注本贴作者", description="关注当前帖子的作者以接收作者新帖子的更新通知")
    @app_commands.checks.cooldown(1, 5.0)
    async def follow_author(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("此命令只能在论坛帖子中使用。", ephemeral=True)
            return
        try:
            author = interaction.channel.owner
            author_name = author.name if author else "未知作者"
            result = await self.author_follow_service.follow_author(interaction.user.id, interaction.channel.owner_id, author_name)
            await _handle_follow_response(interaction, result, author)
        except Exception as e:
            print(f"命令 /关注本贴作者 执行失败: {e}")
            await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

    @app_commands.command(name="取关本贴作者", description="取消关注当前帖子的作者")
    @app_commands.checks.cooldown(1, 5.0)
    async def unfollow_author(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ 此命令只能在论坛帖子中使用。", ephemeral=True)
            return
        try:
            author = interaction.channel.owner
            result = await self.author_follow_service.unfollow_author(interaction.user.id, interaction.channel.owner_id)
            await _handle_unfollow_response(interaction, result, author)
        except Exception as e:
            print(f"命令 /取关本贴作者 执行失败: {e}")
            await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AuthorTracker(bot))
import discord
from discord.ext import commands
from discord import app_commands
from discord import ui
import math  # <-- 1. 导入 math 库
from ..services.follow_service import FollowService, FollowResult, UnfollowResult
import traceback
import asyncio
import os

resource_channel_ids_str = os.getenv('RESOURCE_CHANNEL_IDS', '')
RESOURCE_CHANNEL_IDS = {int(id.strip()) for id in resource_channel_ids_str.split(',') if id.strip()}

if not RESOURCE_CHANNEL_IDS:
    print("警告：在 .env 文件中未配置任何有效的 RESOURCE_CHANNEL_IDS！机器人将不会监听任何频道。")

# --- 1. 将右键菜单命令移出类定义 ---

@app_commands.context_menu(name="关注此消息作者")
async def follow_this_author(interaction: discord.Interaction, message: discord.Message):
    # 从 interaction 中获取 bot 实例和 follow_service
    bot = interaction.client
    follow_service: FollowService = bot.follow_service
    try:
        author = message.author
        result = await follow_service.follow_author(interaction.user.id, author.id, author.name)
        if result == FollowResult.SUCCESS:
            await interaction.response.send_message(f"✅成功关注作者 **{author.display_name}**！", ephemeral=True)
        elif result == FollowResult.ALREADY_FOLLOWED:
            await interaction.response.send_message(f"🤔您已经关注过作者 **{author.display_name}** 了。", ephemeral=True)
        elif result == FollowResult.CANNOT_FOLLOW_SELF:
            await interaction.response.send_message("您不能关注自己~", ephemeral=True)
    except Exception as e:
        print(f"消息命令 '关注此消息作者' 执行失败: {e}")
        await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

@app_commands.context_menu(name="取关此消息作者")
async def unfollow_this_author(interaction: discord.Interaction, message: discord.Message):
    bot = interaction.client
    follow_service: FollowService = bot.follow_service
    try:
        author = message.author
        result = await follow_service.unfollow_author(interaction.user.id, author.id)
        if result == UnfollowResult.SUCCESS:
            await interaction.response.send_message(f"✅已取消关注作者 **{author.display_name}**。", ephemeral=True)
        elif result == UnfollowResult.NOT_FOLLOWED:
            await interaction.response.send_message("🤔您之前没有关注过这位作者。", ephemeral=True)
    except Exception as e:
        print(f"消息命令 '取关此消息作者' 执行失败: {e}")
        await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)


# --- 2. 重构 FollowsManageView 以支持分页 ---
class FollowsManageView(ui.View):
    def __init__(self, follow_service: FollowService, user_id: int, followed_authors: list[dict]):
        super().__init__(timeout=180)
        self.follow_service = follow_service
        self.user_id = user_id
        self.all_authors = followed_authors
        
        self.current_page = 0
        self.page_size = 10  # 每页显示10个作者
        self.total_pages = math.ceil(len(self.all_authors) / self.page_size) if self.all_authors else 1

        self.update_components()

    def get_current_page_authors(self) -> list[dict]:
        """获取当前页的作者列表"""
        start = self.current_page * self.page_size
        end = start + self.page_size
        return self.all_authors[start:end]

    def create_embed(self, success_message: str = None) -> discord.Embed:
        """根据当前页创建Embed"""
        page_authors = self.get_current_page_authors()
        
        description_lines = []
        if not page_authors:
            description_lines.append("您还没有关注任何作者，或当前页没有作者了。")
        else:
            for author in page_authors:
                description_lines.append(f"• <@{author['author_id']}> (`{author['author_name']}`)")
        
        description = "从下面的菜单中选择一位作者进行取关。\n\n" + "\n".join(description_lines)
        if success_message:
            description = f"{success_message}\n\n" + description

        embed = discord.Embed(
            title="我关注的作者列表",
            description=description,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"第 {self.current_page + 1} / {self.total_pages} 页")
        return embed

    def update_components(self):
        """更新视图上的所有组件（下拉菜单和按钮）"""
        self.clear_items()
        
        page_authors = self.get_current_page_authors()
        select_options = [
            discord.SelectOption(label=author['author_name'], value=str(author['author_id']))
            for author in page_authors
        ]
        if not select_options:
             select_menu = ui.Select(placeholder="没有可操作的作者...", disabled=True)
        else:
            select_menu = ui.Select(placeholder="选择一位作者进行取关...", options=select_options)
            select_menu.callback = self.select_callback
        self.add_item(select_menu)

        prev_button = ui.Button(label="上一页", style=discord.ButtonStyle.grey, disabled=(self.current_page == 0))
        prev_button.callback = self.prev_page_callback
        self.add_item(prev_button)

        next_button = ui.Button(label="下一页", style=discord.ButtonStyle.grey, disabled=(self.current_page >= self.total_pages - 1))
        next_button.callback = self.next_page_callback
        self.add_item(next_button)

    async def select_callback(self, interaction: discord.Interaction):
        """当用户从下拉菜单中选择一个选项时调用"""
        author_id_to_unfollow = int(interaction.data['values'][0])
        
        result = await self.follow_service.unfollow_author(self.user_id, author_id_to_unfollow)
        
        if result == UnfollowResult.SUCCESS:
            author_name = next((author['author_name'] for author in self.all_authors if author['author_id'] == author_id_to_unfollow), "未知作者")
            
            # 从列表中移除作者并刷新视图
            self.all_authors = [author for author in self.all_authors if author['author_id'] != author_id_to_unfollow]
            self.total_pages = math.ceil(len(self.all_authors) / self.page_size) if self.all_authors else 1
            if self.current_page >= self.total_pages:
                self.current_page = max(0, self.total_pages - 1)
            
            self.update_components()
            success_msg = f"✅ 已成功取关 **{author_name}**。"
            await interaction.response.edit_message(embed=self.create_embed(success_msg), view=self)

        else:  # NOT_FOLLOWED
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content="🤔 操作失败，您已经取关了这位作者。", view=self, embed=None)

    async def prev_page_callback(self, interaction: discord.Interaction):
        """处理上一页按钮点击"""
        self.current_page -= 1
        self.update_components()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_page_callback(self, interaction: discord.Interaction):
        """处理下一页按钮点击"""
        self.current_page += 1
        self.update_components()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


class AuthorTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.follow_service: FollowService = bot.follow_service

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        try:
            if thread.parent_id not in RESOURCE_CHANNEL_IDS:
                return
            author_id = thread.owner_id
            if not author_id:
                return

            # 记录帖子到数据库 
            await self.bot.db.add_post(thread.id, author_id, thread.created_at)


            parent_name = thread.parent.name if thread.parent else "未知频道"
            print(f"检测到作者 {author_id} 在受监听的频道 {parent_name} 中发布了新帖: {thread.name}")
            follower_ids = await self.follow_service.get_author_followers(author_id)
            if not follower_ids:
                print(f"作者 {author_id} 没有关注者，无需通知。")
                return
            await self.ghost_ping_users(thread, follower_ids)
        except Exception as e:
            print(f"处理 on_thread_create 事件时发生错误 (线程ID: {thread.id}): {e}")
            traceback.print_exc()

    async def ghost_ping_users(self, thread: discord.Thread, user_ids: list[int]):
        print(f"准备在帖子 {thread.id} 中通知 {len(user_ids)} 位用户。")
        # 等待5秒，确保帖子已完全准备好接收消息
        await asyncio.sleep(5)
        chunk_size = 80
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

    # 斜杠命令保留在类中
    @app_commands.command(name="关注本贴作者", description="关注当前帖子的作者以接收作者新帖子的更新通知")
    @app_commands.checks.cooldown(1, 5.0)
    async def follow_author(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("此命令只能在论坛帖子中使用。", ephemeral=True)
            return
        try:
            author = interaction.channel.owner
            author_name = author.name if author else "未知作者"
            result = await self.follow_service.follow_author(interaction.user.id, interaction.channel.owner_id, author_name)
            if result == FollowResult.SUCCESS:
                await interaction.response.send_message(f"✅成功关注作者 **{author.display_name if author else '未知作者'}**！当TA发布新帖时您会收到通知。", ephemeral=True)
            elif result == FollowResult.ALREADY_FOLLOWED:
                await interaction.response.send_message(f"🤔您已经关注该作者 **{author.display_name if author else '未知作者'}** 了。", ephemeral=True)
            elif result == FollowResult.CANNOT_FOLLOW_SELF:
                await interaction.response.send_message("您不能关注自己~", ephemeral=True)
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
            result = await self.follow_service.unfollow_author(interaction.user.id, interaction.channel.owner_id)
            if result == UnfollowResult.SUCCESS:
                await interaction.response.send_message(f"✅已取消关注作者 **{author.display_name if author else '未知作者'}**。", ephemeral=True)
            elif result == UnfollowResult.NOT_FOLLOWED:
                await interaction.response.send_message("🤔您之前没有关注过这位作者。", ephemeral=True)
        except Exception as e:
            print(f"命令 /取关本贴作者 执行失败: {e}")
            await interaction.response.send_message("哎呀，操作失败了。请稍后再试或联系管理员。", ephemeral=True)

# --- 2. 修改 setup 函数以加载 Cog 和独立的命令 ---
async def setup(bot: commands.Bot):
    # 添加 Cog
    await bot.add_cog(AuthorTracker(bot))
    # 将独立的右键菜单命令添加到机器人的命令树
    bot.tree.add_command(follow_this_author)
    bot.tree.add_command(unfollow_this_author)
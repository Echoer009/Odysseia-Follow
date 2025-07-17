import discord
from discord.ext import commands
from discord import app_commands
from discord import ui
import math
import logging # 新增
import os # 新增

# 1. 更新导入
from src.modules.author_follow.services.author_follow_service import AuthorFollowService, UnfollowResult
from src.modules.user_profile_feature.services.profile_service import ProfileService

logger = logging.getLogger(__name__) # 新增

class FollowsManageView(ui.View):
    # 2. 更新构造函数类型提示
    def __init__(self, author_follow_service: AuthorFollowService, user_id: int, followed_authors: list[dict]):
        # 从环境变量读取配置，提供默认值
        try:
            timeout = int(os.getenv('PROFILE_VIEW_TIMEOUT_SECONDS', '180'))
            self.page_size = int(os.getenv('PROFILE_VIEW_PAGE_SIZE', '10'))
        except (ValueError, TypeError):
            timeout = 180
            self.page_size = 10

        super().__init__(timeout=timeout)
        self.author_follow_service = author_follow_service
        self.user_id = user_id
        self.all_authors = followed_authors
        
        self.current_page = 0
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
                new_post_count = author.get('new_posts', 0)
                new_post_text = ""
                if new_post_count > 0:
                    new_post_text = f" - 📬 **{new_post_count}** 个新帖"
                description_lines.append(f"• <@{author['author_id']}> (`{author['author_name']}`){new_post_text}")
        
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
        self.clear_items()

        page_authors = self.get_current_page_authors()
        
        # 只有在当前页有作者可选时，才创建并添加下拉菜单
        if page_authors:
            select_options = [
                discord.SelectOption(label=author['author_name'], value=str(author['author_id']))
                for author in page_authors
            ]
            select_menu = ui.Select(placeholder="选择一位作者进行取关...", options=select_options)
            select_menu.callback = self.select_callback
            self.add_item(select_menu)
        # 如果没有作者，就不添加任何下拉菜单组件

        # 修改按钮样式为 secondary
        prev_button = ui.Button(label="◀️ 上一页", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
        prev_button.callback = self.prev_page
        self.add_item(prev_button)

        next_button = ui.Button(label="下一页 ▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= self.total_pages - 1))
        next_button.callback = self.next_page
        self.add_item(next_button)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            author_id_to_unfollow = int(interaction.data['values'][0])
            # 3. 更新服务调用
            result = await self.author_follow_service.unfollow_author(self.user_id, author_id_to_unfollow)
            
            if result == UnfollowResult.SUCCESS:
                author_name = next((author['author_name'] for author in self.all_authors if author['author_id'] == author_id_to_unfollow), "未知作者")
                
                # 更新内部数据
                self.all_authors = [author for author in self.all_authors if author['author_id'] != author_id_to_unfollow]
                self.total_pages = math.ceil(len(self.all_authors) / self.page_size) if self.all_authors else 1
                if self.current_page >= self.total_pages:
                    self.current_page = max(0, self.total_pages - 1)
                
                # 更新界面组件
                self.update_components()
                success_msg = f"✅ 已成功取关 **{author_name}**。"
                await interaction.edit_original_response(embed=self.create_embed(success_msg), view=self)
            else:  # NOT_FOLLOWED
                self.update_components()
                error_msg = "🤔 操作失败，您可能已经取关了这位作者。"
                await interaction.edit_original_response(embed=self.create_embed(error_msg), view=self)
        except Exception as e:
            # --- 修改这里 ---
            logger.error(f"在 select_callback 中发生错误: {e}", exc_info=True)
            await interaction.edit_original_response(content="处理您的请求时发生了一个内部错误，请稍后再试。", embed=None, view=None)

    async def prev_page(self, interaction: discord.Interaction):
        """翻到上一页"""
        self.current_page -= 1
        self.update_components()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        """翻到下一页"""
        self.current_page += 1
        self.update_components()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


class UserProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # 4. 更新服务属性名称和类型提示
        self.author_follow_service: AuthorFollowService = bot.author_follow_service
        self.profile_service: ProfileService = bot.profile_service

    @app_commands.command(name="我的关注", description="查看您关注的所有作者列表")
    async def my_follows(self, interaction: discord.Interaction):
        try:
            followed_authors = await self.profile_service.get_user_profile_data(interaction.user.id)

            if not followed_authors:
                await interaction.response.send_message("您还没有关注任何作者。", ephemeral=True)
                return
            
            # 5. 将正确的服务实例传递给 View
            view = FollowsManageView(self.author_follow_service, interaction.user.id, followed_authors)
            embed = view.create_embed()
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            # --- 修改这里 ---
            logger.error(f"命令 /我的关注 执行失败: {e}", exc_info=True)
            await interaction.response.send_message("哎呀，操作失败了，好像和数据库的连接出了点问题。请稍后再试或联系管理员。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(UserProfileCog(bot))
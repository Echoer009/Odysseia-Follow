import discord
from discord.ext import commands
from discord import app_commands
from discord import ui
import math
import traceback # 1. 导入 traceback 用于更详细的错误输出
from src.modules.follow_feature.services.follow_service import FollowService, UnfollowResult

# --- 1. 使用重构后的 FollowsManageView 替换旧版本 ---
class FollowsManageView(ui.View):
    def __init__(self, follow_service: FollowService, user_id: int, followed_authors: list[dict]):
        super().__init__(timeout=180)
        self.follow_service = follow_service
        self.user_id = user_id
        self.all_authors = followed_authors
        
        self.current_page = 0
        self.page_size = 1  # 每页显示10个作者
        self.total_pages = math.ceil(len(self.all_authors) / self.page_size) if self.all_authors else 1

        # 初始化时就构建好所有组件
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
            # 将成功消息添加到描述的顶部
            description = f"{success_message}\n\n" + description

        embed = discord.Embed(
            title="我关注的作者列表",
            description=description,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"第 {self.current_page + 1} / {self.total_pages} 页")
        return embed

    def update_components(self):
        """动态更新所有组件（下拉菜单和按钮）"""
        self.clear_items()  # 清除旧的组件

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

        # 按钮的逻辑保持不变，它们会根据页码自动禁用
        prev_button = ui.Button(label="◀️ 上一页", style=discord.ButtonStyle.primary, disabled=(self.current_page == 0))
        prev_button.callback = self.prev_page
        self.add_item(prev_button)

        next_button = ui.Button(label="下一页 ▶️", style=discord.ButtonStyle.primary, disabled=(self.current_page >= self.total_pages - 1))
        next_button.callback = self.next_page
        self.add_item(next_button)

    async def select_callback(self, interaction: discord.Interaction):
        """当用户从下拉菜单中选择一个选项时调用"""
        # 1. 立刻延迟响应，这是解决“交互失败”的关键
        #    使用 ephemeral=True 明确告知 Discord 这是一个临时消息的后续操作
        await interaction.response.defer(ephemeral=True)

        try:
            author_id_to_unfollow = int(interaction.data['values'][0])
            
            # 2. 现在可以安全地执行可能耗时的数据库操作
            result = await self.follow_service.unfollow_author(self.user_id, author_id_to_unfollow)
            
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
                # 3. 使用 edit_original_response 更新原始消息，这是 defer 后的标准做法
                await interaction.edit_original_response(embed=self.create_embed(success_msg), view=self)
            else:  # NOT_FOLLOWED
                self.update_components()
                error_msg = "🤔 操作失败，您可能已经取关了这位作者。"
                await interaction.edit_original_response(embed=self.create_embed(error_msg), view=self)
        except Exception as e:
            # 4. 添加错误捕获，如果中间任何步骤出错，都能给出反馈而不是直接失败
            print(f"在 select_callback 中发生错误: {e}")
            traceback.print_exc()
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
        self.follow_service: FollowService = bot.follow_service

    # 2. 修改装饰器为 app_commands.command
    # 3. 修改函数签名，使用 interaction: discord.Interaction
    @app_commands.command(name="我的关注", description="查看您关注的所有作者列表")
    async def my_follows(self, interaction: discord.Interaction):
        try:
            # 3. --- 全新的命令逻辑 ---
            # a. 获取上次查看时间，并自动更新为现在。函数会返回上次的时间。
            last_view_time = await self.bot.db.get_and_update_last_view(interaction.user.id)

            # b. 获取关注的作者列表
            followed_authors = await self.follow_service.get_user_follows_details(interaction.user.id)

            if not followed_authors:
                await interaction.response.send_message("您还没有关注任何作者。", ephemeral=True)
                return

            # c. 获取这些作者自上次查看以来的新帖计数
            author_ids = [author['author_id'] for author in followed_authors]
            new_post_counts = await self.bot.db.get_new_post_counts(author_ids, last_view_time)
            
            # d. 将计数整合到作者信息中
            new_post_counts_map = {item['author_id']: item['new_posts_count'] for item in new_post_counts}
            for author in followed_authors:
                author['new_posts'] = new_post_counts_map.get(author['author_id'], 0)
            
            # e. (可选优化) 将有新帖的作者排在前面
            followed_authors.sort(key=lambda x: x.get('new_posts', 0), reverse=True)
            
            # f. 创建并发送视图
            view = FollowsManageView(self.follow_service, interaction.user.id, followed_authors)
            embed = view.create_embed()
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            print(f"命令 /我的关注 执行失败: {e}")
            traceback.print_exc() # 打印详细错误信息
            await interaction.response.send_message("哎呀，操作失败了，好像和数据库的连接出了点问题。请稍后再试或联系管理员。", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(UserProfileCog(bot))
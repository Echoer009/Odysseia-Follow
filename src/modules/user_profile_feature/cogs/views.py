import discord
from discord import ui
import math
import os
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .profile_cog import UserProfileCog
    from src.modules.channel_subscription.cogs.subscription_tracker import SubscriptionTracker
    from src.modules.channel_subscription.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

# --- Main Menu UI ---
class MainMenuView(ui.View):
    """主菜单视图，作为统一管理入口"""
    def __init__(self, profile_cog: 'UserProfileCog'):
        timeout = int(os.getenv('MAIN_MENU_VIEW_TIMEOUT_SECONDS', '300'))
        super().__init__(timeout=timeout)
        self.profile_cog = profile_cog

    def create_embed(self):
        embed = discord.Embed(
            title="🔧 我的关注管理中心",
            description="请选择您要管理的项目：\n\n"
                        "👤 **关注的作者**\n"
                        "管理您关注的创作者，当您关注时,会接受到他们的新帖通知。\n\n"
                        "🔔 **关注的频道**\n"
                        "为特定频道设置关键词，接收所有新帖,或只接收您感兴趣的内容。",
            color=0x49989a
        )
        embed.set_footer(text="面板将在 5 分钟后超时。")
        return embed

    @ui.button(label="👤 管理关注的作者", style=discord.ButtonStyle.primary, row=0)
    async def manage_authors(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        try:
            followed_authors = await self.profile_cog.profile_service.get_user_profile_data(interaction.user.id)
            view = FollowsManageView(self.profile_cog, interaction.user.id, followed_authors)
            embed = view.create_embed()
            await interaction.edit_original_response(embed=embed, view=view)
        except Exception as e:
            log_context = {'user_id': interaction.user.id, 'guild_id': interaction.guild_id}
            logger.error("切换到作者管理视图失败", extra=log_context, exc_info=True)
            await interaction.edit_original_response(content="加载作者列表失败，请稍后再试。", view=None, embed=None)

    @ui.button(label="🔔 管理关注的频道", style=discord.ButtonStyle.primary, row=0)
    async def manage_subscriptions(self, interaction: discord.Interaction, button: ui.Button):
        # The deferral is now handled inside send_main_subscription_view
        try:
            subscription_cog: 'SubscriptionTracker' = self.profile_cog.bot.get_cog("SubscriptionTracker")
            if subscription_cog:
                await subscription_cog.send_main_subscription_view(interaction, self.profile_cog)
            else:
                await interaction.response.edit_message(content="❌ 无法加载频道关注模块，请联系管理员。", view=None, embed=None)
        except Exception as e:
            log_context = {'user_id': interaction.user.id, 'guild_id': interaction.guild_id}
            logger.error("切换到频道关注视图失败", extra=log_context, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.edit_message(content="加载频道关注功能失败，请稍后再试。", view=None, embed=None)
            else:
                await interaction.edit_original_response(content="加载频道关注功能失败，请稍后再试。", view=None, embed=None)


# --- Author Follow UI ---
class FollowsManageView(ui.View):
    def __init__(self, profile_cog: 'UserProfileCog', user_id: int, followed_authors: list[dict]):
        timeout = int(os.getenv('PROFILE_VIEW_TIMEOUT_SECONDS', '180'))
        self.page_size = int(os.getenv('PROFILE_VIEW_PAGE_SIZE', '10'))
        super().__init__(timeout=timeout)
        self.profile_cog = profile_cog
        self.author_follow_service = profile_cog.author_follow_service
        self.user_id = user_id
        self.all_authors = followed_authors
        self.current_page = 0
        self.total_pages = math.ceil(len(self.all_authors) / self.page_size) if self.all_authors else 1
        self.update_components()

    def get_current_page_authors(self) -> list[dict]:
        start = self.current_page * self.page_size
        return self.all_authors[start:start + self.page_size]

    def create_embed(self, success_message: str = None) -> discord.Embed:
        page_authors = self.get_current_page_authors()
        description_lines = []
        if not page_authors:
            description_lines.append("您还没有关注任何作者。")
        else:
            for author in page_authors:
                new_post_text = f" - 📬 **{author.get('new_posts', 0)}** 个新帖" if author.get('new_posts', 0) > 0 else ""
                description_lines.append(f"• <@{author['author_id']}> (`{author['author_name']}`){new_post_text}")
        
        description = "从下面的菜单中选择一位作者进行取关。\n\n" + "\n".join(description_lines)
        if success_message:
            description = f"{success_message}\n\n" + description

        embed = discord.Embed(title="我关注的作者列表", description=description, color=0x49989a)
        embed.set_footer(text=f"第 {self.current_page + 1} / {self.total_pages} 页")
        return embed

    def update_components(self):
        self.clear_items()
        page_authors = self.get_current_page_authors()
        if page_authors:
            options = [discord.SelectOption(label=a['author_name'], value=str(a['author_id'])) for a in page_authors]
            select_menu = ui.Select(placeholder="选择一位作者进行取关...", options=options)
            select_menu.callback = self.select_callback
            self.add_item(select_menu)

        prev_button = ui.Button(label="◀️ 上一页", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
        prev_button.callback = self.prev_page
        self.add_item(prev_button)

        next_button = ui.Button(label="下一页 ▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= self.total_pages - 1))
        next_button.callback = self.next_page
        self.add_item(next_button)

        back_button = ui.Button(label="返回主菜单", style=discord.ButtonStyle.grey, row=2)
        back_button.callback = self.back_to_main_menu
        self.add_item(back_button)

    async def back_to_main_menu(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = MainMenuView(self.profile_cog)
        await interaction.edit_original_response(embed=view.create_embed(), view=view)

    async def select_callback(self, interaction: discord.Interaction):
        from src.modules.author_follow.services.author_follow_service import UnfollowResult
        await interaction.response.defer()
        author_id = int(interaction.data['values'][0])
        result = await self.author_follow_service.unfollow_author(self.user_id, author_id)
        
        if result == UnfollowResult.SUCCESS:
            author_name = next((a['author_name'] for a in self.all_authors if a['author_id'] == author_id), "未知作者")
            self.all_authors = [a for a in self.all_authors if a['author_id'] != author_id]
            self.total_pages = math.ceil(len(self.all_authors) / self.page_size) if self.all_authors else 1
            if self.current_page >= self.total_pages:
                self.current_page = max(0, self.total_pages - 1)
            self.update_components()
            await interaction.edit_original_response(embed=self.create_embed(f"✅ 已成功取关 **{author_name}**。"), view=self)
        else:
            await interaction.edit_original_response(embed=self.create_embed("🤔 操作失败，您可能已经取关了这位作者。"), view=self)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.update_components()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        self.update_components()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)


# --- Channel Subscription UI ---
class SubscriptionManageView(ui.View):
    def __init__(self, sub_cog: 'SubscriptionTracker', profile_cog: 'UserProfileCog', user_id: int, channel_id: int):
        timeout = int(os.getenv('SUBSCRIPTION_MANAGE_VIEW_TIMEOUT_SECONDS', '300'))
        super().__init__(timeout=timeout)
        self.sub_cog = sub_cog
        self.profile_cog = profile_cog
        self.user_id = user_id
        self.channel_id = channel_id
        self.service = sub_cog.subscription_service
        self.message: discord.Message = None

    async def update_embed(self):
        embed = await self.sub_cog.create_subscription_embed(self.user_id, self.channel_id)
        if self.message:
            await self.message.edit(embed=embed, view=self)

    @ui.button(label="⭐ 添加关注词", style=discord.ButtonStyle.success, row=0)
    async def add_followed(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SubscriptionModal(self, "followed"))

    @ui.button(label="➖ 删除关注词", style=discord.ButtonStyle.danger, row=0)
    async def edit_followed(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SubscriptionModal(self, "followed", edit_mode=True))

    @ui.button(label="⭐ 添加屏蔽词", style=discord.ButtonStyle.success, row=1)
    async def add_blocked(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SubscriptionModal(self, "blocked"))

    @ui.button(label="➖ 删除屏蔽词", style=discord.ButtonStyle.danger, row=1)
    async def edit_blocked(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SubscriptionModal(self, "blocked", edit_mode=True))

    @ui.button(label="返回频道列表", style=discord.ButtonStyle.primary, row=2)
    async def back_to_channel_select(self, interaction: discord.Interaction, button: ui.Button):
        # This now goes back to the main subscription menu
        await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)

    @ui.button(label="❌ 取消关注此频道", style=discord.ButtonStyle.danger, row=2)
    async def unfollow_channel(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await self.service.unfollow_channel(self.user_id, self.channel_id)
            # After unfollowing, send the user back to the main subscription menu
            await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)
        except Exception as e:
            log_context = {'user_id': self.user_id, 'channel_id': self.channel_id}
            logger.error("取消关注频道失败", extra=log_context, exc_info=True)
            await interaction.edit_original_response(content="取消关注失败，请稍后再试。", embed=None, view=None)

class SubscriptionModal(ui.Modal):
    def __init__(self, parent_view: SubscriptionManageView, keyword_type: str, edit_mode: bool = False):
        self.parent_view = parent_view
        self.service: 'SubscriptionService' = parent_view.service
        self.user_id = parent_view.user_id
        self.channel_id = parent_view.channel_id
        self.keyword_type = keyword_type
        self.edit_mode = edit_mode
        
        action = "编辑" if edit_mode else "添加"
        kw_type_name = "关注" if keyword_type == 'followed' else "屏蔽"
        super().__init__(title=f"{action}{kw_type_name}词")

        self.keywords_input = ui.TextInput(label="关键词 (用空格或换行分隔)", style=discord.TextStyle.paragraph, placeholder="例如: 关键词1 关键词2", required=not edit_mode)
        self.add_item(self.keywords_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # 如果输入为空，则不进行任何操作
        if not self.keywords_input.value.strip():
            return

        new_keywords_set = {kw.strip().lower() for kw in self.keywords_input.value.split()}
        
        current_sub = await self.service.get_subscription(self.user_id, self.channel_id) or {'followed_keywords': [], 'blocked_keywords': []}
        
        key = f"{self.keyword_type}_keywords"
        current_keywords = set(current_sub.get(key, []))

        if self.edit_mode:
            # 编辑模式：删除指定的关键词
            current_keywords -= new_keywords_set
        else:
            # 添加模式：合并关键词
            current_keywords.update(new_keywords_set)
        
        current_sub[key] = list(current_keywords)

        await self.service.update_subscription(self.user_id, self.channel_id, current_sub['followed_keywords'], current_sub['blocked_keywords'])
        await self.parent_view.update_embed()

# --- New Subscription Main Menu ---
class SubscriptionMenuView(ui.View):
    def __init__(self, sub_cog: 'SubscriptionTracker', profile_cog: 'UserProfileCog', user_id: int, subscribed_channels: List[discord.ForumChannel]):
        timeout = int(os.getenv('SUBSCRIPTION_MENU_VIEW_TIMEOUT_SECONDS', '180'))
        super().__init__(timeout=timeout)
        self.sub_cog = sub_cog
        self.profile_cog = profile_cog
        self.user_id = user_id
        self.subscribed_channels = subscribed_channels
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        # Dropdown for managing existing subscriptions
        if self.subscribed_channels:
            options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in self.subscribed_channels]
            select = ui.Select(placeholder="选择一个已关注的频道进行管理...", options=options)
            select.callback = self.select_channel_callback
            self.add_item(select)
        
        # Button to add a new subscription
        add_button = ui.Button(label="➕ 关注新频道", style=discord.ButtonStyle.success, row=1)
        add_button.callback = self.add_new_subscription
        self.add_item(add_button)

        # Back to main menu button
        back_button = ui.Button(label="返回主菜单", style=discord.ButtonStyle.grey, row=2)
        back_button.callback = self.back_to_main_menu
        self.add_item(back_button)

    def create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔔 我关注的频道",
            color=0x49989a
        )
        if not self.subscribed_channels:
            embed.description = "您目前没有关注任何频道。\n\n点击下面的“关注新频道”按钮开始吧！"
        else:
            description = "您已关注以下频道。从下拉菜单中选择一个进行管理。\n\n"
            description += "\n".join(f"• {ch.mention} (`{ch.name}`)" for ch in self.subscribed_channels)
            embed.description = description
        
        embed.set_footer(text="使用下面的按钮来添加新的频道关注。")
        return embed

    async def select_channel_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        channel_id = int(interaction.data['values'][0])
        await self.sub_cog.send_subscription_manage_ui(interaction, self.user_id, channel_id, self.profile_cog)

    async def add_new_subscription(self, interaction: discord.Interaction):
        await interaction.response.defer()
        all_channels = await self.sub_cog.get_target_forum_channels()
        subscribed_ids = {ch.id for ch in self.subscribed_channels}
        available_channels = [ch for ch in all_channels if ch.id not in subscribed_ids]
        
        view = ChannelSelectView(self.sub_cog, self.profile_cog, self.user_id, available_channels)
        embed = view.create_embed()
        await interaction.edit_original_response(embed=embed, view=view)

    async def back_to_main_menu(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = MainMenuView(self.profile_cog)
        await interaction.edit_original_response(embed=view.create_embed(), view=view)

# --- New Channel Selection for Following ---
class ChannelMultiSelect(ui.Select):
    def __init__(self, channels: List[discord.ForumChannel]):
        options = [discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in channels]
        if not options:
            options.append(discord.SelectOption(label="没有可供关注的新频道了", value="disabled", default=True))
        
        super().__init__(
            placeholder="选择一个或多个频道进行关注...",
            min_values=1,
            max_values=min(len(options), 25), # Discord limit
            options=options,
            disabled=(not channels)
        )

    async def callback(self, interaction: discord.Interaction):
        """
        This callback is triggered when the user makes a selection.
        We simply defer the interaction to prevent a "Interaction failed" error
        and allow the user to proceed to click the confirm button.
        """
        await interaction.response.defer()

class ChannelSelectView(ui.View):
    def __init__(self, sub_cog: 'SubscriptionTracker', profile_cog: 'UserProfileCog', user_id: int, available_channels: List[discord.ForumChannel]):
        timeout = int(os.getenv('CHANNEL_SELECT_VIEW_TIMEOUT_SECONDS', '180'))
        super().__init__(timeout=timeout)
        self.sub_cog = sub_cog
        self.profile_cog = profile_cog
        self.user_id = user_id
        
        self.select_menu = ChannelMultiSelect(available_channels)
        self.add_item(self.select_menu)

    def create_embed(self) -> discord.Embed:
        return discord.Embed(
            title="➕ 关注新频道",
            description="请从下面的列表中选择一个或多个您想关注的频道，然后点击“确认关注”。",
            color=0x49989a
        )

    @ui.button(label="✅ 确认关注", style=discord.ButtonStyle.success, row=1)
    async def confirm_follow(self, interaction: discord.Interaction, button: ui.Button):
        selected_ids = self.select_menu.values
        if not selected_ids or selected_ids[0] == "disabled":
            # Just go back if nothing is selected or selection is disabled
            await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)
            return

        service = self.sub_cog.subscription_service
        for channel_id_str in selected_ids:
            try:
                await service.follow_channel(self.user_id, int(channel_id_str))
            except Exception as e:
                log_context = {'user_id': self.user_id, 'channel_id': channel_id_str}
                logger.error("在多选流程中关注频道失败", extra=log_context, exc_info=True)
        
        # After following, show the updated main subscription menu
        await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)

    @ui.button(label="返回", style=discord.ButtonStyle.grey, row=1)
    async def back_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)
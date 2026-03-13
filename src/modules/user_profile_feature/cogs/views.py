import discord
import asyncio
from discord import ui
import math
import os
import logging
from typing import TYPE_CHECKING, List, Optional, cast, Any

from src.modules.thread_favorites.services.favorites_service import FavoritesService

from src.core.utils import retry_on_discord_error

if TYPE_CHECKING:
    from .profile_cog import UserProfileCog
    from src.modules.channel_subscription.cogs.subscription_tracker import (
        SubscriptionTracker,
    )
    from src.modules.channel_subscription.services.subscription_service import (
        SubscriptionService,
    )

logger = logging.getLogger(__name__)


# --- Main Menu UI ---
class MainMenuView(ui.View):
    """主菜单视图，作为统一管理入口"""

    def __init__(self, profile_cog: "UserProfileCog"):
        timeout = int(os.getenv("MAIN_MENU_VIEW_TIMEOUT_SECONDS", "300"))
        super().__init__(timeout=timeout)
        self.profile_cog = profile_cog

    def create_embed(self):
        embed = discord.Embed(
            title="🔧 我的关注管理中心",
            description="请选择您要管理的项目：\n\n"
            "👤 **关注的作者**\n"
            "管理您关注的创作者，当您关注时,会接受到他们的新帖通知。\n\n"
            "🔔 **关注的频道**\n"
            "为特定频道设置关键词，接收所有新帖,或只接收您感兴趣的内容。\n\n"
            "📜 **帖子收藏夹**\n"
            "管理您收藏的帖子，并可批量收藏或退出当前已加入的活跃帖子。",
            color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
        )
        embed.set_footer(text="面板将在 5 分钟后超时。")
        return embed

    @ui.button(label="👤 管理关注的作者", style=discord.ButtonStyle.primary, row=0)
    async def manage_authors(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        try:
            followed_authors = (
                await self.profile_cog.profile_service.get_user_profile_data(
                    interaction.user.id
                )
            )
            view = FollowsManageView(
                self.profile_cog, interaction.user.id, followed_authors
            )
            embed = view.create_embed()
            await interaction.edit_original_response(embed=embed, view=view)
        except Exception:
            log_context = {
                "user_id": interaction.user.id,
                "guild_id": interaction.guild_id,
            }
            logger.error("切换到作者管理视图失败", extra=log_context, exc_info=True)
            await interaction.edit_original_response(
                content="加载作者列表失败，请稍后再试。", view=None, embed=None
            )

    @ui.button(label="🔔 管理关注的频道", style=discord.ButtonStyle.primary, row=0)
    async def manage_subscriptions(
        self, interaction: discord.Interaction, button: ui.Button
    ):
        try:
            subscription_cog: "SubscriptionTracker" = self.profile_cog.bot.get_cog(
                "SubscriptionTracker"
            )
            if subscription_cog:
                await subscription_cog.send_main_subscription_view(
                    interaction, self.profile_cog
                )
            else:
                await interaction.response.edit_message(
                    content="❌ 无法加载频道关注模块，请联系管理员。",
                    view=None,
                    embed=None,
                )
        except Exception:
            log_context = {
                "user_id": interaction.user.id,
                "guild_id": interaction.guild_id,
            }
            logger.error("切换到频道关注视图失败", extra=log_context, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.edit_message(
                    content="加载频道关注功能失败，请稍后再试。", view=None, embed=None
                )
            else:
                await interaction.edit_original_response(
                    content="加载频道关注功能失败，请稍后再试。", view=None, embed=None
                )

    @ui.button(label="📜 管理我的收藏夹", style=discord.ButtonStyle.primary, row=1)
    async def manage_favorites(
        self, interaction: discord.Interaction, button: ui.Button
    ):
        await interaction.response.defer()
        try:
            favorites_service = self.profile_cog.bot.favorites_service
            user = cast(discord.User, interaction.user)
            view = FavoritesManageView(self.profile_cog, favorites_service, user)
            await view.send_initial_message(interaction)
        except Exception:
            log_context = {
                "user_id": interaction.user.id,
                "guild_id": interaction.guild_id,
            }
            logger.error("切换到收藏夹视图失败", extra=log_context, exc_info=True)
            await interaction.edit_original_response(
                content="加载收藏夹失败，请稍后再试。", view=None, embed=None
            )


class FollowsManageView(ui.View):
    def __init__(
        self, profile_cog: "UserProfileCog", user_id: int, followed_authors: list[dict]
    ):
        timeout = int(os.getenv("PROFILE_VIEW_TIMEOUT_SECONDS", "180"))
        self.page_size = int(os.getenv("PROFILE_VIEW_PAGE_SIZE", "10"))
        super().__init__(timeout=timeout)
        self.profile_cog = profile_cog
        self.author_follow_service = profile_cog.author_follow_service
        self.user_id = user_id
        self.all_authors = followed_authors
        self.current_page = 0
        self.total_pages = (
            math.ceil(len(self.all_authors) / self.page_size) if self.all_authors else 1
        )
        self.update_components()

    def get_current_page_authors(self) -> list[dict]:
        start = self.current_page * self.page_size
        return self.all_authors[start : start + self.page_size]

    def create_embed(self, success_message: Optional[str] = None) -> discord.Embed:
        page_authors = self.get_current_page_authors()
        description_lines = []
        if not page_authors:
            description_lines.append("您还没有关注任何作者。")
        else:
            for author in page_authors:
                new_post_text = (
                    f" - 📬 **{author.get('new_posts', 0)}** 个新帖"
                    if author.get("new_posts", 0) > 0
                    else ""
                )
                description_lines.append(
                    f"• <@{author['author_id']}> (`{author['author_name']}`){new_post_text}"
                )

        description = "从下面的菜单中选择一位作者进行取关。\n\n" + "\n".join(
            description_lines
        )
        if success_message:
            description = f"{success_message}\n\n" + description

        embed = discord.Embed(
            title="我关注的作者列表",
            description=description,
            color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
        )
        embed.set_footer(text=f"第 {self.current_page + 1} / {self.total_pages} 页")
        return embed

    def update_components(self):
        self.clear_items()
        page_authors = self.get_current_page_authors()
        if page_authors:
            options = [
                discord.SelectOption(label=a["author_name"], value=str(a["author_id"]))
                for a in page_authors
            ]
            select_menu = ui.Select(
                placeholder="选择一位作者进行取关...", options=options
            )
            select_menu.callback = self.select_callback
            self.add_item(select_menu)

        prev_button = ui.Button(
            label="◀️ 上一页",
            style=discord.ButtonStyle.secondary,
            disabled=(self.current_page == 0),
        )
        prev_button.callback = self.prev_page
        self.add_item(prev_button)

        next_button = ui.Button(
            label="下一页 ▶️",
            style=discord.ButtonStyle.secondary,
            disabled=(self.current_page >= self.total_pages - 1),
        )
        next_button.callback = self.next_page
        self.add_item(next_button)

        back_button = ui.Button(
            label="返回主菜单", style=discord.ButtonStyle.grey, row=2
        )
        back_button.callback = self.back_to_main_menu
        self.add_item(back_button)

    async def back_to_main_menu(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = MainMenuView(self.profile_cog)
        await interaction.edit_original_response(embed=view.create_embed(), view=view)

    async def select_callback(self, interaction: discord.Interaction):
        from src.modules.author_follow.services.author_follow_service import (
            UnfollowResult,
        )

        await interaction.response.defer()
        data = cast(dict[str, Any], interaction.data)
        author_id = int(data["values"][0])
        result = await self.author_follow_service.unfollow_author(
            self.user_id, author_id
        )

        if result == UnfollowResult.SUCCESS:
            author_name = next(
                (
                    a["author_name"]
                    for a in self.all_authors
                    if a["author_id"] == author_id
                ),
                "未知作者",
            )
            self.all_authors = [
                a for a in self.all_authors if a["author_id"] != author_id
            ]
            self.total_pages = (
                math.ceil(len(self.all_authors) / self.page_size)
                if self.all_authors
                else 1
            )
            if self.current_page >= self.total_pages:
                self.current_page = max(0, self.total_pages - 1)
            self.update_components()
            await interaction.edit_original_response(
                embed=self.create_embed(f"✅ 已成功取关 **{author_name}**。"), view=self
            )
        else:
            await interaction.edit_original_response(
                embed=self.create_embed("🤔 操作失败，您可能已经取关了这位作者。"),
                view=self,
            )

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
    def __init__(
        self,
        sub_cog: "SubscriptionTracker",
        profile_cog: "UserProfileCog",
        user_id: int,
        channel_id: int,
    ):
        timeout = int(os.getenv("SUBSCRIPTION_MANAGE_VIEW_TIMEOUT_SECONDS", "300"))
        super().__init__(timeout=timeout)
        self.sub_cog = sub_cog
        self.profile_cog = profile_cog
        self.user_id = user_id
        self.channel_id = channel_id
        self.service = sub_cog.subscription_service
        self.message: Optional[discord.Message] = None

    async def update_embed(self):
        embed = await self.sub_cog.create_subscription_embed(
            self.user_id, self.channel_id
        )
        if self.message:
            await self.message.edit(embed=embed, view=self)

    @ui.button(label="⭐ 添加关注词", style=discord.ButtonStyle.success, row=0)
    async def add_followed(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SubscriptionModal(self, "followed"))

    @ui.button(label="➖ 删除关注词", style=discord.ButtonStyle.danger, row=0)
    async def edit_followed(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            SubscriptionModal(self, "followed", edit_mode=True)
        )

    @ui.button(label="⭐ 添加屏蔽词", style=discord.ButtonStyle.success, row=1)
    async def add_blocked(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(SubscriptionModal(self, "blocked"))

    @ui.button(label="➖ 删除屏蔽词", style=discord.ButtonStyle.danger, row=1)
    async def edit_blocked(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(
            SubscriptionModal(self, "blocked", edit_mode=True)
        )

    @ui.button(label="返回频道列表", style=discord.ButtonStyle.primary, row=2)
    async def back_to_channel_select(
        self, interaction: discord.Interaction, button: ui.Button
    ):
        # This now goes back to the main subscription menu
        await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)

    @ui.button(label="❌ 取消关注此频道", style=discord.ButtonStyle.danger, row=2)
    async def unfollow_channel(
        self, interaction: discord.Interaction, button: ui.Button
    ):
        try:
            await self.service.unfollow_channel(self.user_id, self.channel_id)
            # After unfollowing, send the user back to the main subscription menu
            await self.sub_cog.send_main_subscription_view(
                interaction, self.profile_cog
            )
        except Exception:
            log_context = {"user_id": self.user_id, "channel_id": self.channel_id}
            logger.error("取消关注频道失败", extra=log_context, exc_info=True)
            await interaction.edit_original_response(
                content="取消关注失败，请稍后再试。", embed=None, view=None
            )


class SubscriptionModal(ui.Modal):
    def __init__(
        self,
        parent_view: SubscriptionManageView,
        keyword_type: str,
        edit_mode: bool = False,
    ):
        self.parent_view = parent_view
        self.service: "SubscriptionService" = parent_view.service
        self.user_id = parent_view.user_id
        self.channel_id = parent_view.channel_id
        self.keyword_type = keyword_type
        self.edit_mode = edit_mode

        action = "编辑" if edit_mode else "添加"
        kw_type_name = "关注" if keyword_type == "followed" else "屏蔽"
        super().__init__(title=f"{action}{kw_type_name}词")

        self.keywords_input = ui.TextInput(
            label="关键词 (用空格或换行分隔):请输入您要删除的关键词",
            style=discord.TextStyle.paragraph,
            placeholder="例如: 关键词1 关键词2",
            required=not edit_mode,
        )
        self.add_item(self.keywords_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # 如果输入为空，则不进行任何操作
        if not self.keywords_input.value.strip():
            return

        new_keywords_set = {
            kw.strip().lower() for kw in self.keywords_input.value.split()
        }

        current_sub = await self.service.get_subscription(
            self.user_id, self.channel_id
        ) or {"followed_keywords": [], "blocked_keywords": []}

        key = f"{self.keyword_type}_keywords"
        current_keywords = set(current_sub.get(key, []))

        if self.edit_mode:
            # 编辑模式：删除指定的关键词
            current_keywords -= new_keywords_set
        else:
            # 添加模式：合并关键词
            current_keywords.update(new_keywords_set)

        current_sub[key] = list(current_keywords)

        await self.service.update_subscription(
            self.user_id,
            self.channel_id,
            current_sub["followed_keywords"],
            current_sub["blocked_keywords"],
        )
        await self.parent_view.update_embed()


# --- New Subscription Main Menu ---
class SubscriptionMenuView(ui.View):
    def __init__(
        self,
        sub_cog: "SubscriptionTracker",
        profile_cog: "UserProfileCog",
        user_id: int,
        subscribed_channels: List[discord.ForumChannel],
    ):
        timeout = int(os.getenv("SUBSCRIPTION_MENU_VIEW_TIMEOUT_SECONDS", "180"))
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
            options = [
                discord.SelectOption(label=ch.name, value=str(ch.id))
                for ch in self.subscribed_channels
            ]
            select = ui.Select(
                placeholder="选择一个已关注的频道进行管理...", options=options
            )
            select.callback = self.select_channel_callback
            self.add_item(select)

        # Button to add a new subscription
        add_button = ui.Button(
            label="➕ 关注新频道", style=discord.ButtonStyle.success, row=1
        )
        add_button.callback = self.add_new_subscription
        self.add_item(add_button)

        # Back to main menu button
        back_button = ui.Button(
            label="返回主菜单", style=discord.ButtonStyle.grey, row=2
        )
        back_button.callback = self.back_to_main_menu
        self.add_item(back_button)

    def create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔔 我关注的频道", color=int(os.getenv("THEME_COLOR", "0x49989a"), 16)
        )
        if not self.subscribed_channels:
            embed.description = (
                "您目前没有关注任何频道。\n\n点击下面的“关注新频道”按钮开始吧！"
            )
        else:
            description = "您已关注以下频道。从下拉菜单中选择一个进行管理。\n\n"
            description += "\n".join(
                f"• {ch.mention} (`{ch.name}`)" for ch in self.subscribed_channels
            )
            embed.description = description

        embed.set_footer(text="使用下面的按钮来添加新的频道关注。")
        return embed

    async def select_channel_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = cast(dict[str, Any], interaction.data)
        channel_id = int(data["values"][0])
        await self.sub_cog.send_subscription_manage_ui(
            interaction, self.user_id, channel_id, self.profile_cog
        )

    async def add_new_subscription(self, interaction: discord.Interaction):
        await interaction.response.defer()
        all_channels = await self.sub_cog.get_target_forum_channels()
        subscribed_ids = {ch.id for ch in self.subscribed_channels}
        available_channels = [ch for ch in all_channels if ch.id not in subscribed_ids]

        view = ChannelSelectView(
            self.sub_cog, self.profile_cog, self.user_id, available_channels
        )
        embed = view.create_embed()
        await interaction.edit_original_response(embed=embed, view=view)

    async def back_to_main_menu(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = MainMenuView(self.profile_cog)
        await interaction.edit_original_response(embed=view.create_embed(), view=view)


# --- New Channel Selection for Following ---
# 每页显示的频道数量（Discord SelectMenu 最多25个选项）
CHANNEL_PAGE_SIZE = 25


class ChannelMultiSelect(ui.Select):
    def __init__(
        self,
        channels: List[discord.ForumChannel],
        selected_values: Optional[List[str]] = None,
    ):
        self.all_channels = channels
        self.selected_values = selected_values or []

        options = [
            discord.SelectOption(label=ch.name, value=str(ch.id)) for ch in channels
        ]
        if not options:
            options.append(
                discord.SelectOption(
                    label="没有可供关注的新频道了", value="disabled", default=True
                )
            )

        # 恢复之前选中的状态
        for opt in options:
            if opt.value in self.selected_values:
                opt.default = True

        super().__init__(
            placeholder="选择一个或多个频道进行关注...",
            min_values=1,
            max_values=min(len(options), 25),  # Discord limit
            options=options,
            disabled=(not channels),
        )

    async def callback(self, interaction: discord.Interaction):
        """
        This callback is triggered when the user makes a selection.
        We simply defer the interaction to prevent a "Interaction failed" error
        and allow the user to proceed to click the confirm button.
        """
        await interaction.response.defer()


class ChannelSelectView(ui.View):
    def __init__(
        self,
        sub_cog: "SubscriptionTracker",
        profile_cog: "UserProfileCog",
        user_id: int,
        available_channels: List[discord.ForumChannel],
        current_page: int = 1,
    ):
        timeout = int(os.getenv("CHANNEL_SELECT_VIEW_TIMEOUT_SECONDS", "180"))
        super().__init__(timeout=timeout)
        self.sub_cog = sub_cog
        self.profile_cog = profile_cog
        self.user_id = user_id
        self.all_channels = available_channels
        self.current_page = current_page
        self.selected_channel_ids: List[str] = []  # 跨页保存选中的频道ID

        # 计算分页
        self.total_pages = (
            math.ceil(len(available_channels) / CHANNEL_PAGE_SIZE)
            if available_channels
            else 1
        )
        self.total_pages = max(1, self.total_pages)

        # 获取当前页的频道
        start_idx = (current_page - 1) * CHANNEL_PAGE_SIZE
        end_idx = start_idx + CHANNEL_PAGE_SIZE
        current_page_channels = available_channels[start_idx:end_idx]

        self.select_menu = ChannelMultiSelect(
            current_page_channels, self.selected_channel_ids
        )
        self.add_item(self.select_menu)

        # 更新翻页按钮状态
        self._update_pagination_buttons()

    def _update_pagination_buttons(self):
        """更新翻页按钮的禁用状态"""
        self.prev_page.disabled = self.current_page <= 1
        self.next_page.disabled = self.current_page >= self.total_pages

    def create_embed(self) -> discord.Embed:
        page_info = (
            f"（第 {self.current_page}/{self.total_pages} 页）"
            if self.total_pages > 1
            else ""
        )
        description = f"请从下面的列表中选择一个或多个您想关注的频道，然后点击「确认关注」。\n\n共 {len(self.all_channels)} 个可关注频道{page_info}"
        return discord.Embed(
            title="➕ 关注新频道",
            description=description,
            color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
        )

    @ui.button(label="◀ 上一页", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        # 保存当前页的选中状态
        if self.select_menu.values and self.select_menu.values[0] != "disabled":
            for val in self.select_menu.values:
                if val not in self.selected_channel_ids:
                    self.selected_channel_ids.append(val)

        # 切换到上一页
        self.current_page = max(1, self.current_page - 1)
        await self._refresh_view(interaction)

    @ui.button(label="▶ 下一页", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        # 保存当前页的选中状态
        if self.select_menu.values and self.select_menu.values[0] != "disabled":
            for val in self.select_menu.values:
                if val not in self.selected_channel_ids:
                    self.selected_channel_ids.append(val)

        # 切换到下一页
        self.current_page = min(self.total_pages, self.current_page + 1)
        await self._refresh_view(interaction)

    async def _refresh_view(self, interaction: discord.Interaction):
        """刷新视图，更新当前页的频道列表"""
        # 移除旧的 select menu
        self.remove_item(self.select_menu)

        # 获取当前页的频道
        start_idx = (self.current_page - 1) * CHANNEL_PAGE_SIZE
        end_idx = start_idx + CHANNEL_PAGE_SIZE
        current_page_channels = self.all_channels[start_idx:end_idx]

        # 创建新的 select menu
        self.select_menu = ChannelMultiSelect(
            current_page_channels, self.selected_channel_ids
        )
        self.add_item(self.select_menu)

        # 更新翻页按钮状态
        self._update_pagination_buttons()

        # 更新消息
        embed = self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="✅ 确认关注", style=discord.ButtonStyle.success, row=2)
    async def confirm_follow(self, interaction: discord.Interaction, button: ui.Button):
        # 合并当前页的选中状态和之前保存的选中状态
        if self.select_menu.values and self.select_menu.values[0] != "disabled":
            for val in self.select_menu.values:
                if val not in self.selected_channel_ids:
                    self.selected_channel_ids.append(val)

        if not self.selected_channel_ids:
            # 如果没有选中任何频道，返回主菜单
            await self.sub_cog.send_main_subscription_view(
                interaction, self.profile_cog
            )
            return

        service = self.sub_cog.subscription_service
        for channel_id_str in self.selected_channel_ids:
            try:
                await service.follow_channel(self.user_id, int(channel_id_str))
            except Exception:
                log_context = {"user_id": self.user_id, "channel_id": channel_id_str}
                logger.error(
                    "在多选流程中关注频道失败", extra=log_context, exc_info=True
                )

        # After following, show the updated main subscription menu
        await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)

    @ui.button(label="返回", style=discord.ButtonStyle.grey, row=2)
    async def back_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.sub_cog.send_main_subscription_view(interaction, self.profile_cog)


# --- Author Follow UI ---
# ... (FollowsManageView and other classes remain unchanged) ...
# NOTE: For brevity, the unchanged classes are omitted.
# The new Favorites UI classes will be added at the end.

# --- Favorites UI ---
# This is now a default value, can be overridden by .env
FAVORITES_PAGE_SIZE = int(os.getenv("FAVORITES_PAGE_SIZE", "10"))


class FavoritesManageView(ui.View):
    def __init__(
        self,
        profile_cog: "UserProfileCog",
        favorites_service: FavoritesService,
        user: discord.User,
        initial_page: int = 1,
    ):
        timeout = int(os.getenv("FAVORITES_MANAGE_VIEW_TIMEOUT_SECONDS", "180"))
        super().__init__(timeout=timeout)
        self.profile_cog = profile_cog
        self.favorites_service = favorites_service
        self.user = user
        self.current_page = initial_page
        self.total_pages = 0

    async def send_initial_message(self, interaction: discord.Interaction):
        await self.update_view_internals()
        embed = await self.create_favorites_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    async def update_view_internals(self):
        total_items = await self.favorites_service.get_favorites_count(self.user.id)
        self.total_pages = (
            math.ceil(total_items / FAVORITES_PAGE_SIZE) if total_items > 0 else 1
        )

        self.clear_items()

        prev_button = ui.Button(
            label="⬅️ 上一页",
            style=discord.ButtonStyle.grey,
            disabled=(self.current_page <= 1),
        )
        prev_button.callback = self.prev_page_button
        self.add_item(prev_button)

        next_button = ui.Button(
            label="➡️ 下一页",
            style=discord.ButtonStyle.grey,
            disabled=(self.current_page >= self.total_pages),
        )
        next_button.callback = self.next_page_button
        self.add_item(next_button)

        # The refresh button is now the primary action on this view.
        # It will be moved here from the BatchLeaveView.
        refresh_button = ui.Button(
            label="🔄 刷新数据库", style=discord.ButtonStyle.primary
        )
        refresh_button.callback = self.refresh_active_threads_button
        self.add_item(refresh_button)

        # --- Row 1: Action Buttons ---
        favorite_button = ui.Button(
            label="📥 批量收藏", style=discord.ButtonStyle.success, row=1
        )
        favorite_button.callback = self.batch_favorite_button
        self.add_item(favorite_button)

        unfavorite_button = ui.Button(
            label="🗑️ 批量取消收藏", style=discord.ButtonStyle.danger, row=1
        )
        unfavorite_button.callback = self.batch_unfavorite_button
        self.add_item(unfavorite_button)

        leave_button = ui.Button(
            label="🚪 批量退出子区", style=discord.ButtonStyle.secondary, row=1
        )
        leave_button.callback = self.batch_leave_button
        self.add_item(leave_button)

        back_button = ui.Button(
            label="返回主菜单", style=discord.ButtonStyle.grey, row=2
        )
        back_button.callback = self.back_to_main_menu
        self.add_item(back_button)

    async def create_favorites_embed(self) -> discord.Embed:
        favorites = await self.favorites_service.get_user_favorites(
            self.user.id, self.current_page, FAVORITES_PAGE_SIZE
        )

        embed = discord.Embed(
            title=f"📜 {self.user.display_name} 的收藏夹",
            description="管理您收藏的帖子，或对当前已加入的活跃帖子进行批量操作。\n\n"
            "**注意**：批量操作的数据依赖于后台扫描（约2小时一次）。如果列表不准确，请先点击“刷新数据库”。",
            color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
        )

        if not favorites:
            embed.description = (
                embed.description or ""
            ) + "\n\n*您还没有收藏任何帖子。*"
        else:
            for fav in favorites:
                thread_link = (
                    f"https://discord.com/channels/{fav['guild_id']}/{fav['thread_id']}"
                )
                embed.add_field(
                    name=f"🏷️ {fav['thread_name']}",
                    value=f"[点击跳转]({thread_link}) - 收藏于 <t:{int(fav['added_at'].timestamp())}:R>",
                    inline=False,
                )

        embed.set_footer(text=f"第 {self.current_page} / {self.total_pages} 页")
        return embed

    async def prev_page_button(self, interaction: discord.Interaction):
        if self.current_page > 1:
            self.current_page -= 1
            await self.update_view_internals()
            embed = await self.create_favorites_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    async def next_page_button(self, interaction: discord.Interaction):
        if self.current_page < self.total_pages:
            self.current_page += 1
            await self.update_view_internals()
            embed = await self.create_favorites_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    async def refresh_active_threads_button(self, interaction: discord.Interaction):
        """
        This is the new central refresh logic, moved from BatchLeaveView.
        It now includes a per-user cooldown.
        """
        # 1. Check for cooldown
        bucket = self.profile_cog.refresh_cooldown.get_bucket(interaction.message)
        retry_after = bucket.update_rate_limit() if bucket else None
        if retry_after:
            # User is on cooldown, inform them and do nothing.
            await interaction.response.send_message(
                f"⏳ 操作过于频繁，请在 **{int(retry_after)}** 秒后重试。",
                ephemeral=True,
                delete_after=5,
            )
            return

        # 2. If not on cooldown, proceed with the refresh logic
        await interaction.response.edit_message(
            content="🔄 正在强制刷新您在此服务器的活跃帖子列表，这可能需要一点时间...",
            embed=None,
            view=None,
        )
        try:
            scanner_service = self.profile_cog.bot.scanner_service
            if not scanner_service:
                raise AttributeError("Scanner service not found on bot object.")

            await scanner_service.scan_guild(interaction.guild)

            await self.update_view_internals()
            embed = await self.create_favorites_embed()
            embed.description = "✅ **刷新成功！**\n\n" + (embed.description or "")

            await interaction.edit_original_response(content="", embed=embed, view=self)

        except Exception:
            log_context = {
                "user_id": interaction.user.id,
                "guild_id": interaction.guild.id if interaction.guild else None,
            }
            logger.error("手动刷新数据库失败", extra=log_context, exc_info=True)
            error_embed = discord.Embed(
                title="❌ 刷新失败",
                description="在刷新数据库时发生错误，请稍后再试或联系管理员。",
                color=discord.Color.red(),
            )
            await interaction.edit_original_response(
                content="", embed=error_embed, view=self
            )

    async def batch_favorite_button(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="正在加载可收藏的帖子列表...", embed=None, view=None
        )

        guild = interaction.guild
        if guild is None:
            return
        unfavorited_threads_data = (
            await self.favorites_service.get_unfavorited_threads_for_user(
                self.user, guild
            )
        )

        log_context = {"user_id": interaction.user.id, "guild_id": guild.id}
        logger.info(
            f"获取到 {len(unfavorited_threads_data)} 个可收藏的帖子。",
            extra=log_context,
        )

        if not unfavorited_threads_data:
            embed = discord.Embed(
                title="📥 批量收藏",
                description="✅ 您已经收藏了所有当前已加入的活跃帖子。\n\n"
                "如果这个列表不准确（例如您刚刚加入了新帖子），请返回主菜单并点击“刷新数据库”。",
                color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
            )
            # We need to re-add the back button for navigation
            back_button = ui.Button(label="返回", style=discord.ButtonStyle.grey)
            back_button.callback = self.back_to_main_menu
            view = ui.View(timeout=60)
            view.add_item(back_button)
            await interaction.edit_original_response(content="", embed=embed, view=view)
            return

        # No need to fetch threads again, we pass the data directly
        view = BatchFavoriteConfirmView(
            self.profile_cog,
            self.favorites_service,
            self.user,
            cast(List[dict[str, Any]], unfavorited_threads_data),
        )
        embed = view.create_embed()
        await interaction.edit_original_response(content="", embed=embed, view=view)

    async def batch_unfavorite_button(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="⌛ 正在加载收藏列表...", embed=None, view=None
        )

        total_favorites = await self.favorites_service.get_favorites_count(self.user.id)
        if total_favorites == 0:
            embed = discord.Embed(
                title="🗑️ 批量取消收藏",
                description="您还没有任何收藏，无法执行此操作。",
                color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
            )
            await interaction.edit_original_response(content="", embed=embed, view=self)
            return

        all_favorites = await self.favorites_service.get_user_favorites(
            self.user.id, 1, total_favorites
        )

        view = BatchUnfavoriteView(
            self.profile_cog, self.favorites_service, self.user, all_favorites
        )
        embed = view.create_embed()
        await interaction.edit_original_response(embed=embed, view=view)

    async def batch_leave_button(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="⌛ 正在加载活跃帖子列表...", embed=None, view=None
        )

        guild = interaction.guild
        if guild is None:
            return
        active_threads_data = await self.favorites_service.get_active_threads_for_user(
            self.user, guild
        )

        # 无论是否有活跃帖子，都创建 BatchLeaveView，让它自己处理显示逻辑
        view = BatchLeaveView(
            self.profile_cog, self.favorites_service, self.user, active_threads_data
        )
        embed = view.create_embed()
        await interaction.edit_original_response(content="", embed=embed, view=view)

    async def back_to_main_menu(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = MainMenuView(self.profile_cog)
        await interaction.edit_original_response(embed=view.create_embed(), view=view)


class BatchFavoriteConfirmView(ui.View):
    """
    A view to confirm batch favoriting threads.
    This is a simple confirmation view without pagination or selection.
    """

    def __init__(
        self,
        profile_cog: "UserProfileCog",
        favorites_service: FavoritesService,
        user: discord.User,
        unfavorited_threads: List[Any],
    ):
        timeout = int(os.getenv("BATCH_FAVORITE_CONFIRM_VIEW_TIMEOUT_SECONDS", "180"))
        super().__init__(timeout=timeout)
        self.profile_cog = profile_cog
        self.favorites_service = favorites_service
        self.user = user
        self.unfavorited_threads = unfavorited_threads
        self.update_components()

    def update_components(self):
        """Adds confirm and cancel buttons."""
        self.clear_items()

        confirm_button = ui.Button(
            label="✅ 确认收藏", style=discord.ButtonStyle.success
        )
        confirm_button.callback = self.confirm_button
        self.add_item(confirm_button)

        cancel_button = ui.Button(label="取消", style=discord.ButtonStyle.grey)
        cancel_button.callback = self.cancel_button
        self.add_item(cancel_button)

    def create_embed(self) -> discord.Embed:
        """Creates the embed message for confirmation."""
        thread_count = len(self.unfavorited_threads)
        description = (
            f"我们找到了 **{thread_count}** 个您已加入但尚未收藏的帖子。\n\n"
            "点击“确认收藏”将把它们全部添加到你的收藏夹。\n\n"
            "*如果列表不准确，请先返回主菜单刷新。*"
        )

        embed = discord.Embed(
            title=f"📥 确认批量收藏 {thread_count} 个帖子",
            description=description,
            color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
        )
        # Display a few thread names as examples
        if self.unfavorited_threads:
            # The data is now a list of dicts, not thread objects
            threads_data = cast(List[dict[str, Any]], self.unfavorited_threads)
            sample_threads = "\n".join(
                f"- {t['thread_name']}" for t in threads_data[:5]
            )
            embed.add_field(name="帖子示例:", value=sample_threads, inline=False)

        return embed

    def disable_all_components(self):
        """Disables all components in the view."""
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = True

    async def confirm_button(self, interaction: discord.Interaction):
        self.disable_all_components()
        processing_embed = self.create_embed()
        processing_embed.description = (
            f"⚙️ 正在收藏 **{len(self.unfavorited_threads)}** 个帖子，请稍候..."
        )
        processing_embed.color = int(os.getenv("THEME_COLOR", "0x49989a"), 16)
        await interaction.response.edit_message(embed=processing_embed, view=self)

        # We need to fetch the thread objects before favoriting
        threads_data = cast(List[dict[str, Any]], self.unfavorited_threads)
        thread_ids_to_fetch = [t["thread_id"] for t in threads_data]

        guild = interaction.guild
        if guild is None:
            return

        async def fetch_thread(thread_id):
            try:
                return await retry_on_discord_error(
                    lambda: guild.fetch_channel(thread_id),
                    f"批量收藏 - 获取帖子 {thread_id}",
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.errors.DiscordServerError,
            ):
                return None

        tasks = [fetch_thread(tid) for tid in thread_ids_to_fetch]
        threads_to_favorite = [
            t for t in await asyncio.gather(*tasks) if isinstance(t, discord.Thread)
        ]

        newly_favorited = await self.favorites_service.batch_favorite_threads(
            self.user, threads_to_favorite
        )

        result_view = FavoritesManageView(
            self.profile_cog, self.favorites_service, self.user
        )
        await result_view.update_view_internals()
        result_embed = await result_view.create_favorites_embed()

        summary = f"✅ **批量收藏完成！**\n**{newly_favorited}** 个新帖子被添加到了你的收藏夹。"

        result_embed.description = f"{summary}\n\n" + (result_embed.description or "")

        await interaction.edit_original_response(embed=result_embed, view=result_view)

    async def cancel_button(self, interaction: discord.Interaction):
        view = FavoritesManageView(self.profile_cog, self.favorites_service, self.user)
        # This is the initial response to the cancel button's interaction
        await interaction.response.edit_message(
            content="正在返回...", embed=None, view=None
        )
        await view.send_initial_message(interaction)


# --- Batch Unfavorite UI ---


class BatchUnfavoriteSelect(ui.Select):
    def __init__(self, favorites_on_page: List[dict], previously_selected_ids: set):
        options = []
        for fav in favorites_on_page:
            options.append(
                discord.SelectOption(
                    label=fav["thread_name"][:100],
                    value=str(fav["thread_id"]),
                    default=(fav["thread_id"] in previously_selected_ids),
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="本页没有可操作的收藏", value="disabled", default=True
                )
            )

        super().__init__(
            placeholder="选择或取消选择要取消收藏的帖子...",
            min_values=0,
            max_values=len(options)
            if options and options[0].value != "disabled"
            else 0,
            options=options,
            disabled=(not favorites_on_page),
        )
        self.threads_on_this_page_ids = {fav["thread_id"] for fav in favorites_on_page}

    async def callback(self, interaction: discord.Interaction):
        parent_view = cast("BatchUnfavoriteView", self.view)
        parent_view.selected_to_unfavorite_ids.difference_update(
            self.threads_on_this_page_ids
        )
        parent_view.selected_to_unfavorite_ids.update(
            {int(v) for v in self.values if v != "disabled"}
        )
        await parent_view.update_message(interaction)


class BatchUnfavoriteView(ui.View):
    def __init__(
        self,
        profile_cog: "UserProfileCog",
        favorites_service: FavoritesService,
        user: discord.User,
        all_favorites: List[dict],
    ):
        timeout = int(os.getenv("BATCH_UNFAVORITE_VIEW_TIMEOUT_SECONDS", "180"))
        super().__init__(timeout=timeout)
        self.PAGE_SIZE = int(os.getenv("BATCH_UNFAVORITE_PAGE_SIZE", "25"))
        self.profile_cog = profile_cog
        self.favorites_service = favorites_service
        self.user = user
        self.all_favorites = all_favorites
        self.selected_to_unfavorite_ids = set()
        self.current_page = 0
        self.total_pages = (
            math.ceil(len(self.all_favorites) / self.PAGE_SIZE)
            if self.all_favorites
            else 1
        )
        self.update_components()

    def get_current_page_favorites(self) -> List[dict]:
        start = self.current_page * self.PAGE_SIZE
        return self.all_favorites[start : start + self.PAGE_SIZE]

    def update_components(self):
        self.clear_items()

        page_favorites = self.get_current_page_favorites()
        if page_favorites:
            select_menu = BatchUnfavoriteSelect(
                page_favorites, self.selected_to_unfavorite_ids
            )
            self.add_item(select_menu)

        prev_button = ui.Button(
            label="◀️ 上一页",
            style=discord.ButtonStyle.secondary,
            disabled=(self.current_page == 0),
            row=1,
        )
        prev_button.callback = self.prev_page
        self.add_item(prev_button)

        next_button = ui.Button(
            label="下一页 ▶️",
            style=discord.ButtonStyle.secondary,
            disabled=(self.current_page >= self.total_pages - 1),
            row=1,
        )
        next_button.callback = self.next_page
        self.add_item(next_button)

        confirm_button = ui.Button(
            label="✅ 确认取消收藏", style=discord.ButtonStyle.danger, row=2
        )
        confirm_button.callback = self.confirm_button
        self.add_item(confirm_button)

        cancel_button = ui.Button(label="取消", style=discord.ButtonStyle.grey, row=2)
        cancel_button.callback = self.cancel_button
        self.add_item(cancel_button)

    def create_embed(self) -> discord.Embed:
        description = (
            f"您共有 **{len(self.all_favorites)}** 个收藏的帖子。\n\n"
            "请从下面的菜单中，选择您希望**取消收藏**的帖子。\n\n"
            f"您当前已选择 **{len(self.selected_to_unfavorite_ids)}** 个帖子准备取消收藏。"
        )

        embed = discord.Embed(
            title="🗑️ 批量取消收藏确认",
            description=description,
            color=int(os.getenv("THEME_COLOR", "0x49989a"), 16),
        ).set_footer(text=f"第 {self.current_page + 1} / {self.total_pages} 页")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        # This is the response to the select menu's interaction
        await interaction.response.defer()
        self.update_components()
        embed = self.create_embed()
        # We edit the original message that the view is attached to
        await interaction.edit_original_response(embed=embed, view=self)

    async def prev_page(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)

    async def next_page(self, interaction: discord.Interaction):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_message(interaction)

    def disable_all_components(self):
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = True

    async def confirm_button(self, interaction: discord.Interaction):
        self.disable_all_components()
        processing_embed = self.create_embed()
        processing_embed.description = f"⚙️ 正在处理 **{len(self.selected_to_unfavorite_ids)}** 个帖子的取消收藏操作，请稍候..."
        processing_embed.color = int(os.getenv("THEME_COLOR", "0x49989a"), 16)
        await interaction.response.edit_message(embed=processing_embed, view=self)

        if not self.selected_to_unfavorite_ids:
            result_view = FavoritesManageView(
                self.profile_cog, self.favorites_service, self.user
            )
            await result_view.update_view_internals()
            result_embed = await result_view.create_favorites_embed()
            result_embed.description = (
                "⚠️ **操作取消：** 您没有选择任何要取消收藏的帖子。\n\n"
                + (result_embed.description or "")
            )
            await interaction.edit_original_response(
                embed=result_embed, view=result_view
            )
            return

        removed_count = await self.favorites_service.batch_unfavorite_threads(
            self.user.id, list(self.selected_to_unfavorite_ids)
        )

        result_view = FavoritesManageView(
            self.profile_cog, self.favorites_service, self.user
        )
        await result_view.update_view_internals()
        result_embed = await result_view.create_favorites_embed()

        summary = f"✅ **操作完成！**\n成功取消收藏 **{removed_count}** 个帖子。"

        result_embed.description = f"{summary}\n\n" + (result_embed.description or "")
        await interaction.edit_original_response(embed=result_embed, view=result_view)

    async def cancel_button(self, interaction: discord.Interaction):
        view = FavoritesManageView(self.profile_cog, self.favorites_service, self.user)
        await interaction.response.edit_message(
            content="正在返回...", embed=None, view=None
        )
        await view.send_initial_message(interaction)


# --- Batch Leave UI ---


class BatchLeaveSelect(ui.Select):
    def __init__(self, threads_data_on_page: List[dict], previously_selected_ids: set):
        options = []
        for t_data in threads_data_on_page:
            # Use the name from the DB if available, otherwise create a default name
            thread_name = t_data.get("thread_name") or f"帖子ID: {t_data['thread_id']}"
            thread_id = t_data["thread_id"]
            options.append(
                discord.SelectOption(
                    label=thread_name[:100],
                    value=str(thread_id),
                    default=(thread_id in previously_selected_ids),
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="本页没有可以操作的帖子", value="disabled", default=True
                )
            )

        super().__init__(
            placeholder="选择或取消选择要退出的帖子...",
            min_values=0,
            max_values=len(options)
            if options and options[0].value != "disabled"
            else 0,
            options=options,
            disabled=(not threads_data_on_page),
        )
        self.threads_on_this_page_ids = {t["thread_id"] for t in threads_data_on_page}

    async def callback(self, interaction: discord.Interaction):
        parent_view = cast("BatchLeaveView", self.view)
        parent_view.selected_to_leave_ids.difference_update(
            self.threads_on_this_page_ids
        )
        parent_view.selected_to_leave_ids.update(
            {int(v) for v in self.values if v != "disabled"}
        )
        await parent_view.update_message(interaction)


class BatchLeaveView(ui.View):
    def __init__(
        self,
        profile_cog: "UserProfileCog",
        favorites_service: FavoritesService,
        user: discord.User,
        all_threads_data: List[dict],
    ):
        timeout = int(os.getenv("BATCH_LEAVE_VIEW_TIMEOUT_SECONDS", "180"))
        super().__init__(timeout=timeout)
        self.PAGE_SIZE = int(os.getenv("BATCH_LEAVE_PAGE_SIZE", "25"))
        self.profile_cog = profile_cog
        self.favorites_service = favorites_service
        self.user = user
        self.all_threads_data = all_threads_data
        self.selected_to_leave_ids = set()
        self.current_page = 0
        self.total_pages = (
            math.ceil(len(self.all_threads_data) / self.PAGE_SIZE)
            if self.all_threads_data
            else 1
        )
        self.update_components()

    def get_current_page_threads_data(self) -> List[dict]:
        start = self.current_page * self.PAGE_SIZE
        return self.all_threads_data[start : start + self.PAGE_SIZE]

    def update_components(self):
        self.clear_items()

        # The refresh button is gone from here.
        cancel_button = ui.Button(label="取消", style=discord.ButtonStyle.grey, row=2)
        cancel_button.callback = self.cancel_button
        self.add_item(cancel_button)

        # If there is data, add the select menu, pagination, and confirm button
        if self.all_threads_data:
            page_threads_data = self.get_current_page_threads_data()
            select_menu = BatchLeaveSelect(
                page_threads_data, self.selected_to_leave_ids
            )
            self.add_item(select_menu)

            prev_button = ui.Button(
                label="◀️ 上一页",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page == 0),
                row=1,
            )
            prev_button.callback = self.prev_page
            self.add_item(prev_button)

            next_button = ui.Button(
                label="下一页 ▶️",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page >= self.total_pages - 1),
                row=1,
            )
            next_button.callback = self.next_page
            self.add_item(next_button)

            confirm_button = ui.Button(
                label="✅ 确认退出", style=discord.ButtonStyle.danger, row=2
            )
            confirm_button.callback = self.confirm_button
            self.add_item(confirm_button)

    def create_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🚪 批量退出子区", color=int(os.getenv("THEME_COLOR", "0x49989a"), 16)
        )

        if not self.all_threads_data:
            embed.description = (
                "您当前没有加入任何活跃的帖子。\n\n"
                "如果您刚刚加入了新帖子，请返回主菜单点击“刷新数据库”来更新。"
            )
            embed.set_footer(text="点击“取消”返回收藏夹主菜单。")
        else:
            description = (
                f"您当前加入了 **{len(self.all_threads_data)}** 个活跃帖子。\n\n"
                "请从下面的菜单中，选择您希望**退出**的帖子。\n\n"
                f"您当前已选择 **{len(self.selected_to_leave_ids)}** 个帖子准备退出。\n\n"
                "*如果列表不准确，请先返回主菜单刷新。*"
            )
            embed.description = description
            embed.set_footer(text=f"第 {self.current_page + 1} / {self.total_pages} 页")

        return embed

    async def update_message(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.update_components()
        embed = self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    async def prev_page(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_message(interaction)

    async def next_page(self, interaction: discord.Interaction):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_message(interaction)

    # This button is now removed from this view.

    def disable_all_components(self):
        for item in self.children:
            if isinstance(item, (ui.Button, ui.Select)):
                item.disabled = True

    async def confirm_button(self, interaction: discord.Interaction):
        self.disable_all_components()
        processing_embed = self.create_embed()
        processing_embed.color = int(os.getenv("THEME_COLOR", "0x49989a"), 16)

        if not self.selected_to_leave_ids:
            processing_embed.description = (
                "⚠️ **操作取消：** 您没有选择任何要退出的帖子。"
            )
            await interaction.response.edit_message(embed=processing_embed, view=self)
            await asyncio.sleep(3)
            view = FavoritesManageView(
                self.profile_cog, self.favorites_service, self.user
            )
            await view.send_initial_message(interaction)
            return

        processing_embed.description = (
            f"⚙️ 正在准备退出 **{len(self.selected_to_leave_ids)}** 个帖子，请稍候..."
        )
        await interaction.response.edit_message(embed=processing_embed, view=self)

        guild = interaction.guild
        if guild is None:
            return

        async def fetch_thread(thread_id):
            try:
                return await retry_on_discord_error(
                    lambda: guild.fetch_channel(thread_id),
                    f"批量退出 - 获取帖子 {thread_id}",
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.errors.DiscordServerError,
            ):
                return None

        tasks = [fetch_thread(tid) for tid in self.selected_to_leave_ids]
        threads_to_leave = [
            t for t in await asyncio.gather(*tasks) if isinstance(t, discord.Thread)
        ]

        processing_embed.description = (
            f"⚙️ 正在执行退出操作，共 **{len(threads_to_leave)}** 个帖子..."
        )
        await interaction.edit_original_response(embed=processing_embed, view=self)

        succeeded, failed = await self.favorites_service.batch_leave_threads(
            self.user, threads_to_leave
        )

        result_view = FavoritesManageView(
            self.profile_cog, self.favorites_service, self.user
        )
        await result_view.update_view_internals()
        result_embed = await result_view.create_favorites_embed()

        summary = f"✅ **操作完成！**\n成功退出 **{succeeded}** 个帖子。"
        if failed > 0:
            summary += f"\n**{failed}** 个帖子因权限问题无法退出。"

        result_embed.description = f"{summary}\n\n" + (result_embed.description or "")
        await interaction.edit_original_response(embed=result_embed, view=result_view)

    async def cancel_button(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = FavoritesManageView(self.profile_cog, self.favorites_service, self.user)
        await view.send_initial_message(interaction)

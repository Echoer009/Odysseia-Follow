# src/modules/competition_follow/cogs/competition_tracker.py

import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import re
import os
from typing import Optional
from src.modules.competition_follow.models import Competition
from src.modules.competition_follow.services.follow_service import FollowService
from src.modules.competition_follow.services.parsing_service import parsing_service
from src.modules.competition_follow.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

class CompetitionTracker(commands.Cog):
    """
    一个Cog，用于跟踪比赛信息并通过私信通知用户。
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.notification_service = NotificationService(bot)
        self.follow_service = FollowService(bot.db)
        
        # --- 右键菜单命令 ---
        self.follow_competition_menu = app_commands.ContextMenu(
            name="⭐ 关注此杯赛",
            callback=self.follow_competition_context,
        )
        self.unfollow_competition_menu = app_commands.ContextMenu(
            name="➖ 取关此杯赛",
            callback=self.unfollow_competition_context,
        )
        self.bot.tree.add_command(self.follow_competition_menu)
        self.bot.tree.add_command(self.unfollow_competition_menu)

        self.check_competitions.start()

    def cog_unload(self):
        """当 Cog 被卸载时，清理命令和任务，以支持热重载"""
        self.check_competitions.cancel()
        self.bot.tree.remove_command(self.follow_competition_menu.name, type=self.follow_competition_menu.type)
        self.bot.tree.remove_command(self.unfollow_competition_menu.name, type=self.unfollow_competition_menu.type)

    # ----------------------------------------------------------------
    # Command Logic Implementation (Internal)
    # ----------------------------------------------------------------

    async def _internal_follow(self, interaction: discord.Interaction, message: discord.Message):
        """处理关注比赛的核心逻辑，供所有命令调用。"""
        if not message.embeds:
            await interaction.followup.send("❌ **操作失败**：此消息不包含可供追踪的 Embed。", ephemeral=True)
            return

        initial_ids = parsing_service.extract_submission_ids(message.embeds[0])
        
        success = await self.follow_service.follow_competition(
            user=interaction.user,
            channel_id=message.channel.id,
            message_id=message.id,
            guild_id=message.guild.id,
            initial_ids=initial_ids
        )

        log_context = {
            'user_id': interaction.user.id,
            'guild_id': message.guild.id,
            'channel_id': message.channel.id,
            'message_id': message.id,
            'success': success
        }
        logger.info("用户尝试关注比赛", extra=log_context)

        if success:
            await interaction.followup.send("✅ **关注成功**！当该杯赛有新作品提交时，您会收到私信通知。", ephemeral=True)
        else:
            await interaction.followup.send("🤔 **重复操作**：您已经关注过这个杯赛了。", ephemeral=True)

    async def _internal_unfollow(self, interaction: discord.Interaction, message_id: int):
        """处理取消关注比赛的核心逻辑，供所有命令调用。"""
        success = await self.follow_service.unfollow_competition(interaction.user, message_id)

        log_context = {
            'user_id': interaction.user.id,
            'guild_id': interaction.guild_id,
            'message_id': message_id,
            'success': success
        }
        logger.info("用户尝试取关比赛", extra=log_context)

        if success:
            await interaction.followup.send("✅ **操作成功**：您已取消关注该杯赛。", ephemeral=True)
        else:
            await interaction.followup.send("🤔 **重复操作**：您之前没有关注过这个杯赛。", ephemeral=True)

    # ----------------------------------------------------------------
    # 右键命令
    # ----------------------------------------------------------------

    async def follow_competition_context(self, interaction: discord.Interaction, message: discord.Message):
        """右键菜单 '关注此比赛' 的回调函数"""
        await interaction.response.defer(ephemeral=True)
        await self._internal_follow(interaction, message)

    async def unfollow_competition_context(self, interaction: discord.Interaction, message: discord.Message):
        """右键菜单 '取消关注此比赛' 的回调函数"""
        await interaction.response.defer(ephemeral=True)
        await self._internal_unfollow(interaction, message.id)

    # ----------------------------------------------------------------
    # 斜杠命令
    # ----------------------------------------------------------------

    async def _parse_message_link(self, link: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
        """从Discord消息链接中解析 guild_id, channel_id, 和 message_id。"""
        match = re.match(r"https://discord.com/channels/(\d+)/(\d+)/(\d+)", link)
        if not match:
            return None, None, None
        guild_id, channel_id, message_id = map(int, match.groups())
        return guild_id, channel_id, message_id

    @app_commands.command(name="关注杯赛", description="通过消息链接关注一个杯赛，以接收新作品通知")
    @app_commands.rename(message_link='消息链接')
    async def follow_competition_slash(self, interaction: discord.Interaction, message_link: str):
        await interaction.response.defer(ephemeral=True)

        guild_id, channel_id, message_id = await self._parse_message_link(message_link)

        if not all((guild_id, channel_id, message_id)):
            await interaction.followup.send("❌ **格式错误**：请输入一个有效的 Discord 消息链接。", ephemeral=True)
            return

        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            await self._internal_follow(interaction, message)
        except (discord.NotFound, discord.Forbidden) as e:
            log_context = {'user_id': interaction.user.id, 'guild_id': guild_id, 'channel_id': channel_id, 'message_id': message_id, 'error': str(e)}
            logger.warning("无法访问斜杠命令所需的消息", extra=log_context)
            await interaction.followup.send("❌ **无法访问**：请检查链接是否正确，以及检查bot是否有权限查看该频道和消息。", ephemeral=True)
        except Exception as e:
            log_context = {'user_id': interaction.user.id, 'guild_id': guild_id, 'channel_id': channel_id, 'message_id': message_id}
            logger.error("/关注比赛 命令出错", extra=log_context, exc_info=True)
            await interaction.followup.send("⚙️ **发生未知错误**，请稍后再试或联系管理员。", ephemeral=True)

    @app_commands.command(name="取关杯赛", description="通过消息链接取消关注一个杯赛")
    @app_commands.rename(message_link='消息链接')
    async def unfollow_competition_slash(self, interaction: discord.Interaction, message_link: str):
        await interaction.response.defer(ephemeral=True)

        _, _, message_id = await self._parse_message_link(message_link)

        if not message_id:
            await interaction.followup.send("❌ **格式错误**：请输入一个有效的 Discord 消息链接。", ephemeral=True)
            return
        
        await self._internal_unfollow(interaction, message_id)

    # ----------------------------------------------------------------
    # Background Task
    # ----------------------------------------------------------------

    @tasks.loop(minutes=float(os.getenv('COMPETITION_CHECK_INTERVAL_MINUTES', '1.0')))
    async def check_competitions(self):
        """定期轮询检查所有被关注的比赛是否有更新。"""
        logger.debug("开始执行比赛更新的计划任务...")
        all_competitions = await self.follow_service.get_all_followed_competitions()
        if not all_competitions:
            logger.debug("没有正在关注的比赛，跳过检查。")
            return

        for competition in all_competitions:
            log_context = {'competition_message_id': competition.message_id, 'channel_id': competition.channel_id}
            try:
                channel = self.bot.get_channel(competition.channel_id) or await self.bot.fetch_channel(competition.channel_id)
                message = await channel.fetch_message(competition.message_id)
                await self._process_competition_update(message, competition)
            except discord.NotFound:
                logger.warning("比赛消息未找到，可能已被删除。", extra=log_context)
            except discord.Forbidden:
                logger.error("访问比赛消息时权限不足。", extra=log_context)
            except Exception as e:
                logger.error("处理比赛时发生未知错误。", extra=log_context, exc_info=True)

    async def _process_competition_update(self, message: discord.Message, followed_competition: Competition):
        """处理单个比赛的更新检查和通知逻辑。"""
        if not message.embeds:
            return

        competition_embed = message.embeds[0]
        competition_name = message.channel.name

        new_submission_ids = parsing_service.extract_submission_ids(competition_embed)
        if not new_submission_ids:
            return

        old_submission_ids = followed_competition.last_submission_ids
        newly_added_ids = parsing_service.find_new_submissions(old_submission_ids, new_submission_ids)

        if not newly_added_ids:
            return
        
        log_context = {
            'competition_name': competition_name,
            'message_id': message.id,
            'new_submission_count': len(newly_added_ids),
            'new_submission_ids': newly_added_ids
        }
        logger.info("发现比赛有新作品提交", extra=log_context)

        subscribers = await self.follow_service.get_subscribers_for_competition(message.id)
        if not subscribers:
            logger.info("此比赛没有订阅者，跳过通知。", extra={'message_id': message.id})
        else:
            logger.info(f"正在通知 {len(subscribers)} 位比赛订阅者。", extra={'message_id': message.id, 'subscriber_count': len(subscribers)})
            for new_id in newly_added_ids:
                for user_id in subscribers:
                    await self.notification_service.send_new_submission_notification(
                        user_id=user_id,
                        new_submission_id=new_id,
                        competition_message=message,
                        competition_name=competition_name
                    )
        
        await self.follow_service.update_submission_state(message.id, new_submission_ids)
        logger.info("成功更新比赛的提交状态。", extra={'message_id': message.id})

    @check_competitions.before_loop
    async def before_check_competitions(self):
        """在任务循环开始前，等待机器人准备好。"""
        await self.bot.wait_until_ready()
        logger.info("比赛更新检查循环已准备就绪。")


async def setup(bot: commands.Bot):
    await bot.add_cog(CompetitionTracker(bot))

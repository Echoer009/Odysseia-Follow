# src/modules/competition_follow/services/follow_service.py

import discord
from typing import Optional
from src.core.database import Database
from src.modules.competition_follow.models import Competition

class FollowService:
    """
    负责管理比赛关注、用户订阅和作品状态的数据库交互。
    """

    def __init__(self, db: Database):
        self.db = db

    async def follow_competition(self, user: discord.User, channel_id: int, message_id: int, guild_id: int, initial_ids: list[str]) -> bool:
        """
        让一个用户关注一个特定的比赛。
        这会首先确保比赛存在于数据库中，然后添加用户订阅。

        Returns:
            bool: 如果是新的关注，返回True；如果已关注，返回False。
        """
        # 核心逻辑：先确保比赛记录存在（如果不存在则创建），然后再添加订阅者。
        await self.db.ensure_competition_exists(message_id, channel_id, guild_id, initial_ids)
        return await self.db.add_competition_subscriber(user.id, message_id)

    async def unfollow_competition(self, user: discord.User, message_id: int) -> bool:
        """
        让一个用户取消关注一个比赛。

        Returns:
            bool: 如果成功取消，返回True；如果本未关注，返回False。
        """
        return await self.db.remove_competition_subscriber(user.id, message_id)

    async def get_followed_competition(self, message_id: int) -> Optional[Competition]:
        """
        根据消息ID获取被关注的比赛信息。

        Returns:
            Optional[Competition]: 如果比赛被关注，返回比赛的数据模型对象；否则返回None。
        """
        competition_dict = await self.db.get_competition_by_id(message_id)
        if competition_dict:
            return Competition(**competition_dict)
        return None

    async def get_subscribers_for_competition(self, message_id: int) -> list[int]:
        """
        获取关注了某个比赛的所有用户的ID列表。
        """
        return await self.db.get_subscribers_for_competition(message_id)

    async def update_submission_state(self, message_id: int, new_ids: list[str]):
        """
        更新一个比赛的最新作品ID列表。
        """
        await self.db.update_competition_submissions(message_id, new_ids)

    async def get_all_followed_competitions(self) -> list[Competition]:
        """获取所有被关注的比赛列表。"""
        competitions_data = await self.db.get_all_followed_competitions()
        return [Competition(**data) for data in competitions_data]

# 注意：这个服务需要在Cog中用 bot.db 实例来初始化。
# 例如: self.follow_service = FollowService(bot.db)
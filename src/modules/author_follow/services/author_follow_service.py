from src.core.database import Database
from enum import Enum
from datetime import datetime

class FollowResult(Enum):
    SUCCESS = 1
    ALREADY_FOLLOWED = 2
    CANNOT_FOLLOW_SELF = 3

class UnfollowResult(Enum):
    SUCCESS = 1
    NOT_FOLLOWED = 2

# 2. 修改类名
class AuthorFollowService:
    def __init__(self, db: Database):
        self.db = db

    async def process_new_thread(self, thread_id: int, author_id: int, author_name: str, created_at: datetime):
        """
        处理一个新帖子的完整业务逻辑：
        1. 确保作者存在
        2. 记录新帖子
        """
        await self.db.ensure_author_exists(author_id, author_name)
        await self.db.add_post(thread_id, author_id, created_at)

    async def follow_author(self, user_id: int, author_id: int, author_name: str) -> FollowResult:
        if user_id == author_id:
            return FollowResult.CANNOT_FOLLOW_SELF
        success = await self.db.add_follower(user_id, author_id, author_name)
        return FollowResult.SUCCESS if success else FollowResult.ALREADY_FOLLOWED

    async def unfollow_author(self, user_id: int, author_id: int) -> UnfollowResult:
        success = await self.db.remove_follower(user_id, author_id)
        return UnfollowResult.SUCCESS if success else UnfollowResult.NOT_FOLLOWED

    async def get_user_follows(self, user_id: int) -> list[int]:
        """业务逻辑：获取用户的关注列表"""
        return await self.db.get_followed_authors(user_id)

    async def get_user_follows_details(self, user_id: int) -> list[dict]:
        """业务逻辑：获取用户的关注列表详情（ID和名字）"""
        return await self.db.get_followed_authors_with_names(user_id)

    async def get_author_followers(self, author_id: int) -> list[int]:
        """业务逻辑：获取作者的关注者列表"""
        return await self.db.get_followers_for_author(author_id)

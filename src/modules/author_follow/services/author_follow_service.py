from src.core.database import Database # 1. 更新导入路径
from enum import Enum

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

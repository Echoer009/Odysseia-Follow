from src.database import Database # <-- 修改这里，使用绝对路径
from enum import Enum

# 使用枚举(Enum)来定义清晰的操作结果，比返回True/False更强大
class FollowResult(Enum):
    SUCCESS = 1           # 关注成功
    ALREADY_FOLLOWED = 2  # 已经关注过
    CANNOT_FOLLOW_SELF = 3# 不能关注自己

class UnfollowResult(Enum):
    SUCCESS = 1           # 取关成功
    NOT_FOLLOWED = 2      # 之前未关注

class FollowService:
    def __init__(self, db: Database):
        self.db = db

    async def follow_author(self, user_id: int, author_id: int, author_name: str) -> FollowResult:
        """核心业务逻辑：处理关注作者"""
        if user_id == author_id:
            return FollowResult.CANNOT_FOLLOW_SELF

        success = await self.db.add_follower(user_id, author_id, author_name)
        
        if success:
            return FollowResult.SUCCESS
        else:
            return FollowResult.ALREADY_FOLLOWED

    async def unfollow_author(self, user_id: int, author_id: int) -> UnfollowResult:
        """核心业务逻辑：处理取关作者"""
        success = await self.db.remove_follower(user_id, author_id)

        if success:
            return UnfollowResult.SUCCESS
        else:
            return UnfollowResult.NOT_FOLLOWED

    async def get_user_follows(self, user_id: int) -> list[int]:
        """核心业务逻辑：获取用户的关注列表"""
        return await self.db.get_followed_authors(user_id)

    async def get_user_follows_details(self, user_id: int) -> list[dict]:
        """核心业务逻辑：获取用户的关注列表详情（ID和名字）"""
        return await self.db.get_followed_authors_with_names(user_id)

    async def get_author_followers(self, author_id: int) -> list[int]:
        """核心业务逻辑：获取作者的关注者列表"""
        return await self.db.get_followers_for_author(author_id)
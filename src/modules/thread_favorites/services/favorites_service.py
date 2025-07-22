import discord
import os
import asyncio
from src.core.database import Database
from typing import List, Tuple
from datetime import datetime, timezone

class FavoritesService:
    def __init__(self, db: Database):
        self.db = db
        # 为批量离开操作添加一个锁，以防止并发调用导致速率限制
        self.leave_lock = asyncio.Lock()

    async def get_user_favorites(self, user_id: int, page: int, page_size: int) -> list[dict]:
        """获取用户收藏夹的分页列表。"""
        offset = (page - 1) * page_size
        return await self.db.get_user_favorites_paginated(user_id, page_size, offset)

    async def get_favorites_count(self, user_id: int) -> int:
        """获取用户的收藏总数。"""
        return await self.db.get_user_favorites_count(user_id)

    async def add_favorite(self, user_id: int, thread: discord.Thread) -> bool:
        """通过右键菜单等方式，添加单个收藏。"""
        now = datetime.now(timezone.utc)
        return await self.db.add_favorite(user_id, thread.id, thread.name, thread.guild.id, now)

    async def get_active_threads_for_user(self, user: discord.User, guild: discord.Guild) -> List[dict]:
        """
        从数据库快速获取用户所在的活跃帖子的ID和名称，不执行API调用。
        """
        return await self.db.get_user_active_threads(user.id, guild.id)

    async def get_unfavorited_threads_for_user(self, user: discord.User, guild: discord.Guild) -> List[dict]:
        """
        从数据库快速获取用户已加入但尚未收藏的帖子列表（ID和名称），不执行API调用。
        """
        return await self.db.get_unfavorited_active_threads(user.id, guild.id)

    async def batch_favorite_threads(self, user: discord.User, threads_to_favorite: List[discord.Thread]) -> int:
        """
        批量收藏帖子，不处理离开逻辑。
        """
        if not threads_to_favorite:
            return 0

        # The previous implementation already correctly filters existing favorites,
        # but we do it here again for safety, as this is a pure "favorite" action.
        existing_favorites = await self.db.get_all_user_favorite_thread_ids(user.id)
        existing_favorites_set = set(existing_favorites)
        
        now = datetime.now(timezone.utc)
        threads_to_favorite_data = [
            (user.id, t.id, t.name, t.guild.id, now)
            for t in threads_to_favorite if t.id not in existing_favorites_set
        ]
        
        if threads_to_favorite_data:
            await self.db.add_favorites_in_batch(threads_to_favorite_data)
        
        return len(threads_to_favorite_data)

    async def remove_favorite(self, user_id: int, thread_id: int) -> bool:
        """移除单个收藏。"""
        return await self.db.remove_favorite(user_id, thread_id)

    async def batch_unfavorite_threads(self, user_id: int, thread_ids: List[int]) -> int:
        """
        批量取消收藏帖子。
        """
        if not thread_ids:
            return 0
        
        # The database method should return the number of rows deleted.
        removed_count = await self.db.remove_favorites_in_batch(user_id, thread_ids)
        return removed_count

    async def batch_leave_threads(self, user: discord.User, threads_to_leave: List[discord.Thread]) -> Tuple[int, int]:
        """
        批量将用户从指定的帖子中移出。此方法使用最终的、最安全的串行处理模式，以100%避免速率限制。
        返回一个元组 (succeeded_count, failed_count)。
        """
        async with self.leave_lock:
            if not threads_to_leave:
                return 0, 0

            succeeded_count = 0
            failed_count = 0
            # 从环境变量获取每个请求之间的延迟，默认为1秒，这是一个非常安全的值
            delay_per_request = float(os.getenv('LEAVE_DELAY_SECONDS', '1.0'))

            for thread in threads_to_leave:
                try:
                    await thread.remove_user(user)
                    # 成功退出后，立即从缓存中删除
                    await self.db.remove_active_thread_member(user.id, thread.id)
                    succeeded_count += 1
                except discord.HTTPException:
                    failed_count += 1
                
                # 在每次API调用后都进行短暂的暂停，以避免速率限制
                await asyncio.sleep(delay_per_request)
            
            return succeeded_count, failed_count

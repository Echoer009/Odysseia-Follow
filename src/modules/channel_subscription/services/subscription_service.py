import discord
from src.core.database import Database
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class SubscriptionService:
    def __init__(self, db: Database):
        self.db = db

    async def get_subscription(self, user_id: int, channel_id: int) -> Optional[dict]:
        """获取用户的关键词订阅设置。"""
        return await self.db.get_keyword_subscription(user_id, channel_id)

    async def update_subscription(self, user_id: int, channel_id: int, followed_keywords: list[str], blocked_keywords: list[str]):
        """仅更新用户的关键词订阅，不改变其关注状态。"""
        # 清理和去重
        followed = sorted(list(set([kw.lower() for kw in followed_keywords if kw])))
        blocked = sorted(list(set([kw.lower() for kw in blocked_keywords if kw])))

        # 获取当前的订阅状态，如果不存在则默认为未订阅
        current_sub = await self.get_subscription(user_id, channel_id)
        is_subscribed = current_sub.get('is_subscribed', False) if current_sub else False

        await self.db.upsert_keyword_subscription(user_id, channel_id, is_subscribed, followed, blocked)
        logger.info(f"用户 {user_id} 在频道 {channel_id} 的关键词已更新。")

    async def follow_channel(self, user_id: int, channel_id: int):
        """用户关注一个频道。这将保留现有的关键词设置。"""
        current_sub = await self.get_subscription(user_id, channel_id)
        followed_kws = current_sub.get('followed_keywords', []) if current_sub else []
        blocked_kws = current_sub.get('blocked_keywords', []) if current_sub else []
        
        await self.db.upsert_keyword_subscription(user_id, channel_id, True, followed_kws, blocked_kws)
        logger.info(f"用户 {user_id} 已关注频道 {channel_id}。")

    async def unfollow_channel(self, user_id: int, channel_id: int):
        """用户取消关注一个频道。这将保留现有的关键词设置。"""
        current_sub = await self.get_subscription(user_id, channel_id)
        # If there's no record at all, there's nothing to do.
        if not current_sub:
            logger.warning(f"用户 {user_id} 尝试取消关注一个从未订阅过的频道 {channel_id}。")
            return

        followed_kws = current_sub.get('followed_keywords', [])
        blocked_kws = current_sub.get('blocked_keywords', [])

        await self.db.upsert_keyword_subscription(user_id, channel_id, False, followed_kws, blocked_kws)
        logger.info(f"用户 {user_id} 已取消关注频道 {channel_id}。")

    async def process_new_thread(self, thread: discord.Thread) -> list[int]:
        """
        处理一个新创建的帖子，根据用户的频道订阅设置返回需要通知的用户ID列表。
        通知逻辑优先级: 屏蔽词 > 关键词 > 全量订阅
        """
        channel_id = thread.parent_id
        thread_title = thread.name.lower()
        tag_names = {tag.name.lower() for tag in thread.applied_tags}
        search_content = thread_title + " " + " ".join(tag_names)

        subscriptions = await self.db.get_all_subscriptions_for_channel(channel_id)
        if not subscriptions:
            return []

        users_to_notify = []
        for sub in subscriptions:
            user_id = sub['user_id']
            
            if user_id == thread.owner_id:
                continue

            followed_kws = sub.get('followed_keywords', [])
            blocked_kws = sub.get('blocked_keywords', [])

            # 1. 最高优先级：检查屏蔽词
            if any(kw in search_content for kw in blocked_kws):
                continue

            # 2. 次高优先级：检查关注关键词 (如果设置了)
            if followed_kws:
                if any(kw in search_content for kw in followed_kws):
                    users_to_notify.append(user_id)
                continue # 如果设置了关注词但没匹配上，则不进入全量订阅逻辑

            # 3. 默认行为：全量订阅 (如果未设置关注词)
            else:
                users_to_notify.append(user_id)
                
        logger.info(f"帖子 '{thread.name}' (ID: {thread.id}) 在频道 {channel_id} 中触发了对 {len(users_to_notify)} 位用户的通知。")
        return list(set(users_to_notify)) # 使用 set 去重以防万一

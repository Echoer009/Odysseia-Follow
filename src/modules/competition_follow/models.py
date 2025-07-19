# src/modules/competition_follow/models.py

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Competition:
    """
    代表一个被关注的比赛。
    对应数据库中的 'competitions' 表。
    """
    message_id: int
    channel_id: int
    guild_id: int
    last_submission_ids: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

@dataclass
class Subscription:
    """
    代表一个用户对比赛的关注。
    对应数据库中的 'competition_subscriptions' 表。
    """
    user_id: int
    competition_message_id: int
    id: Optional[int] = None
    subscribed_at: Optional[datetime] = None
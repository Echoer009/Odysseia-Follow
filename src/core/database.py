import aiosqlite
import os
from datetime import datetime, timezone, timedelta
import asyncio
import pathlib
import logging
import json
from typing import Optional

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        # SQLite 不需要连接池，只需要一个连接对象
        self.conn = None
        self.db_name = os.getenv('DB_NAME')
        self.backup_folder = os.getenv('BACKUP_FOLDER', 'backups')
        # 新增：从环境变量读取备份保留天数
        try:
            self.backup_retention_days = int(os.getenv('BACKUP_RETENTION_DAYS', '7'))
        except (ValueError, TypeError):
            self.backup_retention_days = 7


    async def connect(self):
        """连接到SQLite数据库文件"""
        self.conn = await aiosqlite.connect(self.db_name)
        # 2. 设置 row_factory，让查询结果可以像字典一样通过列名访问，这对于保持其他代码不变至关重要
        self.conn.row_factory = aiosqlite.Row
        # 3. 启用外键约束，SQLite默认是关闭的
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.commit()
        # 4. 在这里运行数据库迁移
        await self._run_migrations()
        logger.info("数据库连接成功并完成初始化", extra={'db_name': self.db_name})

    async def cleanup_old_backups(self):
        """清理超过指定保留天数的旧备份文件。"""
        if self.backup_retention_days <= 0:
            logger.info("备份清理功能已禁用", extra={'retention_days': self.backup_retention_days})
            return

        backup_dir = pathlib.Path(self.backup_folder)
        if not backup_dir.is_dir():
            return

        logger.info("开始清理旧备份", extra={'retention_days': self.backup_retention_days})
        cutoff_date = datetime.now() - timedelta(days=self.backup_retention_days)
        cleaned_count = 0
        
        for file_path in backup_dir.glob('*_backup_*.db'):
            try:
                timestamp_str = file_path.stem.split('_backup_')[-1]
                file_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if file_date < cutoff_date:
                    file_path.unlink()
                    logger.info("已删除旧备份文件", extra={'file_name': file_path.name})
                    cleaned_count += 1
            except (ValueError, IndexError) as e:
                logger.warning("无法解析或处理备份文件", extra={'file_name': file_path.name}, exc_info=True)
        
        log_context = {'cleaned_count': cleaned_count}
        if cleaned_count > 0:
            logger.info("备份清理完成", extra=log_context)
        else:
            logger.info("没有需要清理的旧备份文件", extra=log_context)


    async def backup_database(self):
        """使用SQLite的在线备份API创建一个安全的数据库备份文件。"""
        # 0. 在备份前，先执行清理任务
        await self.cleanup_old_backups()

        # 1. 确保备份目录存在
        backup_dir = pathlib.Path(self.backup_folder)
        backup_dir.mkdir(exist_ok=True)

        # 2. 创建带时间戳的备份文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_stem = pathlib.Path(self.db_name).stem # 获取不带扩展名的文件名
        backup_filename = f"{db_stem}_backup_{timestamp}.db"
        backup_path = backup_dir / backup_filename

        # 3. 使用 aiosqlite 的 backup 功能，这是最安全的方式
        log_context = {'backup_path': str(backup_path)}
        logger.info("正在开始备份数据库", extra=log_context)
        try:
            async with aiosqlite.connect(backup_path) as backup_conn:
                await self.conn.backup(backup_conn)
            logger.info("数据库备份成功", extra=log_context)
        except Exception as e:
            logger.error("数据库备份失败", extra=log_context, exc_info=True)

    async def start_backup_loop(self, interval_seconds: int):
        """启动一个循环，按指定间隔备份数据库。"""
        logger.info("数据库自动备份循环已启动。")
        while True:
            # 等待指定的时间间隔
            await asyncio.sleep(interval_seconds)
            # 执行备份
            await self.backup_database()


    async def _execute(self, query, args=None, fetch=None):
        """通用的执行函数"""
        # 5. SQLite的参数占位符是 '?' 而不是 '%s'
        async with self.conn.cursor() as cursor:
            await cursor.execute(query, args or ())
            if fetch == 'one':
                return await cursor.fetchone()
            if fetch == 'all':
                return await cursor.fetchall()
            # 对于 INSERT, UPDATE, DELETE，我们需要手动提交
            await self.conn.commit()
            return cursor.rowcount

    async def ensure_author_exists(self, author_id: int, author_name: str):
        """确保作者存在于数据库中，如果不存在则创建，如果存在则更新其名称。"""
        # 使用 SQLite 的 "UPSERT" 语法
        # ON CONFLICT(author_id) DO UPDATE SET author_name = ...
        # 这会确保作者名称总是最新的，解决了旧名称不会被更新的问题。
        sql = """
            INSERT INTO authors (author_id, author_name) VALUES (?, ?)
            ON CONFLICT(author_id) DO UPDATE SET author_name = excluded.author_name;
        """
        await self._execute(sql, (author_id, author_name))

    async def add_follower(self, user_id: int, author_id: int, author_name: str) -> bool:
        """
        添加一个关注关系。
        返回 True 表示成功关注，False 表示已经关注过。
        """
        await self.ensure_author_exists(author_id, author_name)
        sql = "INSERT OR IGNORE INTO followers (user_id, author_id) VALUES (?, ?)"
        rows_affected = await self._execute(sql, (user_id, author_id))
        return rows_affected > 0

    async def remove_follower(self, user_id: int, author_id: int) -> bool:
        """
        移除一个关注关系。
        返回 True 表示成功取关，False 表示之前未关注。
        """
        sql = "DELETE FROM followers WHERE user_id = ? AND author_id = ?"
        rows_affected = await self._execute(sql, (user_id, author_id))
        return rows_affected > 0

    async def get_followers_for_author(self, author_id: int) -> list[int]:
        """获取一个作者的所有关注者的ID列表"""
        sql = "SELECT user_id FROM followers WHERE author_id = ?"
        results = await self._execute(sql, (author_id,), fetch='all')
        return [row['user_id'] for row in results] if results else []

    async def get_followed_authors(self, user_id: int) -> list[int]:
        """获取一个用户关注的所有作者的ID列表"""
        sql = "SELECT author_id FROM followers WHERE user_id = ?"
        results = await self._execute(sql, (user_id,), fetch='all')
        return [row['author_id'] for row in results] if results else []

    async def get_followed_authors_with_names(self, user_id: int) -> list[dict]:
        """获取用户关注的所有作者的ID和名字"""
        sql = """
            SELECT f.author_id, a.author_name
            FROM followers f
            JOIN authors a ON f.author_id = a.author_id
            WHERE f.user_id = ?
        """
        results = await self._execute(sql, (user_id,), fetch='all')
        # 将 Row 对象转换为普通字典列表
        return [dict(row) for row in results] if results else []

    # --- Competition Follow Methods ---

    async def ensure_competition_exists(self, message_id: int, channel_id: int, guild_id: int, initial_ids: list[str]):
        """确保比赛记录存在。如果不存在，则创建它。"""
        ids_json = json.dumps(initial_ids)
        # 使用 INSERT OR IGNORE 避免在记录已存在时报错
        sql = """
            INSERT OR IGNORE INTO competitions (message_id, channel_id, guild_id, last_submission_ids)
            VALUES (?, ?, ?, ?)
        """
        await self._execute(sql, (message_id, channel_id, guild_id, ids_json))

    async def add_competition_subscriber(self, user_id: int, message_id: int) -> bool:
        """为比赛添加订阅者。返回True表示新订阅，False表示已订阅。"""
        sql = "INSERT OR IGNORE INTO competition_subscriptions (user_id, competition_message_id) VALUES (?, ?)"
        rows_affected = await self._execute(sql, (user_id, message_id))
        return rows_affected > 0

    async def remove_competition_subscriber(self, user_id: int, message_id: int) -> bool:
        """移除比赛的订阅者。返回True表示成功移除，False表示未订阅。"""
        sql = "DELETE FROM competition_subscriptions WHERE user_id = ? AND competition_message_id = ?"
        rows_affected = await self._execute(sql, (user_id, message_id))
        return rows_affected > 0

    async def get_competition_by_id(self, message_id: int) -> Optional[dict]:
        """通过message_id获取比赛信息。"""
        sql = "SELECT * FROM competitions WHERE message_id = ?"
        result = await self._execute(sql, (message_id,), fetch='one')
        if result:
            competition_dict = dict(result)
            competition_dict['last_submission_ids'] = json.loads(competition_dict['last_submission_ids'])
            return competition_dict
        return None

    async def get_subscribers_for_competition(self, message_id: int) -> list[int]:
        """获取一个比赛的所有订阅者ID。"""
        sql = "SELECT user_id FROM competition_subscriptions WHERE competition_message_id = ?"
        results = await self._execute(sql, (message_id,), fetch='all')
        return [row['user_id'] for row in results] if results else []

    async def update_competition_submissions(self, message_id: int, new_ids: list[str]):
        """更新比赛的最新作品ID列表。"""
        ids_json = json.dumps(new_ids)
        sql = "UPDATE competitions SET last_submission_ids = ? WHERE message_id = ?"
        await self._execute(sql, (ids_json, message_id))

    async def get_all_followed_competitions(self) -> list[dict]:
        """获取所有被关注的比赛信息。"""
        sql = "SELECT * FROM competitions"
        results = await self._execute(sql, fetch='all')
        if not results:
            return []
        
        competitions = []
        for row in results:
            competition_dict = dict(row)
            competition_dict['last_submission_ids'] = json.loads(competition_dict['last_submission_ids'])
            competitions.append(competition_dict)
        return competitions

    # 4. 为帖子追踪添加新的数据库方法
    async def add_post(self, post_id: int, author_id: int, created_at: datetime):
        """记录作者发布的新帖子"""
        # 将时区感知的datetime转换为UTC天真时间以便存入SQLite
        utc_created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
        sql = "INSERT OR IGNORE INTO author_posts (post_id, author_id, created_at) VALUES (?, ?, ?)"
        await self._execute(sql, (post_id, author_id, utc_created_at))

    async def get_and_update_last_view(self, user_id: int) -> datetime:
        """获取用户上次查看时间，并更新为当前时间。返回上次查看的时间。"""
        sql_get = "SELECT last_viewed_at FROM user_last_view WHERE user_id = ?"
        result = await self._execute(sql_get, (user_id,), fetch='one')
        
        last_view_time = datetime(1970, 1, 1) # 如果是第一次查看，返回一个很早的时间
        if result and result['last_viewed_at']:
            try:
                # aiosqlite可能返回字符串，需要转换回datetime对象
                last_view_time = datetime.fromisoformat(result['last_viewed_at'])
            except (TypeError, ValueError):
                # 兼容旧格式
                last_view_time = datetime.strptime(result['last_viewed_at'], '%Y-%m-%d %H:%M:%S')

        # 将当前时间（UTC）更新到数据库
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        sql_update = "INSERT OR REPLACE INTO user_last_view (user_id, last_viewed_at) VALUES (?, ?)"
        await self._execute(sql_update, (user_id, now_utc))
        
        return last_view_time

    async def get_new_post_counts(self, author_ids: list[int], since_timestamp: datetime) -> list[dict]:
        """获取指定作者们在某个时间点之后的新帖子数量"""
        if not author_ids:
            return []
        
        placeholders = ','.join('?' for _ in author_ids)
        sql = f"""
            SELECT author_id, COUNT(post_id) as new_posts_count
            FROM author_posts
            WHERE author_id IN ({placeholders}) AND created_at > ?
            GROUP BY author_id
        """
        
        params = tuple(author_ids) + (since_timestamp,)
        results = await self._execute(sql, params, fetch='all')
        return [dict(row) for row in results] if results else []

    # --- 关键词关注方法 ---

    async def get_keyword_subscription(self, user_id: int, channel_id: int) -> Optional[dict]:
        """获取用户在特定频道下的关键词订阅设置。"""
        sql = "SELECT * FROM keyword_subscriptions WHERE user_id = ? AND channel_id = ?"
        result = await self._execute(sql, (user_id, channel_id), fetch='one')
        if not result:
            return None
        
        subscription = dict(result)
        # 将数据库中的 0/1 转换为布尔值
        subscription['is_subscribed'] = bool(subscription.get('is_subscribed', 0))
        subscription['followed_keywords'] = json.loads(subscription.get('followed_keywords') or '[]')
        subscription['blocked_keywords'] = json.loads(subscription.get('blocked_keywords') or '[]')
        return subscription

    async def upsert_keyword_subscription(self, user_id: int, channel_id: int, is_subscribed: bool, followed_keywords: list[str], blocked_keywords: list[str]):
        """创建或更新用户的关键词订阅设置，包括订阅状态。"""
        followed_json = json.dumps(followed_keywords)
        blocked_json = json.dumps(blocked_keywords)
        sql = """
            INSERT INTO keyword_subscriptions (user_id, channel_id, is_subscribed, followed_keywords, blocked_keywords)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, channel_id) DO UPDATE SET
                is_subscribed = excluded.is_subscribed,
                followed_keywords = excluded.followed_keywords,
                blocked_keywords = excluded.blocked_keywords;
        """
        await self._execute(sql, (user_id, channel_id, is_subscribed, followed_json, blocked_json))

    async def get_all_subscriptions_for_channel(self, channel_id: int) -> list[dict]:
        """获取特定频道下的所有有效订阅 (is_subscribed = 1)。"""
        sql = "SELECT * FROM keyword_subscriptions WHERE channel_id = ? AND is_subscribed = 1"
        results = await self._execute(sql, (channel_id,), fetch='all')
        if not results:
            return []

        subscriptions = []
        for row in results:
            subscription = dict(row)
            subscription['is_subscribed'] = True # We already filtered for this
            subscription['followed_keywords'] = json.loads(subscription.get('followed_keywords') or '[]')
            subscription['blocked_keywords'] = json.loads(subscription.get('blocked_keywords') or '[]')
            subscriptions.append(subscription)
        return subscriptions

    async def get_subscribed_channels_for_user(self, user_id: int) -> list[dict]:
        """获取用户已订阅的所有频道信息。"""
        sql = "SELECT * FROM keyword_subscriptions WHERE user_id = ? AND is_subscribed = 1"
        results = await self._execute(sql, (user_id,), fetch='all')
        if not results:
            return []
        
        subscriptions = []
        for row in results:
            subscription = dict(row)
            subscription['is_subscribed'] = True
            subscription['followed_keywords'] = json.loads(subscription.get('followed_keywords') or '[]')
            subscription['blocked_keywords'] = json.loads(subscription.get('blocked_keywords') or '[]')
            subscriptions.append(subscription)
        return subscriptions

    # --- Thread Favorites Methods ---

    async def add_favorite(self, user_id: int, thread_id: int, thread_name: str, guild_id: int, added_at: datetime) -> bool:
        """将一个帖子添加到用户的收藏夹。返回True表示新收藏，False表示已存在。"""
        sql = """
            INSERT OR IGNORE INTO thread_favorites (user_id, thread_id, thread_name, guild_id, added_at)
            VALUES (?, ?, ?, ?, ?)
        """
        rows_affected = await self._execute(sql, (user_id, thread_id, thread_name, guild_id, added_at))
        return rows_affected > 0

    async def remove_favorite(self, user_id: int, thread_id: int) -> bool:
        """从用户的收藏夹中移除一个帖子。返回True表示成功移除，False表示不存在。"""
        sql = "DELETE FROM thread_favorites WHERE user_id = ? AND thread_id = ?"
        rows_affected = await self._execute(sql, (user_id, thread_id))
        return rows_affected > 0

    async def get_user_favorites_paginated(self, user_id: int, limit: int, offset: int) -> list[dict]:
        """分页获取用户的收藏帖子列表。"""
        sql = """
            SELECT thread_id, thread_name, guild_id, added_at
            FROM thread_favorites
            WHERE user_id = ?
            ORDER BY added_at DESC
            LIMIT ? OFFSET ?
        """
        results = await self._execute(sql, (user_id, limit, offset), fetch='all')
        if not results:
            return []
        
        # 将 added_at 字符串转换为 datetime 对象
        processed_results = []
        for row in results:
            row_dict = dict(row)
            if row_dict.get('added_at'):
                try:
                    row_dict['added_at'] = datetime.fromisoformat(row_dict['added_at'])
                except (TypeError, ValueError):
                    # 添加一个备用解析，以防万一数据库中存在旧格式
                    try:
                        row_dict['added_at'] = datetime.strptime(row_dict['added_at'], '%Y-%m-%d %H:%M:%S.%f')
                    except ValueError:
                         row_dict['added_at'] = datetime.strptime(row_dict['added_at'], '%Y-%m-%d %H:%M:%S')

            processed_results.append(row_dict)
            
        return processed_results

    async def get_user_favorites_count(self, user_id: int) -> int:
        """获取用户收藏的帖子总数。"""
        sql = "SELECT COUNT(id) FROM thread_favorites WHERE user_id = ?"
        result = await self._execute(sql, (user_id,), fetch='one')
        return result[0] if result else 0
    
    async def get_all_user_favorite_thread_ids(self, user_id: int) -> list[int]:
        """获取用户收藏的所有帖子 ID。"""
        sql = "SELECT thread_id FROM thread_favorites WHERE user_id = ?"
        results = await self._execute(sql, (user_id,), fetch='all')
        return [row['thread_id'] for row in results] if results else []

    async def add_favorites_in_batch(self, favorites_data: list[tuple]):
        """
        批量添加收藏。
        favorites_data 是一个元组列表，每个元组包含 (user_id, thread_id, thread_name, guild_id, added_at)
        """
        sql = """
            INSERT OR IGNORE INTO thread_favorites (user_id, thread_id, thread_name, guild_id, added_at)
            VALUES (?, ?, ?, ?, ?)
        """
        # executemany 是批量操作的最佳方式
        async with self.conn.cursor() as cursor:
            await cursor.executemany(sql, favorites_data)
            await self.conn.commit()

    async def remove_favorites_in_batch(self, user_id: int, thread_ids: list[int]) -> int:
        """
        批量移除收藏。
        返回成功移除的收藏数量。
        """
        if not thread_ids:
            return 0
        
        placeholders = ','.join('?' for _ in thread_ids)
        sql = f"DELETE FROM thread_favorites WHERE user_id = ? AND thread_id IN ({placeholders})"
        
        params = (user_id,) + tuple(thread_ids)
        rows_affected = await self._execute(sql, params)
        return rows_affected

    # --- Active Thread Scanner Methods ---

    async def clear_active_thread_members(self, guild_id: int):
        """清除指定服务器的所有活跃帖子-成员关系记录。"""
        sql = "DELETE FROM active_thread_members WHERE guild_id = ?"
        await self._execute(sql, (guild_id,))

    async def update_active_thread_members(self, thread_id: int, member_ids: list[int], guild_id: int):
        """
        使用 UPSERT 语法批量更新或插入一个帖子的成员列表。
        这可以确保数据是最新的，并且避免了重复记录。
        """
        now = datetime.now(timezone.utc)
        data = [(thread_id, user_id, guild_id, now) for user_id in member_ids]
        
        sql = """
            INSERT INTO active_thread_members (thread_id, user_id, guild_id, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id, user_id) DO UPDATE SET
                last_seen = excluded.last_seen;
        """
        async with self.conn.cursor() as cursor:
            await cursor.executemany(sql, data)
            await self.conn.commit()

    async def get_user_active_threads(self, user_id: int, guild_id: int) -> list[dict]:
        """
        获取用户所在的所有活跃帖子的ID和名称。
        使用 LEFT JOIN 从 thread_favorites 获取名称，如果帖子未被收藏，则名称为 NULL。
        """
        sql = """
            SELECT
                atm.thread_id,
                tf.thread_name
            FROM active_thread_members atm
            LEFT JOIN thread_favorites tf ON atm.thread_id = tf.thread_id AND atm.user_id = tf.user_id
            WHERE atm.user_id = ? AND atm.guild_id = ?
        """
        results = await self._execute(sql, (user_id, guild_id), fetch='all')
        return [dict(row) for row in results] if results else []

    async def get_unfavorited_active_threads(self, user_id: int, guild_id: int) -> list[dict]:
        """
        获取用户已加入但尚未收藏的活跃帖子列表（ID和名称）。
        这通过查找在 active_thread_members 中但不在 thread_favorites 中的记录来实现。
        注意：由于我们没有在 active_thread_members 中存储名字，所以 thread_name 将为 NULL。
        我们需要在调用方处理这种情况。
        """
        sql = """
            SELECT atm.thread_id, NULL as thread_name
            FROM active_thread_members atm
            WHERE atm.user_id = ?
              AND atm.guild_id = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM thread_favorites tf
                  WHERE tf.user_id = atm.user_id AND tf.thread_id = atm.thread_id
              )
        """
        results = await self._execute(sql, (user_id, guild_id), fetch='all')
        return [dict(row) for row in results] if results else []


    async def remove_active_thread_member(self, user_id: int, thread_id: int):
        """从活跃帖子成员缓存中移除一个特定的用户-帖子关系。"""
        sql = "DELETE FROM active_thread_members WHERE user_id = ? AND thread_id = ?"
        await self._execute(sql, (user_id, thread_id))

    async def _run_migrations(self):
        """
        执行基于版本的数据库迁移。
        此方法会检查 `src/migrations/versions` 目录下的 .sql 文件，
        并与数据库中存储的 `user_version` 进行比较，然后按顺序应用所有新的迁移。
        """
        logger.info("正在检查并运行数据库迁移...")
        
        # 1. 获取迁移文件目录
        # 使用 __file__ 来定位，确保路径的健壮性
        migrations_path = pathlib.Path(__file__).parent.parent / "migrations" / "versions"
        if not migrations_path.is_dir():
            logger.warning(f"迁移目录不存在，跳过迁移: {migrations_path}")
            return

        # 2. 获取当前数据库版本
        async with self.conn.cursor() as cursor:
            await cursor.execute("PRAGMA user_version")
            current_version = (await cursor.fetchone())[0]
        logger.info(f"当前数据库版本: {current_version}")

        # 3. 获取所有迁移脚本并排序
        try:
            migration_files = sorted(
                migrations_path.glob("*.sql"),
                key=lambda p: int(p.stem.split('_')[0])
            )
        except (ValueError, IndexError):
            logger.error("迁移文件名格式不正确，应为 'XXX_description.sql'。")
            raise

        latest_version = current_version
        for migration_file in migration_files:
            try:
                file_version = int(migration_file.stem.split('_')[0])
                
                if file_version > current_version:
                    logger.info(f"准备应用迁移脚本: v{file_version} - {migration_file.name}")
                    with open(migration_file, 'r', encoding='utf-8') as f:
                        sql_script = f.read()
                    
                    # aiosqlite 的 executescript 是同步的，但对于 DDL 来说通常没问题
                    await self.conn.executescript(sql_script)
                    
                    # 更新数据库版本
                    await self.conn.execute(f"PRAGMA user_version = {file_version}")
                    await self.conn.commit()
                    
                    logger.info(f"成功应用迁移脚本并更新数据库版本至: {file_version}")
                    latest_version = file_version
            except Exception:
                logger.error(f"应用迁移脚本失败: {migration_file.name}", exc_info=True)
                await self.conn.rollback() # 失败时回滚
                raise # 重新抛出异常，以防止机器人以损坏的数据库状态启动

        if latest_version == current_version:
            logger.info("数据库结构已是最新，无需迁移。")
        else:
            logger.info(f"数据库迁移完成，当前版本为: {latest_version}")
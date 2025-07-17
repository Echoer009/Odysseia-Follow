import aiosqlite
import os
from datetime import datetime, timezone, timedelta
import asyncio
import pathlib
import logging

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
        # 4. 在这里创建数据表（如果它们不存在的话）
        await self.create_tables()
        logger.info(f"数据库 '{self.db_name}' 连接成功并完成初始化。")

    async def cleanup_old_backups(self):
        """清理超过指定保留天数的旧备份文件。"""
        if self.backup_retention_days <= 0:
            logger.info("备份清理功能已禁用 (保留天数 <= 0)。")
            return

        backup_dir = pathlib.Path(self.backup_folder)
        if not backup_dir.is_dir():
            return

        logger.info(f"开始清理 {self.backup_retention_days} 天前的旧备份...")
        cutoff_date = datetime.now() - timedelta(days=self.backup_retention_days)
        cleaned_count = 0
        
        for file_path in backup_dir.glob('*_backup_*.db'):
            try:
                # 从文件名解析时间戳，例如 '..._backup_20231027_153000.db'
                timestamp_str = file_path.stem.split('_backup_')[-1]
                file_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if file_date < cutoff_date:
                    file_path.unlink() # 删除文件
                    logger.info(f"已删除旧备份: {file_path.name}")
                    cleaned_count += 1
            except (ValueError, IndexError) as e:
                logger.warning(f"无法解析备份文件名或处理文件 '{file_path.name}': {e}")
        
        if cleaned_count > 0:
            logger.info(f"备份清理完成，共删除了 {cleaned_count} 个旧文件。")
        else:
            logger.info("没有需要清理的旧备份文件。")


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
        logger.info(f"正在开始备份数据库到 {backup_path}...")
        try:
            async with aiosqlite.connect(backup_path) as backup_conn:
                await self.conn.backup(backup_conn)
            logger.info(f"数据库成功备份到: {backup_path}")
        except Exception as e:
            logger.error(f"创建数据库备份时出错: {e}", exc_info=True)

    async def start_backup_loop(self, interval_seconds: int):
        """启动一个循环，按指定间隔备份数据库。"""
        logger.info("数据库自动备份循环已启动。")
        while True:
            # 等待指定的时间间隔
            await asyncio.sleep(interval_seconds)
            # 执行备份
            await self.backup_database()

    async def create_tables(self):
        """创建数据库表"""
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS authors (
                author_id INTEGER PRIMARY KEY,
                author_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS followers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                followed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, author_id),
                FOREIGN KEY(author_id) REFERENCES authors(author_id) ON DELETE CASCADE
            )
        """)
        # 2. 添加新表来记录作者发布的帖子
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS author_posts (
                post_id INTEGER PRIMARY KEY,
                author_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(author_id) REFERENCES authors(author_id) ON DELETE CASCADE
            )
        """)
        # 3. 添加新表来记录用户最后查看的时间
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_last_view (
                user_id INTEGER PRIMARY KEY,
                last_viewed_at DATETIME NOT NULL
            )
        """)
        await self.conn.commit()

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
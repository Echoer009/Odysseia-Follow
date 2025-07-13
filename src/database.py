import aiosqlite # 1. 导入新的库
import os

class Database:
    def __init__(self):
        # SQLite 不需要连接池，只需要一个连接对象
        self.conn = None
        self.db_name = os.getenv('DB_NAME')

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
        """确保作者存在于数据库中，如果不存在则创建"""
        # 'OR IGNORE' 是SQLite中等价于MySQL 'IGNORE'的语法
        sql = "INSERT OR IGNORE INTO authors (author_id, author_name) VALUES (?, ?)"
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
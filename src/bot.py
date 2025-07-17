import discord
from discord.ext import commands
import os
import asyncio
import pathlib
from dotenv import load_dotenv, find_dotenv
from src.core.database import Database
from src.modules.author_follow.services.author_follow_service import AuthorFollowService
from src.modules.user_profile_feature.services.profile_service import ProfileService
import logging
from src.core.logging_setup import setup_logging

# 使用 find_dotenv() 确保总能找到 .env 文件
load_dotenv(find_dotenv())
TOKEN = os.getenv('DISCORD_TOKEN')

# 获取一个logger实例
logger = logging.getLogger(__name__)

class MyBot(commands.Bot):
    def __init__(self):
        # 从 .env 文件加载 GUILD_ID
        GUILD_ID = os.getenv("GUILD_ID")

        # 使用下面的代码来正确处理一个或多个 GUILD ID
        if GUILD_ID:
            # 通过逗号分割字符串，并移除每个ID周围可能存在的空格，然后转换为整数列表
            self.guild_ids = [int(gid.strip()) for gid in GUILD_ID.split(',') if gid.strip()]
            logger.info(f"已加载 {len(self.guild_ids)} 个目标服务器 ID。")
        else:
            self.guild_ids = []
            logger.info("未在 .env 文件中指定 GUILD_ID，将进行全局同步。")

        # 确保 intents 正确设置
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # 确保开启了成员意图，以便获取用户信息
        super().__init__(command_prefix="!", intents=intents)
        
        # --- 在这里加载和处理全局配置 ---
        self.resource_channel_ids: set[int] = self._load_resource_channels()
        
        # 2. 更新服务属性的名称和类型提示
        self.db: Database | None = None
        self.author_follow_service: AuthorFollowService | None = None
        self.profile_service: ProfileService | None = None
        self.db_backup_task: asyncio.Task | None = None # 新增：用于存储备份任务

    def _load_resource_channels(self) -> set[int]:
        """从环境变量加载并解析需要监听的频道ID"""
        resource_channel_ids_str = os.getenv('RESOURCE_CHANNEL_IDS', '')
        logger.info(f"从 .env 加载的 RESOURCE_CHANNEL_IDS 原始字符串: '{resource_channel_ids_str}'")
        if not resource_channel_ids_str:
            logger.warning("警告：在 .env 文件中未配置任何有效的 RESOURCE_CHANNEL_IDS！机器人将不会监听任何频道。")
            return set()
        
        try:
            ids = {int(id.strip()) for id in resource_channel_ids_str.split(',') if id.strip()}
            logger.info(f"成功解析并加载了 {len(ids)} 个监听频道 ID。")
            return ids
        except ValueError as e:
            logger.error(f"错误：解析 RESOURCE_CHANNEL_IDS 时出错！请检查 .env 文件中的 ID 是否为纯数字并用英文逗号分隔。错误信息: {e}")
            return set() # 解析失败时，返回空集合以防止后续代码出错

    async def setup_hook(self) -> None:
        """
        Bot 启动时执行的异步初始化。
        加载 cogs 并同步命令树。
        """
        # --- 1. 初始化数据库和所有服务 ---
        self.db = Database()
        await self.db.connect()
        
        self.author_follow_service = AuthorFollowService(self.db)
        self.profile_service = ProfileService(self.db, self.author_follow_service)
        logger.info("数据库和服务已成功初始化。")

        # --- 2. 启动数据库备份任务 ---
        await self.start_db_backup_task()

        # --- 3. 加载所有模块/Cogs ---
        await self.load_all_cogs()

        # --- 4. 同步应用命令 ---
        logger.info("--- 正在同步应用命令 ---")
        if self.guild_ids:
            for guild_id in self.guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"命令树已同步到服务器: {guild_id}")
        else:
            # 否则进行全局同步，这可能需要长达一小时才能生效
            await self.tree.sync()
            logger.info("命令树已全局同步。")

        # --- 5. 列出已加载的命令 ---
        self.list_loaded_commands()

        logger.info(f"以 {self.user} (ID: {self.user.id}) 的身份登录")
        logger.info('------------------------')

    async def start_db_backup_task(self):
        """从环境变量读取配置并启动数据库备份的后台任务。"""
        backup_interval_hours_str = os.getenv('BACKUP_INTERVAL_HOURS')
        if backup_interval_hours_str and backup_interval_hours_str.isdigit() and int(backup_interval_hours_str) > 0:
            interval_hours = int(backup_interval_hours_str)
            interval_seconds = interval_hours * 3600
            self.db_backup_task = self.loop.create_task(self.db.start_backup_loop(interval_seconds))
            logger.info(f"已启动数据库自动备份任务，间隔为 {interval_hours} 小时。")
        else:
            logger.warning("数据库自动备份已禁用（未配置或间隔为0）。")

    async def close(self):
        """在机器人关闭时，优雅地清理资源。"""
        logger.info("正在关闭机器人并清理资源...")
        # 1. 取消后台任务
        if self.db_backup_task and not self.db_backup_task.done():
            self.db_backup_task.cancel()
            logger.info("数据库备份任务已取消。")
        
        # 2. 关闭数据库连接
        if self.db and self.db.conn:
            await self.db.conn.close()
            logger.info("数据库连接已关闭。")
        
        # 3. 调用父类的 close 方法
        await super().close()
        logger.info("机器人已成功关闭。")

    async def load_all_cogs(self):
        """一个健壮的方法，用于查找并加载所有 Cogs。"""
        # 使用 pathlib 来处理路径，使其与操作系统无关
        project_root = pathlib.Path(__file__).parent.parent
        modules_root = project_root / "src" / "modules"
        
        logger.info("--- 正在加载 模块 ---")
        # 递归查找 'modules' 目录下所有 'cogs' 子文件夹中的 .py 文件
        for path in modules_root.rglob("cogs/*.py"):
            if path.name == "__init__.py":
                continue
            
            # 将文件路径转换为 Python 模块路径
            # 例如: E:\...\src\modules\feature\cogs\cmd.py -> src.modules.feature.cogs.cmd
            module_path = ".".join(path.relative_to(project_root).parts).removesuffix(".py")
            try:
                await self.load_extension(module_path)
                logger.info(f"✅ 已加载: {module_path}")
            except Exception as e:
                logger.error(f"❌ 加载 {module_path} 失败: {e}", exc_info=True)
        logger.info("--- 模块 加载完毕 ---")

    def list_loaded_commands(self):
        """用于打印出所有已注册的应用命令。"""
        logger.info("--- 已加载的应用命令 ---")
        # 从命令树中获取所有已注册的命令
        commands = self.tree.get_commands()
        if not commands:
            logger.info("  未找到任何应用命令。")
        else:
            for command in commands:
                logger.info(f"  - /{command.name}")
        logger.info("------------------------")


async def main():
    # 在启动bot前先配置好日志
    setup_logging()

    if not TOKEN:
        logger.critical("错误：未在 .env 文件中找到 DISCORD_TOKEN。机器人无法启动。")
        return

    bot = MyBot()
    
    try:
        await bot.start(TOKEN)
    except discord.errors.LoginFailure:
        logger.critical("错误：提供的 DISCORD_TOKEN 无效。请检查 .env 文件。")
    except Exception as e:
        logger.critical(f"机器人启动时发生致命错误: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 使用logger而不是print
        logging.getLogger(__name__).info("机器人正在关闭。")
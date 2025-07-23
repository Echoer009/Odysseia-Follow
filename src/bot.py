import discord
from discord.ext import commands
import os
import asyncio
import pathlib
from dotenv import load_dotenv, find_dotenv
from src.core.database import Database
from src.modules.author_follow.services.author_follow_service import AuthorFollowService
from src.modules.user_profile_feature.services.profile_service import ProfileService
from src.modules.channel_subscription.services.subscription_service import SubscriptionService
from src.modules.thread_favorites.services.favorites_service import FavoritesService
from src.modules.thread_favorites.services.scanner_service import ActiveThreadScanner
import logging
from src.core.logging_setup import setup_logging

# 使用 find_dotenv() 确保总能找到 .env 文件
load_dotenv(find_dotenv())
TOKEN = os.getenv('DISCORD_TOKEN')

# 获取一个logger实例
logger = logging.getLogger(__name__)

class MyBot(commands.Bot):
    def __init__(self):
        logger.info("--- ⌛ 0. 环境与配置加载 ---")
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

        # --- 在这里加载和处理全局配置 ---
        self.resource_channel_ids: set[int] = self._load_resource_channels()

        # 确保 intents 正确设置
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # 确保开启了成员意图，以便获取用户信息
        super().__init__(command_prefix="!", intents=intents)
        
        # 2. 更新服务属性的名称和类型提示
        self.db: Database | None = None
        self.author_follow_service: AuthorFollowService | None = None
        self.profile_service: ProfileService | None = None
        self.subscription_service: SubscriptionService | None = None
        self.favorites_service: FavoritesService | None = None
        self.db_backup_task: asyncio.Task | None = None
        self.scanner_service: ActiveThreadScanner | None = None

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
        这里只做最核心、最快的初始化。
        """
        logger.info("--- 🚀 1. 初始化核心服务 ---")
        self.db = Database()
        await self.db.connect()
        
        self.author_follow_service = AuthorFollowService(self.db)
        self.profile_service = ProfileService(self.db, self.author_follow_service)
        self.subscription_service = SubscriptionService(self.db)
        self.favorites_service = FavoritesService(self.db)
        self.scanner_service = ActiveThreadScanner(self, self.db)
        logger.info("✅ 核心服务初始化完成。")

        logger.info("--- 🧩 2. 加载功能模块 (Cogs) ---")
        await self.load_all_cogs()

        logger.info("--- 🛰️ 3. 同步应用命令 ---")
        if self.guild_ids:
            for guild_id in self.guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"✅ 命令已同步到服务器: {guild_id}")
        else:
            await self.tree.sync()
            logger.info("✅ 命令已全局同步。")
        
        self.list_loaded_commands()
        logger.info(f"--- 🎉 机器人核心已就绪,等待 Discord 连接成功...---")

    async def on_ready(self):
        """当机器人成功连接到 Discord 后执行所有耗时和后台任务。"""
        logger.info(f"--- ✅ 已成功连接到 Discord ---,以 {self.user} (ID: {self.user.id}) 的身份登录-")

        # --- 4. 执行首次扫描并填充队列 ---
        logger.info("--- 🏃 4. 执行首次帖子扫描 (这可能需要一点时间) ---")
        for guild in self.guilds:
            await self.scanner_service.scan_guild(guild)
        logger.info("✅ 首次帖子扫描完成，待办队列已填充。")

        # --- 5. 启动所有后台任务 ---
        logger.info("--- 🚀 5. 启动所有后台服务 ---")
        self.start_background_tasks()
        logger.info("✅ 所有后台服务已成功启动。")
        logger.info("======================== 机器人完全就绪 ========================")

    def start_background_tasks(self):
        """统一启动所有后台任务。"""
        # 数据库备份
        backup_interval_hours_str = os.getenv('BACKUP_INTERVAL_HOURS')
        if backup_interval_hours_str and backup_interval_hours_str.isdigit() and int(backup_interval_hours_str) > 0:
            interval_hours = int(backup_interval_hours_str)
            self.db_backup_task = self.loop.create_task(self.db.start_backup_loop(interval_hours * 3600))
            logger.info("  - [启动] 数据库自动备份任务。")
        else:
            logger.warning("  - [跳过] 数据库自动备份已禁用。")

        # 帖子扫描器 (周期性)
        scanner_interval_hours_str = os.getenv('SCANNER_INTERVAL_HOURS')
        if scanner_interval_hours_str and scanner_interval_hours_str.isdigit() and int(scanner_interval_hours_str) > 0:
            interval_hours = int(scanner_interval_hours_str)
            self.scanner_service.start(interval_hours * 3600)
            logger.info("  - [启动] 活跃帖子扫描服务。")
        else:
            logger.warning("  - [跳过] 活跃帖子扫描服务已禁用。")


    async def close(self):
        """在机器人关闭时，优雅地清理资源。"""
        logger.info("正在关闭机器人并清理资源...")

        # 1. 首先，调用父类的 close 方法。
        # 这会优雅地断开与 Discord 的连接，并停止所有内部任务（如心跳）。
        # 这是解决 "Event loop is closed" 错误的关键。
        await super().close()
        logger.info("Discord 客户端已成功关闭。")

        # 2. 在 Discord 连接关闭后，再清理我们自己的资源。
        # 取消我们自己创建的后台任务
        if self.db_backup_task and not self.db_backup_task.done():
            self.db_backup_task.cancel()
            logger.info("数据库备份任务已取消。")
        
        if self.scanner_service and self.scanner_service.task and not self.scanner_service.task.done():
            self.scanner_service.stop()
            logger.info("活跃帖子扫描任务已停止。")
        

        # 关闭数据库连接
        if self.db and self.db.conn:
            await self.db.conn.close()
            logger.info("数据库连接已关闭。")
        
        logger.info("所有自定义资源已成功清理，机器人已完全关闭。")

    async def load_all_cogs(self):
        """一个健壮的方法，用于查找并加载所有 Cogs。"""
        # 使用 pathlib 来处理路径，使其与操作系统无关
        project_root = pathlib.Path(__file__).parent.parent
        modules_root = project_root / "src" / "modules"
        
        # 递归查找 'modules' 目录下所有 'cogs' 子文件夹中的 .py 文件
        for path in modules_root.rglob("cogs/*.py"):
            if path.name == "__init__.py" or path.name == "views.py":
                continue
            
            # 将文件路径转换为 Python 模块路径
            # 例如: E:\...\src\modules\feature\cogs\cmd.py -> src.modules.feature.cogs.cmd
            module_path = ".".join(path.relative_to(project_root).parts).removesuffix(".py")
            try:
                await self.load_extension(module_path)
                logger.info(f"✅ 已加载: {module_path}")
            except Exception as e:
                logger.error(f"❌ 加载 {module_path} 失败: {e}", exc_info=True)

    def list_loaded_commands(self):
        """用于打印出所有已注册的应用命令。"""
        logger.info("--- 📋 已加载的应用命令 ---")
        # 从命令树中获取所有已注册的命令
        commands = self.tree.get_commands()
        if not commands:
            logger.info("  未找到任何应用命令。")
        else:
            for command in commands:
                logger.info(f"  - /{command.name}")


async def main():
    # 在启动bot前先配置好日志
    setup_logging()

    if not TOKEN:
        logger.critical("错误：未在 .env 文件中找到 DISCORD_TOKEN。机器人无法启动。")
        return

    bot = MyBot()
    
    try:
        # bot.start() 会一直运行，直到机器人断开或被关闭。
        await bot.start(TOKEN)
    except discord.errors.LoginFailure:
        logger.critical("错误：提供的 DISCORD_TOKEN 无效。请检查 .env 文件。")
    except Exception as e:
        # 捕获其他潜在的启动错误
        logger.critical(f"机器人启动时发生致命错误: {e}", exc_info=True)
    finally:
        # 无论 try 块如何退出（正常结束、异常、或被 Ctrl+C 取消），
        # finally 块都会执行。这是确保资源被释放的关键。
        if not bot.is_closed():
            logger.info("检测到程序即将退出，正在优雅地关闭机器人...")
            await bot.close()

if __name__ == "__main__":
    try:
        # asyncio.run() 会优雅地处理 KeyboardInterrupt。
        # 它会取消 main() 任务，等待其完成（包括 finally 块），然后关闭事件循环。
        asyncio.run(main())
    except KeyboardInterrupt:
        # 这个捕获块现在主要是为了提供一个清晰的退出信息，
        # 并防止向用户显示不必要的堆栈跟踪。
        # 此时，main() 中的 finally 块应该已经执行完毕。
        logging.getLogger(__name__).info("程序已干净地退出。")
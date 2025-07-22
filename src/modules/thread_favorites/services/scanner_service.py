import os
import discord
import asyncio
import logging
from src.core.database import Database

logger = logging.getLogger(__name__)

class ActiveThreadScanner:
    def __init__(self, bot, db: Database):
        self.bot = bot
        self.db = db
        self.task: asyncio.Task = None
        try:
            self.concurrent_tasks = int(os.getenv('SCANNER_CONCURRENT_TASKS', '25'))
            self.chunk_delay = float(os.getenv('SCANNER_CHUNK_DELAY_SECONDS', '0.5'))
        except (ValueError, TypeError):
            self.concurrent_tasks = 25
            self.chunk_delay = 0.5
        logger.info(f"扫描服务已配置：并发数={self.concurrent_tasks}, 批次延迟={self.chunk_delay}s")

    async def _process_thread(self, thread: discord.Thread, guild_id: int):
        """处理单个帖子的逻辑。"""
        try:
            # 检查机器人是否是成员，如果不是，则主动加入
            if thread.me is None:
                # 检查帖子是否已归档或锁定，这种情况下可能无法加入
                if thread.archived or thread.locked:
                    logger.debug(f"帖子 '{thread.name}' (ID: {thread.id}) 已归档或锁定，无法加入，跳过。")
                    return thread, 0, None
                
                try:
                    logger.debug(f"机器人不是帖子 '{thread.name}' 的成员，正在尝试主动加入...")
                    await thread.join()
                    logger.debug(f"成功加入帖子 '{thread.name}' (ID: {thread.id})。")
                except discord.HTTPException as join_e:
                    logger.warning(f"尝试加入帖子 '{thread.name}' (ID: {thread.id}) 失败: {join_e}。跳过此帖。")
                    return thread, None, join_e

            # 现在机器人肯定是成员了，可以获取成员列表
            members = await thread.fetch_members()
            member_ids = [member.id for member in members]
            await self.db.update_active_thread_members(thread.id, thread.name, member_ids, guild_id)
            return thread, len(member_ids), None
        except discord.HTTPException as e:
            logger.warning(f"获取帖子 '{thread.name}' (ID: {thread.id}) 的成员时发生HTTP异常: {e}。跳过此帖。")
            return thread, None, e
        except Exception as e:
            logger.error(f"处理帖子 '{thread.name}' 时发生未知错误: {e}", exc_info=True)
            return thread, None, e

    async def scan_guild(self, guild: discord.Guild):
        """对单个服务器执行并发扫描和数据更新。"""
        logger.info(f"开始扫描服务器 '{guild.name}' (ID: {guild.id}) 的活跃帖子...")
        
        try:
            active_threads = await asyncio.wait_for(guild.active_threads(), timeout=60.0)
        except asyncio.TimeoutError:
            logger.error(f"获取服务器 '{guild.name}' 的活跃帖子列表超时（超过60秒）。")
            return
        except Exception as e:
            logger.critical(f"获取服务器 '{guild.name}' 的活跃帖子时发生未知严重错误: {e}", exc_info=True)
            return

        if not active_threads:
            logger.info(f"服务器 '{guild.name}' 中没有找到活跃帖子。")
            return

        total_threads = len(active_threads)
        logger.info(f"在 '{guild.name}' 中找到 {total_threads} 个活跃帖子，开始并发处理...")
        
        await self.db.clear_active_thread_members(guild.id)
        
        processed_count = 0
        for i in range(0, total_threads, self.concurrent_tasks):
            chunk = active_threads[i:i + self.concurrent_tasks]
            tasks = [self._process_thread(thread, guild.id) for thread in chunk]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for res in results:
                processed_count += 1
                if isinstance(res, Exception):
                    logger.error(f"处理一个帖子时 gather 捕获到未处理的异常: {res}")
                else:
                    thread, member_count, error = res
                    if error:
                        # 错误已在 _process_thread 中记录，这里可以只计数
                        pass
                    else:
                        logger.debug(f"({processed_count}/{total_threads}) 已处理 '{thread.name}'，找到 {member_count} 个成员。")
            
            if i + self.concurrent_tasks < total_threads:
                logger.debug(f"完成一个批次的处理，等待{self.chunk_delay}秒后继续...")
                await asyncio.sleep(self.chunk_delay)

        logger.info(f"服务器 '{guild.name}' 的活跃帖子扫描完成。")

    async def start_scanning_loop(self, interval_seconds: int):
        """启动后台循环任务。"""
        await self.bot.wait_until_ready()
        logger.info(f"后台扫描任务已启动，将立即开始首次扫描，扫描间隔为 {interval_seconds / 3600:.1f} 小时。")
        
        while not self.bot.is_closed():
            # 1. 执行扫描
            logger.info("开始新一轮的活跃帖子扫描...")
            for guild in self.bot.guilds:
                # 增加一个检查，以防在扫描过程中机器人关闭
                if self.bot.is_closed():
                    logger.info("机器人在扫描服务器期间关闭，任务终止。")
                    return
                await self.scan_guild(guild)
            
            # 2. 等待下一次扫描
            logger.info(f"所有服务器扫描完毕，将在 {interval_seconds / 3600:.1f} 小时后再次扫描。")
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                logger.info("扫描任务被取消，循环终止。")
                break

    def start(self, interval_seconds: int):
        """公开的启动方法。"""
        if self.task and not self.task.done():
            logger.warning("扫描任务已在运行中。")
            return
        self.task = self.bot.loop.create_task(self.start_scanning_loop(interval_seconds))

    def stop(self):
        """停止后台任务。"""
        if self.task and not self.task.done():
            self.task.cancel()
            logger.info("后台扫描任务已取消。")

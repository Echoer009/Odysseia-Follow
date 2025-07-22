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
        # 为服务器扫描操作添加一个全局锁，防止手动刷新和后台任务并发执行
        self.scan_lock = asyncio.Lock()
        try:
            self.concurrent_tasks = int(os.getenv('SCANNER_CONCURRENT_TASKS', '25'))
            self.chunk_delay = float(os.getenv('SCANNER_CHUNK_DELAY_SECONDS', '0.5'))
        except (ValueError, TypeError):
            self.concurrent_tasks = 25
            self.chunk_delay = 0.5
        # 创建一个信号量，用于限制并发的“加入帖子”请求数量，防止速率限制。
        # 这就像一个只允许1个请求同时通过的门，可以有效避免请求风暴。
        self.join_semaphore = asyncio.Semaphore(1)
        logger.info(f"扫描服务已配置：并发数={self.concurrent_tasks}, 批次延迟={self.chunk_delay}s, 加入并发数=1")

    async def _process_thread(self, thread: discord.Thread, guild_id: int):
        """
        处理单个帖子的逻辑。
        如果缓存显示机器人不是成员，则会二次核查。
        """
        # 1. 检查缓存中的成员状态，如果显示未加入，则进行二次核查
        if thread.me is None:
            try:
                logger.debug(f"缓存显示未加入帖子 '{thread.name}' (ID: {thread.id})，正在二次核查...")
                # 使用 fetch_channel 获取最新的帖子对象，覆盖掉可能过时的缓存对象
                thread = await self.bot.fetch_channel(thread.id)
                if not isinstance(thread, discord.Thread):
                    logger.warning(f"对象 (ID: {thread.id}) 在二次核查时发现不是帖子。")
                    return thread, 0, None  # 无法处理
            except (discord.NotFound, discord.Forbidden):
                logger.warning(f"二次核查帖子 (ID: {thread.id}) 时失败（可能已删除或无权限），跳过。")
                return thread, 0, None  # 无法处理
            except Exception as e:
                logger.error(f"二次核查帖子 (ID: {thread.id}) 时发生未知错误: {e}", exc_info=True)
                return thread, 0, None  # 无法处理

        # 2. 经过二次核查（如果需要），现在我们有了更新的帖子对象，再次检查成员状态
        if thread.me is None:
            # 确认未加入
            if not thread.archived and not thread.locked:
                await self.db.add_thread_to_join_queue(thread.id, guild_id)
                logger.debug(f"确认未加入帖子 '{thread.name}' (ID: {thread.id})，已添加到待办队列。")
            return thread, 0, None  # 扫描器的任务完成
        else:
            # 确认已加入 (无论是最初缓存正确，还是二次核查后发现)
            try:
                members = await thread.fetch_members()
                member_ids = [member.id for member in members]
                await self.db.update_active_thread_members(thread.id, thread.name, member_ids, guild_id)
                logger.debug(f"已处理成员帖子 '{thread.name}'，找到 {len(member_ids)} 个成员。")
                return thread, len(member_ids), None
            except discord.HTTPException as e:
                logger.warning(f"获取帖子 '{thread.name}' 的成员失败: {e}。跳过此帖。")
                return thread, None, e
            except Exception as e:
                logger.error(f"处理帖子 '{thread.name}' 时发生未知错误: {e}", exc_info=True)
                return thread, None, e

    async def scan_guild(self, guild: discord.Guild):
        """对单个服务器执行并发扫描和数据更新。此方法现在是线程安全的。"""
        async with self.scan_lock:
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
        """启动后台循环任务。该任务会先等待一个周期，然后再执行扫描。"""
        await self.bot.wait_until_ready()
        logger.info(f"后台扫描任务已启动，将在 {interval_seconds / 3600:.1f} 小时后进行首次周期性扫描。")
        
        while not self.bot.is_closed():
            try:
                # 1. 首先等待一个完整的周期
                await asyncio.sleep(interval_seconds)

                # 2. 等待结束后，执行扫描
                logger.info("开始新一轮的周期性活跃帖子扫描...")
                for guild in self.bot.guilds:
                    # 增加一个检查，以防在扫描过程中机器人关闭
                    if self.bot.is_closed():
                        logger.info("机器人在扫描服务器期间关闭，任务终止。")
                        return
                    await self.scan_guild(guild)
                logger.info(f"周期性扫描完成，将在 {interval_seconds / 3600:.1f} 小时后再次扫描。")

            except asyncio.CancelledError:
                logger.info("扫描任务被取消，循环终止。")
                break
            except Exception as e:
                logger.error(f"后台扫描循环中发生未知错误: {e}", exc_info=True)
                # 发生未知错误后，为避免快速失败循环，同样等待一个周期
                logger.info("为防止错误快速循环，将等待一个周期后重试...")
                try:
                    await asyncio.sleep(interval_seconds)
                except asyncio.CancelledError:
                    logger.info("在错误恢复等待期间，扫描任务被取消，循环终止。")
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

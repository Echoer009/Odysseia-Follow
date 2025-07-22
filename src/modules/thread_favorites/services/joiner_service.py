import discord
import asyncio
import logging
import os
from src.core.database import Database

logger = logging.getLogger(__name__)

class ThreadJoiner:
    def __init__(self, bot: discord.Client, db: Database):
        self.bot = bot
        self.db = db
        self.task: asyncio.Task = None
        try:
            self.interval = int(os.getenv('JOINER_INTERVAL_SECONDS', '5'))
        except (ValueError, TypeError):
            self.interval = 5

    async def _join_thread_loop(self):
        """后台循环，处理待加入的帖子队列。"""
        await self.bot.wait_until_ready()
        logger.info(f"帖子自动加入服务已启动，将每 {self.interval} 秒处理一个任务。")

        while not self.bot.is_closed():
            try:
                # 1. 从数据库获取一个待办任务
                queue_item = await self.db.get_oldest_thread_from_join_queue()

                if queue_item:
                    thread_id, guild_id = queue_item
                    logger.info(f"开始处理待加入的帖子，ID: {thread_id}")

                    status = "processed" # 默认为已处理
                    try:
                        # 2. 尝试获取帖子对象并加入
                        thread = await self.bot.fetch_channel(thread_id)
                        
                        if not isinstance(thread, discord.Thread):
                            logger.warning(f"对象 (ID: {thread_id}) 不是一个帖子，无法加入。将标记为失败。")
                            status = "failed"
                        elif thread.me:
                            logger.info(f"机器人已经是帖子 '{thread.name}' (ID: {thread_id}) 的成员，无需加入。标记为已处理。")
                            status = "processed"
                        else:
                            await thread.join()
                            logger.info(f"成功加入帖子 '{thread.name}' (ID: {thread_id})。")
                            
                            # 成功加入后，立即获取成员并更新 active_thread_members 表
                            try:
                                members = await thread.fetch_members()
                                member_ids = [member.id for member in members]
                                await self.db.update_active_thread_members(thread.id, thread.name, member_ids, guild_id)
                                logger.info(f"已为新加入的帖子 '{thread.name}' 更新了 {len(member_ids)} 名成员。")
                            except Exception as e:
                                logger.error(f"为新加入的帖子 '{thread.name}' 更新成员时出错: {e}", exc_info=True)
                            
                            status = "processed"
                            
                    except discord.Forbidden:
                        logger.warning(f"无法加入帖子 (ID: {thread_id})，原因是权限不足（可能是私有帖子）。将标记为失败。")
                        status = "failed"
                    except discord.NotFound:
                        logger.warning(f"找不到帖子 (ID: {thread_id})，可能已被删除。将标记为失败。")
                        status = "failed"
                    except Exception as e:
                        logger.error(f"加入帖子 (ID: {thread_id}) 时发生未知错误: {e}", exc_info=True)
                        status = "failed"
                    finally:
                        # 3. 无论成功与否，都更新任务的状态
                        await self.db.update_join_queue_status(thread_id, status)
                        logger.info(f"已更新任务 (ID: {thread_id}) 状态为 '{status}'。")
                
                # 4. 等待下一个周期
                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                logger.info("帖子加入任务被取消，循环终止。")
                break
            except Exception as e:
                logger.critical(f"帖子加入服务循环发生严重错误: {e}", exc_info=True)
                # 发生严重错误时，等待更长时间以防循环过快失败
                await asyncio.sleep(60)

    def start(self):
        """公开的启动方法。"""
        if self.task and not self.task.done():
            logger.warning("帖子加入任务已在运行中。")
            return
        self.task = self.bot.loop.create_task(self._join_thread_loop())

    def stop(self):
        """停止后台任务。"""
        if self.task and not self.task.done():
            self.task.cancel()
            logger.info("帖子加入任务已取消。")
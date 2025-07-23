# src/core/utils.py
import asyncio
import logging
import discord
from typing import Coroutine, Any, TypeVar, Callable

logger = logging.getLogger(__name__)

T = TypeVar('T')

async def retry_on_discord_error(
    coro_func: Callable[[], Coroutine[Any, Any, T]],
    operation_name: str,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0
) -> T:
    """
    一个工具函数，当发生 DiscordServerError 时，使用指数退避策略重试一个协程。
    为了更详细的日志记录，现在传入一个返回协程的函数。

    :param coro_func: 一个返回需要执行的协程的函数 (例如: lambda: channel.fetch_message(id))
    :param operation_name: 操作的描述性名称，用于日志记录 (例如: "获取比赛消息")
    :param max_retries: 最大重试次数
    :param initial_delay: 初始延迟秒数
    :param backoff_factor: 每次重试后延迟时间增加的倍数
    :return: 如果成功，返回协程的结果
    :raises: 如果所有重试都失败，则抛出最后一个异常
    """
    delay = initial_delay
    logger.debug(f"开始执行操作: '{operation_name}'，最多重试 {max_retries} 次。")
    
    for i in range(max_retries):
        try:
            # 调用函数以获取新的协程对象并执行
            result = await coro_func()
            logger.debug(f"操作 '{operation_name}' 成功。")
            return result
        except discord.errors.DiscordServerError as e:
            if i == max_retries - 1:
                logger.error(
                    f"操作 '{operation_name}' 在 {max_retries} 次重试后最终失败。最后一次错误: {e}",
                    exc_info=True
                )
                raise
            
            logger.warning(
                f"操作 '{operation_name}' 失败 (尝试 {i + 1}/{max_retries})，状态码: {e.status}。将在 {delay:.2f} 秒后重试..."
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor
            
    # 这段代码理论上不应该被执行到
    raise RuntimeError(f"操作 '{operation_name}' 的重试逻辑出现意外错误。")
import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler

def setup_logging():
    """
    配置日志系统，确保处理器不重复添加。
    使用更简洁的日志格式。
    """
    # 获取根logger
    root_logger = logging.getLogger()
    
    if root_logger.hasHandlers():
        return

    root_logger.setLevel(logging.INFO)

    # --- 核心改动：定义一个新的、更简洁的格式化器 ---
    # 新格式: 2025-07-18 01:55:10 [INFO] 消息内容
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # --- 确保日志目录存在 ---
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 创建文件处理器 (每天轮换)
    # 文件日志可以保留更详细的信息，方便排错
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler = TimedRotatingFileHandler(
        'logs/bot.log', when='midnight', interval=1, backupCount=7, encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # 仅在第一次配置时打印此消息
    # root_logger.info("日志系统已配置完成。") # 这条消息可以注释掉，让启动更干净
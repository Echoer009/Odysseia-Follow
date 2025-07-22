import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler
from pythonjsonlogger import jsonlogger

def setup_logging():
    """
    配置日志系统，确保处理器不重复添加。
    使用更简洁的日志格式。
    """
    # 获取根logger
    root_logger = logging.getLogger()
    
    if root_logger.hasHandlers():
        # 如果已经有处理器，假设已经配置过，直接返回
        return

    root_logger.setLevel(logging.INFO)

    # --- 控制台格式化器 (人类可读) ---
    console_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # --- 文件格式化器 (JSON) ---
    json_formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(message)s',
        rename_fields={
            'asctime': 'timestamp',
            'levelname': 'level'
        }
    )

    # --- 确保日志目录存在 ---
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # --- 创建控制台处理器 ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # --- 创建文件处理器 (JSON) ---
    log_interval = int(os.getenv('LOG_ROTATION_INTERVAL_DAYS', '1'))
    log_backup_count = int(os.getenv('LOG_BACKUP_COUNT', '7'))
    file_handler = TimedRotatingFileHandler(
        'logs/bot.log', when='midnight', interval=log_interval, backupCount=log_backup_count, encoding='utf-8'
    )
    file_handler.setFormatter(json_formatter) # 使用 JSON 格式化器
    root_logger.addHandler(file_handler)

    # 设置 discord.py 内部 logger 的级别
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)

    root_logger.info("日志系统初始化完成 (控制台: text, 文件: json)")
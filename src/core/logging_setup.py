import logging
import sys
from logging.handlers import TimedRotatingFileHandler
import os

def setup_logging():
    """配置全局日志记录器"""
    log_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # --- 控制台处理器 ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    
    # --- 文件处理器 (每天轮换，保留7天) ---
    # 确保logs目录存在
    if not os.path.exists('logs'):
        os.makedirs('logs')
        
    file_handler = TimedRotatingFileHandler(
        'logs/bot.log', when='midnight', interval=1, backupCount=7, encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    
    # --- 获取根记录器并添加处理器 ---
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) # 设置全局日志级别
    
    # 防止重复添加处理器
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    # --- 为一些嘈杂的库设置更高的日志级别，避免刷屏 ---
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('websockets').setLevel(logging.WARNING)
    
    print("日志系统已配置完成。") # 这里用print是为了在日志系统启动前给出明确反馈
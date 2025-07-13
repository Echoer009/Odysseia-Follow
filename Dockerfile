# 1. 使用一个官方的、轻量级的 Python 镜像作为基础
FROM python:3.11-slim

# 2. 在容器内创建一个工作目录
WORKDIR /app

# 3. 复制依赖文件
#    我们先复制这个文件并安装依赖，这样可以利用Docker的层缓存。
#    只要 requirements.txt 不变，Docker就不会重新安装依赖，从而加快构建速度。
COPY requirements.txt .

# 4. 安装依赖，--no-cache-dir 可以减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt

# 5. 复制项目的所有代码到工作目录
COPY . .

# 6. 定义容器启动时要执行的命令
#    这和您在本地运行的方式完全一致
CMD ["python", "-m", "src.bot"]
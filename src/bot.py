import discord
from discord.ext import commands
import os
import asyncio
import pathlib
from dotenv import load_dotenv, find_dotenv
from src.core.database import Database
from src.modules.author_follow.services.author_follow_service import AuthorFollowService
from src.modules.user_profile_feature.services.profile_service import ProfileService

# 使用 find_dotenv() 确保总能找到 .env 文件
load_dotenv(find_dotenv())
TOKEN = os.getenv('DISCORD_TOKEN')
# 读取你在 .env 文件中设置的服务器ID
GUILD_ID = os.getenv('GUILD_ID')

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # 确保开启了成员意图，以便获取用户信息
        super().__init__(command_prefix="!", intents=intents)
        
        # 将服务器ID转换为整数并存储，以便后续使用
        self.test_guild_id = int(GUILD_ID) if GUILD_ID else None
        
        # 2. 更新服务属性的名称和类型提示
        self.db: Database | None = None
        self.author_follow_service: AuthorFollowService | None = None
        self.profile_service: ProfileService | None = None


    async def setup_hook(self):
        # 3. 更新服务实例化
        self.db = Database() # 假设你的DB_NAME在env里
        await self.db.connect() # 假设你的Database类有connect方法
        
        self.author_follow_service = AuthorFollowService(self.db)
        self.profile_service = ProfileService(self.db, self.author_follow_service)
        
        # 定义要加载的模块列表
        modules_to_load = [
            'src.modules.author_follow.cogs.author_tracker',
            'src.modules.user_profile_feature.cogs.profile_cog',
        ]

        for module_path in modules_to_load:
            try:
                await self.load_extension(module_path) 
                print(f"✅ 成功加载模块: {module_path}")
            except Exception as e:
                print(f"❌ 加载模块 {module_path} 失败: {e}")

        # 修改这里的逻辑，使用服务器ID进行同步
        if self.test_guild_id:
            guild = discord.Object(id=self.test_guild_id)
            await self.tree.sync(guild=guild)
            print(f"命令树已同步到服务器: {self.test_guild_id}")
        else:
            # 否则进行全局同步，这可能需要长达一小时才能生效
            await self.tree.sync()
            print("命令树已全局同步。")

        # 新增：打印所有已加载的应用命令
        self.list_loaded_commands()

    async def on_ready(self):
        print(f'以 {self.user} (ID: {self.user.id}) 的身份登录')
        print('------')

    async def load_all_cogs(self):
        """一个健壮的方法，用于查找并加载所有 Cogs。"""
        project_root = pathlib.Path(__file__).parent.parent
        modules_root = project_root / "src" / "modules"
        
        print("--- 正在加载 Cogs ---")
        # 递归查找 'modules' 目录下所有 'cogs' 子文件夹中的 .py 文件
        for path in modules_root.rglob("cogs/*.py"):
            if path.name == "__init__.py":
                continue
            
            # 将文件路径转换为 Python 模块路径
            # 例如: E:\...\src\modules\feature\cogs\cmd.py -> src.modules.feature.cogs.cmd
            module_path = ".".join(path.relative_to(project_root).parts).removesuffix(".py")
            try:
                await self.load_extension(module_path)
                print(f"  [成功] 已加载: {module_path}")
            except Exception as e:
                print(f"  [失败] 加载 {module_path} 失败: {e}")
        print("--- Cogs 加载完毕 ---")

    def list_loaded_commands(self):
        """一个新方法，用于打印出所有已注册的应用命令。"""
        print("--- 已加载的应用命令 ---")
        # 从命令树中获取所有已注册的命令
        commands = self.tree.get_commands()
        if not commands:
            print("  未找到任何应用命令。")
        else:
            for command in commands:
                print(f"  - /{command.name}")
        print("------------------------")


async def main():
    bot = MyBot()
    await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("机器人正在关闭。")
import discord
from discord.ext import commands
from discord import app_commands
# 1. 修正导入路径，使用从 'src' 开始的绝对路径
from src.modules.follow_feature.services.follow_service import FollowService

class UserProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # bot对象上已经附加了follow_service实例
        self.follow_service: FollowService = bot.follow_service

    # 2. 修改装饰器为 app_commands.command
    # 3. 修改函数签名，使用 interaction: discord.Interaction
    @app_commands.command(name="我的关注", description="查看您关注的所有作者列表")
    async def my_follows(self, interaction: discord.Interaction):
        try:
            # 4. 将 ctx.author.id 替换为 interaction.user.id
            followed_authors = await self.follow_service.get_user_follows_details(interaction.user.id)

            if not followed_authors:
                # 5. 将 ctx.respond 替换为 interaction.response.send_message
                await interaction.response.send_message("您还没有关注任何作者。", ephemeral=True)
                return

            # 创建更详细的描述
            description_lines = []
            for author in followed_authors:
                # 优先显示 <@id>，如果用户不在服务器，则会显示其在数据库中记录的名字
                description_lines.append(f"• <@{author['author_id']}> (`{author['author_name']}`)")

            # 注意：如果列表过长，可能会超过Discord Embed的限制。
            # 对于超长列表，未来可以考虑使用分页视图（discord.ui.View）来优化。
            embed = discord.Embed(
                title="我关注的作者列表",
                description="以下是您关注的所有作者：\n" + "\n".join(description_lines),
                color=discord.Color.blue()
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"命令 /我的关注 执行失败: {e}")
            await interaction.response.send_message("哎呀，操作失败了，好像和数据库的连接出了点问题。请稍后再试或联系管理员。", ephemeral=True)

# 2. setup 函数需要是异步的 (async)
async def setup(bot: commands.Bot):
    await bot.add_cog(UserProfileCog(bot))
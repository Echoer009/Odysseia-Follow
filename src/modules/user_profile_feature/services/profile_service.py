from src.core.database import Database # 1. 更新数据库导入路径
from src.modules.author_follow.services.author_follow_service import AuthorFollowService

class ProfileService:
    # 3. 更新构造函数中的类型提示
    def __init__(self, db: Database, author_follow_service: AuthorFollowService):
        self.db = db
        self.author_follow_service = author_follow_service

    async def get_user_profile_data(self, user_id: int) -> list[dict]:
        """
        准备用户个人资料（我的关注）页面所需的数据。
        这是一个高级服务，组合了多个数据源和业务逻辑。
        """
        # 1. 获取上次查看时间，同时更新为现在
        last_view_time = await self.db.get_and_update_last_view(user_id)
        
        # 2. 调用 FollowService 获取用户关注的作者基础信息
        followed_authors = await self.author_follow_service.get_user_follows_details(user_id)
        if not followed_authors:
            return []

        # 3. 从数据库获取这些作者的新帖子数
        author_ids = [author['author_id'] for author in followed_authors]
        new_post_counts = await self.db.get_new_post_counts(author_ids, last_view_time)
        
        # 4. 将新帖子数量合并到作者信息中
        new_post_counts_map = {item['author_id']: item['new_posts_count'] for item in new_post_counts}
        for author in followed_authors:
            author['new_posts'] = new_post_counts_map.get(author['author_id'], 0)
        
        # 5. 按新帖子数量倒序排序
        followed_authors.sort(key=lambda x: x.get('new_posts', 0), reverse=True)
        
        return followed_authors
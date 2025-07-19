# src/modules/competition_follow/services/parsing_service.py

import discord
import re

class ParsingService:
    """
    负责解析比赛展示Embed，并识别新提交的作品。
    """

    def extract_submission_ids(self, embed: discord.Embed) -> list[str]:

        if not embed.description:
            return []
        
        # 正则表达式匹配所有 "投稿ID：`...`"
        # \` (反引号) 是Markdown中代码块的标记
        id_pattern = re.compile(r"🆔投稿ID：`(\w+)`", re.MULTILINE)
        ids = id_pattern.findall(embed.description)
        return ids

    def find_new_submissions(self, old_ids: list[str], new_ids: list[str]) -> list[str]:

        old_id_set = set(old_ids)
        new_submissions = [id for id in new_ids if id not in old_id_set]
        return new_submissions

parsing_service = ParsingService()

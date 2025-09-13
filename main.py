import asyncio
import aiomysql
from datetime import date
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
# V--- 我们将直接从 event 中获取 bot，因此不再需要导入 AiocqhttpAdapter ---V
# from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import AiocqhttpAdapter
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

@register("checkin_plugin", "Future-404", "一个集成了签到积分与兑换码功能的群管理插件", "1.0.0") # <-- 版本升级为 1.0.0
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.db_pool = None
        logger.info("签到插件 V1.0.0 正在加载...")
        asyncio.create_task(self.initialize_database())

    async def initialize_database(self):
        try:
            self.db_pool = await aiomysql.create_pool(
                host='mysql', port=3306, user='Future404',
                password='FbTy4xJ4Dc5Bw82f', db='checkin_plugin_db',
                autocommit=True
            )
            logger.info("数据库连接池创建成功。")
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("CREATE TABLE IF NOT EXISTS users (qq_id BIGINT PRIMARYARY KEY, points INT DEFAULT 0, last_checkin DATE);")
                    await cur.execute("CREATE TABLE IF NOT EXISTS codes (id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(255) UNIQUE NOT NULL);")
                    await cur.execute("CREATE TABLE IF NOT EXISTS whitelisted_groups (group_id BIGINT PRIMARY KEY);")
            logger.info("数据库表初始化检查完成。")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")

    @filter.regex(r"^签到$")
    async def handle_checkin(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        is_whitelisted = await self.is_group_whitelisted(group_id)
        if not is_whitelisted:
            return

        today = date.today()
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT last_checkin FROM users WHERE qq_id = %s", (user_id,))
                result = await cur.fetchone()

                if result is None:
                    await cur.execute("INSERT INTO users (qq_id, points, last_checkin) VALUES (%s, 10, %s)", (user_id, today))
                    yield event.plain_result(f"欢迎新朋友 {user_name}！首次签到成功，获得 10 积分！")
                    return

                last_checkin_date = result[0]
                if last_checkin_date == today:
                    yield event.plain_result(f"{user_name}，你今天已经签过到了哦，明天再来吧！")
                else:
                    await cur.execute("UPDATE users SET points = points + 10, last_checkin = %s WHERE qq_id = %s", (today, user_id))
                    yield event.plain_result(f"{user_name} 签到成功！获得 10 积分！")

    @filter.regex(r"^我的积分$")
    async def query_points(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        # 同样需要检查白名单
        is_whitelisted = await self.is_group_whitelisted(group_id)
        if not is_whitelisted:
            return # 白名单外的群不响应

        points = 0
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT points FROM users WHERE qq_id = %s", (user_id,))
                result = await cur.fetchone()
                if result:
                    points = result[0]

        yield event.plain_result(f"{user_name}，您当前的积分为：{points}")

    # V--- 我们将只重写 redeem_code 这个函数，以最终的智慧 ---V
    @filter.regex(r"^兑换兑换码$")
    async def redeem_code(self, event: AstrMessageEvent):
        # 确保事件来自 aiocqhttp 平台
        if not isinstance(event, AiocqhttpMessageEvent):
            yield event.plain_result("抱歉，此功能目前仅支持 QQ 平台。")
            return

        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        if not await self.is_group_whitelisted(group_id):
            return

        # 先检查，后操作
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                # ... (积分和兑换码检查逻辑保持不变) ...
                await cur.execute("SELECT points FROM users WHERE qq_id = %s", (user_id,))
                result = await cur.fetchone()
                current_points = result[0] if result else 0

                if current_points < 70:
                    yield event.plain_result(f"{user_name}，您的积分不足 70，无法兑换哦。")
                    return

                await cur.execute("SELECT id, code FROM codes LIMIT 1")
                code_record = await cur.fetchone()

                if not code_record:
                    yield event.plain_result("抱歉，兑换码仓库已空，请联系管理员补充。")
                    return

                code_id, the_code = code_record

        # --- 这，是我们最终的、基于真理的私聊方式 ---
        try:
            # 1. 直接从 event 中获取最可靠的“权杖”
            client = event.bot
            
            # 2. 以最直接的方式，下达最底层的命令
            await client.send_private_msg(
                user_id=user_id,
                message=f"您好，{user_name}！您成功兑换了兑换码，请查收：\n{the_code}"
            )
            logger.info(f"已通过 event.bot 成功向用户 {user_id} 发送私聊。")

            # 3. 私聊成功后，再执行数据库操作
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("UPDATE users SET points = points - 70 WHERE qq_id = %s", (user_id,))
                    await cur.execute("DELETE FROM codes WHERE id = %s", (code_id,))

            # 4. 在群里给予凯旋的宣告
            yield event.plain_result(f"恭喜 {user_name}！兑换成功，兑换码已通过私聊发送给您，请注意查收！")

        except Exception as e:
            logger.error(f"最终环节私聊发送失败，详细错误: {e}", exc_info=True)
            yield event.plain_result(f" @{user_name} 兑换成功！但机器人私聊时遇到未知错误，请联系管理员处理。")

    async def is_group_whitelisted(self, group_id: int) -> bool:
        if not group_id:
            return False
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT group_id FROM whitelisted_groups WHERE group_id = %s", (group_id,))
                return await cur.fetchone() is not None

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("添加白名单")
    async def add_whitelist(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("请在需要添加的群聊中执行此命令。")
            return

        is_whitelisted = await self.is_group_whitelisted(group_id)
        if is_whitelisted:
            yield event.plain_result(f"群 {group_id} 已经在本插件的白名单中了。")
            return

        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO whitelisted_groups (group_id) VALUES (%s)", (group_id,))

        yield event.plain_result(f"成功将群 {group_id} 添加到本插件的白名单。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("移除白名单")
    async def remove_whitelist(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("请在需要移除的群聊中执行此命令。")
            return

        is_whitelisted = await self.is_group_whitelisted(group_id)
        if not is_whitelisted:
            yield event.plain_result(f"群 {group_id} 不在本插件的白名单中。")
            return

        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM whitelisted_groups WHERE group_id = %s", (group_id,))

        yield event.plain_result(f"成功将群 {group_id} 从本插件的白名单中移除。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("添加兑换码")
    async def add_codes(self, event: AstrMessageEvent, codes: str):
        code_list = codes.split()
        if not code_list:
            yield event.plain_result("指令格式错误，请使用：/添加兑换码 [兑换码1] [兑换码2] ...")
            return

        added_count = 0
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                for code in code_list:
                    try:
                        # INSERT IGNORE 会在兑换码已存在时忽略错误，避免重复添加
                        await cur.execute("INSERT IGNORE INTO codes (code) VALUES (%s)", (code,))
                        if cur.rowcount > 0: # rowcount > 0 意味着插入成功
                            added_count += 1
                    except Exception as e:
                        logger.error(f"添加兑换码 {code} 时出错: {e}")
        
        yield event.plain_result(f"操作完成！成功添加 {added_count} 个新兑换码。有 {len(code_list) - added_count} 个兑换码已存在或添加失败。")
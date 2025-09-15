import asyncio
import aiomysql
import random
import httpx
from datetime import date
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.utils.session_waiter import session_waiter, SessionController
import astrbot.api.message_components as Comp
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

@register("checkin_plugin_pro", "Future-404", "一个为群组设计的、功能强大的激励与奖励系统。集成了高度可配置的每日签到（支持随机积分、暴击与首次奖励）和多商品“多宝阁”兑换商店。可通过指令管理白名单与兑换码库存。", "0.5.1")
class CheckinPluginV5(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.db_pool = None
        logger.info("多宝阁签到插件 V5.0.0 正在加载 (静态配置)...")
        asyncio.create_task(self.initialize_database())

    async def initialize_database(self):
        try:
            db_conf = self.config.get('database', {})
            self.db_pool = await aiomysql.create_pool(
                host=db_conf.get('host'), port=db_conf.get('port'), user=db_conf.get('user'),
                password=db_conf.get('password'), db=db_conf.get('db_name'), autocommit=True
            )
            logger.info("数据库连接池(配置驱动)创建成功。")
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("CREATE TABLE IF NOT EXISTS users (qq_id BIGINT PRIMARY KEY, points INT DEFAULT 0, last_checkin DATE);")
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS codes (
                            id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(255) NOT NULL,
                            item_type VARCHAR(255) NOT NULL, UNIQUE (code)
                        );
                        """)
                    await cur.execute("CREATE TABLE IF NOT EXISTS whitelisted_groups (group_id BIGINT PRIMARY KEY);")
            logger.info("数据库表初始化检查完成。")
        except Exception as e:
            logger.error(f"数据库初始化(配置驱动)失败: {e}", exc_info=True)

    # --- 辅助核心：静态商品栏搜索引擎 ---
    def _find_item_by_name(self, name_to_find: str):
        """根据商品名称，在固定的商品栏中查找商品。"""
        name_to_find = name_to_find.strip().lower()

        for i in range(1, 11):
            slot_config = self.config.get(f'item_slot_{i}', {})
            
            if not slot_config.get('enabled') or not slot_config.get('item_name'):
                continue

            item_name = slot_config.get('item_name', '').strip().lower()
            if item_name == name_to_find:
                return {
                    "internal_id": f'item_slot_{i}',
                    "item_name": slot_config.get('item_name'),
                    "item_cost": slot_config.get('item_cost')
                }
        
        return None

    # --- 核心用户功能 ---
    @filter.regex(r"^签到$")
    async def handle_checkin(self, event: AstrMessageEvent):
        user_id, user_name = event.get_sender_id(), event.get_sender_name()
        group_id = event.get_group_id()
        if not await self.is_group_whitelisted(group_id): return

        today = date.today()
        rewards_conf = self.config.get('rewards', {})
        
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT points, last_checkin FROM users WHERE qq_id = %s", (user_id,))
                result = await cur.fetchone()

                if result and result[1] == today:
                    yield event.plain_result(f"{user_name}，你今天已经签过到了哦，明天再来吧！")
                    return
                
                if result is None:
                    final_points = rewards_conf.get('first_checkin_points', 20)
                    reply_message = f"欢迎新朋友 {user_name}！首次签到获得特别奖励，获得 {final_points} 积分！"
                else:
                    base_points = random.randint(rewards_conf.get('min_points', 5), rewards_conf.get('max_points', 15))
                    final_points = base_points
                    is_crit = random.random() < rewards_conf.get('crit_chance', 0.05)
                    
                    reply_message = f"{user_name} 签到成功！\n获得了 {base_points} 点基础积分"
                    if is_crit:
                        final_points *= 2
                        reply_message += f"，触发幸运翻倍！\n最终获得 {final_points} 积分！"
                    else:
                        reply_message += "."
                
                if result is None:
                    await cur.execute("INSERT INTO users (qq_id, points, last_checkin) VALUES (%s, %s, %s)", (user_id, final_points, today))
                else:
                    await cur.execute("UPDATE users SET points = points + %s, last_checkin = %s WHERE qq_id = %s", (final_points, today, user_id))
                
                yield event.plain_result(reply_message)

    @filter.regex(r"^我的积分$")
    async def query_points(self, event: AstrMessageEvent):
        user_id, user_name = event.get_sender_id(), event.get_sender_name()
        if not await self.is_group_whitelisted(event.get_group_id()): return
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT points FROM users WHERE qq_id = %s", (user_id,))
                points = (await cur.fetchone() or [0])[0]
        yield event.plain_result(f"{user_name}，您好！\n通过每日签到，您已累计了 {points} 积分。")

    @filter.regex(r"^多宝阁$|^商品列表$")
    async def show_redeemable_items(self, event: AstrMessageEvent):
        if not await self.is_group_whitelisted(event.get_group_id()): return

        reply_message = "欢迎光临多宝阁！\n当前可兑换的商品有：\n" + "-" * 20
        found_any = False
        for i in range(1, 11):
            slot_config = self.config.get(f'item_slot_{i}', {})
            if slot_config.get('enabled') and slot_config.get('item_name'):
                found_any = True
                reply_message += f"\n- 【{slot_config.get('item_name')}】: {slot_config.get('item_cost')} 积分"
        
        if not found_any:
            yield event.plain_result("多宝阁今天不开张哦，管理员尚未上架任何商品。")
            return

        reply_message += "\n" + "-" * 20 + "\n使用指令 `兑换 [商品名称]` 即可兑换。"
        yield event.plain_result(reply_message)

    @filter.regex(r"^兑换\s*(.+)$")
    async def redeem_item(self, event: AstrMessageEvent, item_name_to_redeem: str):
        if not isinstance(event, AiocqhttpMessageEvent): return
        user_id, user_name = event.get_sender_id(), event.get_sender_name()
        if not await self.is_group_whitelisted(event.get_group_id()): return

        target_item = self._find_item_by_name(item_name_to_redeem.strip())

        if not target_item:
            yield event.plain_result(f"抱歉，多宝阁中没有名为“{item_name_to_redeem}”的商品。")
            return

        item_name = target_item.get('item_name')
        internal_id = target_item.get('internal_id')
        cost = target_item.get('item_cost', 99999)

        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT points FROM users WHERE qq_id = %s", (user_id,))
                current_points = (await cur.fetchone() or [0])[0]
                if current_points < cost:
                    yield event.plain_result(f"{user_name}，您的积分不足 {cost}，无法兑换【{item_name}】。")
                    return
                
                await cur.execute("SELECT id, code FROM codes WHERE item_type = %s LIMIT 1", (internal_id,))
                code_record = await cur.fetchone()
                if not code_record:
                    yield event.plain_result(f"抱歉，【{item_name}】的库存已空。")
                    return
                code_id, the_code = code_record

        try:
            client = event.bot
            await client.send_private_msg(user_id=user_id, message=f"您好！您成功使用 {cost} 积分兑换了【{item_name}】，请查收：\n{the_code}")
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("UPDATE users SET points = points - %s WHERE qq_id = %s", (cost, user_id))
                    await cur.execute("DELETE FROM codes WHERE id = %s", (code_id,))
            yield event.plain_result(f"恭喜 {user_name}！兑换【{item_name}】成功，秘宝已通过私聊发送！")
        except Exception as e:
            logger.error(f"兑换【{item_name}】私聊发送失败: {e}", exc_info=True)
            yield event.plain_result(f" @{user_name} 兑换成功！但私聊时发生未知错误，请联系管理员。")

    # --- 辅助与管理功能 ---
    async def is_group_whitelisted(self, group_id: int) -> bool:
        if not group_id: return False
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT group_id FROM whitelisted_groups WHERE group_id = %s", (group_id,))
                return await cur.fetchone() is not None

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("添加白名单")
    async def add_whitelist(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id: yield event.plain_result("请在群聊中执行。"); return
        if await self.is_group_whitelisted(group_id): yield event.plain_result("该群已在白名单中。"); return
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO whitelisted_groups (group_id) VALUES (%s)", (group_id,))
        yield event.plain_result(f"成功将群 {group_id} 添加到白名单。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("移除白名单")
    async def remove_whitelist(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id: yield event.plain_result("请在群聊中执行。"); return
        if not await self.is_group_whitelisted(group_id): yield event.plain_result("该群不在白名单中。"); return
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DELETE FROM whitelisted_groups WHERE group_id = %s", (group_id,))
        yield event.plain_result(f"成功将群 {group_id} 从白名单中移除。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("导入兑换码")
    async def import_codes_command(self, event: AstrMessageEvent, item_name: str = None):
        if not item_name:
            help_text = "指令格式：/导入兑换码 [商品名称]\n\n当前已启用的商品栏有：\n"
            found_any = False
            for i in range(1, 11):
                slot_config = self.config.get(f'item_slot_{i}', {})
                if slot_config.get('enabled') and slot_config.get('item_name'):
                    found_any = True
                    help_text += f"- {slot_config.get('item_name')}\n"
            
            if not found_any:
                help_text = "当前尚未配置任何已启用的商品。"
            yield event.plain_result(help_text)
            return

        target_item = self._find_item_by_name(item_name)
        
        if not target_item:
            yield event.plain_result(f"导入失败：未找到名为“{item_name}”的商品。")
            return
        
        item_name = target_item.get('item_name')
        internal_id = target_item.get('internal_id')
        try:
            yield event.plain_result(f"身份已确认。请在 60 秒内，为【{item_name}】发送 .txt 文件。")
            @session_waiter(timeout=60)
            async def file_waiter(controller: SessionController, event: AstrMessageEvent):
                file_url = ""
                for component in event.message_obj.message:
                    if isinstance(component, Comp.File): file_url = getattr(component, "url", ""); break
                if not file_url: await event.send(event.plain_result("收到的不是文件哦，请发送 .txt 文件。")); return
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(file_url, timeout=30); response.raise_for_status()
                    code_list = [line.strip() for line in response.text.splitlines() if line.strip()]
                    if not code_list:
                        await event.send(event.plain_result("文件内容为空或格式不正确。")); controller.stop(); return
                    added_count = 0
                    async with self.db_pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            for code in code_list:
                                try:
                                    await cur.execute("INSERT IGNORE INTO codes (code, item_type) VALUES (%s, %s)", (code, internal_id,))
                                    if cur.rowcount > 0: added_count += 1
                                except Exception as db_err: logger.error(f"导入兑换码 {code} 时数据库出错: {db_err}")
                    await event.send(event.plain_result(f"为【{item_name}】导入操作完成！\n读取到 {len(code_list)} 个兑换码，成功添加 {added_count} 个。"))
                except Exception as e:
                    logger.error(f"处理兑换码文件时发生未知错误: {e}", exc_info=True)
                    await event.send(event.plain_result("处理文件时发生内部错误，请联系管理员。"))
                finally:
                    controller.stop()
            await file_waiter(event)
        except TimeoutError: yield event.plain_result("超时未收到文件，导入操作已取消。")
        except Exception as e: logger.error(f"启动导入会话时出错: {e}", exc_info=True); yield event.plain_result("启动导入会话时发生未知错误。")
        finally: event.stop_event()
import asyncio
import aiomysql
import random
from datetime import date, datetime, timezone, timedelta
from functools import wraps
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

def require_whitelisted_group(func):
    """装饰器：确保指令在白名单群组中执行"""
    @wraps(func)
    async def wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        group_id = event.get_group_id()
        if not group_id or not await self.is_group_whitelisted(group_id):
            return
        
        # 修复：被装饰的函数是异步生成器，我们必须遍历它并产生结果
        async for res in func(self, event, *args, **kwargs):
            yield res
    return wrapper

@register("checkin_plugin_pro", "Future-404", "一个为群组设计的、功能强大的激励与奖励系统。集成了高度可配置的每日签到和多商品“GlowMind积分商城”兑换商店。", "6.0.0")
class CheckinPluginPro(Star):
    # --- 常量定义 ---
    TABLE_USERS = "users"
    TABLE_CODES = "codes"
    TABLE_WHITELIST = "whitelisted_groups"
    MAX_ITEM_SLOTS = 10

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.db_pool = None
        logger.info("GlowMind积分商城签到插件 V6.0.0 正在加载 (重构版)...")
        asyncio.create_task(self.initialize_database())

    async def initialize_database(self):
        try:
            db_conf = self.config.get('database', {})
            self.db_pool = await aiomysql.create_pool(
                host=db_conf.get('host'), port=db_conf.get('port'), user=db_conf.get('user'),
                password=db_conf.get('password'), db=db_conf.get('db_name'), autocommit=True
            )
            logger.info("数据库连接池(配置驱动)创建成功。")
            
            await self._execute_query(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_USERS} (
                    qq_id BIGINT PRIMARY KEY, points INT DEFAULT 0, last_checkin DATE
                );
                """)
            await self._execute_query(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_CODES} (
                    id INT AUTO_INCREMENT PRIMARY KEY, code VARCHAR(255) NOT NULL,
                    item_type VARCHAR(255) NOT NULL,
                    UNIQUE (code)
                );
                """)
            await self._execute_query(f"CREATE TABLE IF NOT EXISTS {self.TABLE_WHITELIST} (group_id BIGINT PRIMARY KEY);")

            logger.info("数据库表初始化检查完成。")
        except Exception as e:
            logger.error(f"数据库初始化(配置驱动)失败: {e}", exc_info=True)

    # --- 数据库辅助核心 ---
    async def _execute_query(self, query: str, args: tuple = None, fetch: str = None):
        """
        统一的数据库执行器。
        :param query: SQL 查询语句
        :param args: 查询参数
        :param fetch: 'one' (fetchone), 'all' (fetchall), None (不 fetch, 返回 rowcount)
        """
        if not self.db_pool:
            logger.error("数据库连接池未初始化，无法执行查询。")
            return None
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, args)
                if fetch == 'one':
                    return await cur.fetchone()
                elif fetch == 'all':
                    return await cur.fetchall()
                return cur.rowcount

    # --- 辅助核心：静态商品栏搜索引擎 ---
    def _find_item_by_name(self, name_to_find: str):
        name_to_find = name_to_find.strip().lower()
        for i in range(1, self.MAX_ITEM_SLOTS + 1):
            slot_config = self.config.get(f'item_slot_{i}', {})
            if slot_config.get('enabled') and slot_config.get('item_name', '').strip().lower() == name_to_find:
                return {
                    "internal_id": f'item_slot_{i}',
                    "item_name": slot_config.get('item_name'),
                    "item_cost": slot_config.get('item_cost')
                }
        return None

    # --- 核心用户功能 ---
    @filter.regex(r"^签到$")
    @require_whitelisted_group
    async def handle_checkin(self, event: AstrMessageEvent):
        user_id, user_name = event.get_sender_id(), event.get_sender_name()
        
        general_conf = self.config.get('general_settings', {})
        offset_hours = general_conf.get('timezone_offset_hours', 8.0)
        utc_now = datetime.now(timezone.utc)
        our_timezone = timezone(timedelta(hours=offset_hours))
        our_now = utc_now.astimezone(our_timezone)
        today = our_now.date()

        rewards_conf = self.config.get('rewards', {})
        
        query = f"SELECT points, last_checkin FROM {self.TABLE_USERS} WHERE qq_id = %s"
        result = await self._execute_query(query, (user_id,), fetch='one')

        if result and result[1] == today:
            yield event.plain_result(f"{user_name}，你今天已经签过到了哦，别想再白嫖，明天再来吧！")
            return
        
        if result is None:
            final_points = rewards_conf.get('first_checkin_points', 20)
            reply_message = f"欢迎新朋友 {user_name}！首次签到获得特别新人大礼，你总共获得了 {final_points} 积分！"
            insert_query = f"INSERT INTO {self.TABLE_USERS} (qq_id, points, last_checkin) VALUES (%s, %s, %s)"
            await self._execute_query(insert_query, (user_id, final_points, today))
        else:
            base_points = random.randint(rewards_conf.get('min_points', 5), rewards_conf.get('max_points', 15))
            final_points = base_points
            is_crit = random.random() < rewards_conf.get('crit_chance', 0.05)
            
            reply_message = f"{user_name} 😘签到成功！\n获得了 {base_points} 点积分"
            if is_crit:
                final_points *= 2
                reply_message += f"，🤑666！触发幸运翻倍！\n最终获得 {final_points} 积分！"
            else:
                reply_message += "."
            
            update_query = f"UPDATE {self.TABLE_USERS} SET points = points + %s, last_checkin = %s WHERE qq_id = %s"
            await self._execute_query(update_query, (final_points, today, user_id))
        
        yield event.plain_result(reply_message)

    @filter.regex(r"^积分$")
    @require_whitelisted_group
    async def query_points(self, event: AstrMessageEvent):
        user_id, user_name = event.get_sender_id(), event.get_sender_name()
        query = f"SELECT points FROM {self.TABLE_USERS} WHERE qq_id = %s"
        result = await self._execute_query(query, (user_id,), fetch='one')
        points = (result or [0])[0]
        yield event.plain_result(f"{user_name}，您好！\n通过每日签到，您已累计了 {points} 积分。")

    async def _get_all_inventory_counts(self):
        inventory_counts = {}
        query = f"SELECT item_type, COUNT(*) FROM {self.TABLE_CODES} GROUP BY item_type"
        results = await self._execute_query(query, fetch='all')
        if results:
            inventory_counts = {row[0]: row[1] for row in results}
        return inventory_counts

    @filter.regex(r"^(商店|商城)$")
    @require_whitelisted_group
    async def show_redeemable_items(self, event: AstrMessageEvent):
        inventory_counts = await self._get_all_inventory_counts()
        reply_text = "欢迎光临1781积分商城！\n当前可兑换的秘宝有：\n"
        found_any = False

        for i in range(1, self.MAX_ITEM_SLOTS + 1):
            slot_config = self.config.get(f'item_slot_{i}', {})
            
            if slot_config.get('enabled') and slot_config.get('item_name'):
                found_any = True
                item_name = slot_config.get('item_name')
                item_cost = slot_config.get('item_cost', '未知')
                internal_id = f'item_slot_{i}'
                stock = inventory_counts.get(internal_id, 0)

                reply_text += f"\n💎 **{item_name}**\n"
                reply_text += f"   - 价格: {item_cost} 积分\n"
                reply_text += f"   -库存: {stock} 件"

        if not found_any:
            reply_text = "1781积分商城今日正在盘点，暂无商品上架，敬请期待！"
        yield event.plain_result(reply_text)

    @filter.regex(r"^兑换\s*.+")
    @require_whitelisted_group
    async def redeem_item(self, event: AstrMessageEvent):
        full_message = event.message_str.strip()
        item_name_to_redeem = full_message[2:].strip()

        if not item_name_to_redeem:
            yield event.plain_result("请输入您想兑换的商品名称。")
            return

        if not isinstance(event, AiocqhttpMessageEvent):
            return
        user_id, user_name = event.get_sender_id(), event.get_sender_name()

        target_item = self._find_item_by_name(item_name_to_redeem)
        if not target_item:
            yield event.plain_result(f"抱歉，1781积分商城中没有名为“{item_name_to_redeem}”的商品。")
            return

        item_name = target_item.get('item_name')
        internal_id = target_item.get('internal_id')
        cost = target_item.get('item_cost', 99999)
        the_code = "" # 初始化

        # --- 事务开始 ---
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await conn.begin()

                    # 1. 锁定并检查用户积分
                    await cur.execute(f"SELECT points FROM {self.TABLE_USERS} WHERE qq_id = %s FOR UPDATE", (user_id,))
                    current_points_result = await cur.fetchone()
                    
                    current_points = (current_points_result or [0])[0]

                    if current_points < cost:
                        yield event.plain_result(f"{user_name}，您的积分不足 {cost}，无法兑换【{item_name}】。")
                        await conn.rollback()
                        return

                    # 2. 锁定并获取一个兑换码
                    await cur.execute(f"SELECT id, code FROM {self.TABLE_CODES} WHERE item_type = %s LIMIT 1 FOR UPDATE", (internal_id,))
                    code_record = await cur.fetchone()

                    if not code_record:
                        yield event.plain_result(f"抱歉，【{item_name}】的库存已空。")
                        await conn.rollback()
                        return
                    
                    code_id, the_code = code_record

                    # 3. 扣除积分
                    await cur.execute(f"UPDATE {self.TABLE_USERS} SET points = points - %s WHERE qq_id = %s", (cost, user_id))
                    
                    # 4. 删除已使用的兑换码
                    await cur.execute(f"DELETE FROM {self.TABLE_CODES} WHERE id = %s", (code_id,))

                    # 5. 提交事务
                    await conn.commit()

                except Exception as e:
                    await conn.rollback()
                    logger.error(f"用户 {user_id} 兑换【{item_name}】时发生数据库事务错误: {e}", exc_info=True)
                    yield event.plain_result(f"兑换失败，发生意外的数据库错误，请联系管理员。")
                    return
        # --- 事务结束 ---

        # 事务成功后，发送私信
        try:
            client = event.bot
            await client.send_private_msg(user_id=user_id, message=f"您好！您成功使用 {cost} 积分兑换了【{item_name}】，请查收：\n{the_code}")
            yield event.plain_result(f"恭喜 {user_name}！兑换【{item_name}】成功，秘宝已通过私聊发送！")
        except Exception as e:
            logger.error(f"兑换【{item_name}】私聊发送失败 (但积分和库存已扣除): {e}", exc_info=True)
            yield event.plain_result(f"@{user_name} 兑换成功！但私聊发送时发生未知错误，请联系管理员，如果你事先没有加bot为好友，就受着")

    # --- 辅助与管理功能 ---
    async def is_group_whitelisted(self, group_id: int) -> bool:
        if not group_id: return False
        query = f"SELECT group_id FROM {self.TABLE_WHITELIST} WHERE group_id = %s"
        result = await self._execute_query(query, (group_id,), fetch='one')
        return result is not None

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("添加白名单")
    async def add_whitelist(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id: yield event.plain_result("请在群聊中执行。"); return
        if await self.is_group_whitelisted(group_id): yield event.plain_result("该群已在白名单中。"); return
        
        query = f"INSERT INTO {self.TABLE_WHITELIST} (group_id) VALUES (%s)"
        await self._execute_query(query, (group_id,))
        yield event.plain_result(f"成功将群 {group_id} 添加到白名单。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("移除白名单")
    async def remove_whitelist(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if not group_id: yield event.plain_result("请在群聊中执行。"); return
        if not await self.is_group_whitelisted(group_id): yield event.plain_result("该群不在白名单中。"); return
        
        query = f"DELETE FROM {self.TABLE_WHITELIST} WHERE group_id = %s"
        await self._execute_query(query, (group_id,))
        yield event.plain_result(f"成功将群 {group_id} 从白名单中移除。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("导入兑换码")
    async def import_codes_command(self, event: AstrMessageEvent, item_name: str):
        full_message = event.message_str
        first_newline_index = full_message.find('\n')

        if first_newline_index == -1:
            yield event.plain_result("请在指令的下一行，提供需要导入的兑换码。")
            return
            
        codes_text = full_message[first_newline_index:].strip()
        
        target_item = self._find_item_by_name(item_name)
        if not target_item:
            yield event.plain_result(f"导入失败：未找到名为“{item_name}”的商品。")
            return
        
        internal_id = target_item.get('internal_id')
        code_list = [line.strip() for line in codes_text.splitlines() if line.strip()]

        if not code_list:
            yield event.plain_result("未在指令中找到有效的兑换码。")
            return

        added_count = 0
        for code in code_list:
            try:
                query = f"INSERT IGNORE INTO {self.TABLE_CODES} (code, item_type) VALUES (%s, %s)"
                rows_affected = await self._execute_query(query, (code, internal_id))
                if rows_affected > 0:
                    added_count += 1
            except Exception as db_err:
                logger.error(f"导入兑换码 {code} 时数据库出错: {db_err}")

        yield event.plain_result(
            f"为【{item_name}】导入操作完成！\n"
            f"从指令中读取到 {len(code_list)} 个兑换码，成功添加 {added_count} 个。"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("调整积分", alias={'奖励积分'})
    async def adjust_points_manual(self, event: AstrMessageEvent, user_id: int, points_delta: int):
        original_points = 0
        new_points = 0
        
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await conn.begin()
                    
                    await cur.execute(f"SELECT points FROM {self.TABLE_USERS} WHERE qq_id = %s FOR UPDATE", (user_id,))
                    result = await cur.fetchone()
                    
                    if result is None:
                        original_points = 0
                        new_points = max(0, original_points + points_delta)
                        if new_points > 0:
                           await cur.execute(f"INSERT INTO {self.TABLE_USERS} (qq_id, points, last_checkin) VALUES (%s, %s, NULL)", (user_id, new_points))
                        else:
                           yield event.plain_result(f"操作失败：用户 {user_id} 不存在，且操作结果为0或负积分。")
                           await conn.rollback()
                           return
                    else:
                        original_points = result[0]
                        new_points = max(0, original_points + points_delta)
                        await cur.execute(f"UPDATE {self.TABLE_USERS} SET points = %s WHERE qq_id = %s", (new_points, user_id))
                    
                    await conn.commit()
                except Exception as e:
                    await conn.rollback()
                    logger.error(f"管理员调整用户 {user_id} 积分时发生数据库事务错误: {e}", exc_info=True)
                    yield event.plain_result(f"调整积分失败，发生意外的数据库错误。")
                    return

        action_text = "奖励" if points_delta >= 0 else "扣除"
        abs_delta = abs(points_delta)
        
        yield event.plain_result(
            f"操作成功！\n"
            f"已为用户 {user_id} {action_text} {abs_delta} 积分。\n"
            f"其积分已从 {original_points} 变为 {new_points}。"
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_group_member_decrease(self, event: AstrMessageEvent):
        if not isinstance(event, AiocqhttpMessageEvent):
            return

        raw_message = getattr(event.message_obj, "raw_message", None)

        if (
            not isinstance(raw_message, dict)
            or raw_message.get("post_type") != "notice"
            or raw_message.get("notice_type") != "group_decrease"
        ):
            return

        group_id = raw_message.get("group_id")
        user_id = raw_message.get("user_id")
        
        if not await self.is_group_whitelisted(group_id):
            return

        try:
            rows_deleted = await self._execute_query(f"DELETE FROM {self.TABLE_USERS} WHERE qq_id = %s", (user_id,))
            
            if rows_deleted > 0:
                logger.info(f"用户 {user_id} 的数据已从数据库中清除 (群: {group_id})。")
                
                client = event.bot
                operator_id = raw_message.get("operator_id")
                sub_type = raw_message.get("sub_type")

                user_info = await client.get_stranger_info(user_id=user_id, no_cache=True)
                user_nickname = user_info.get("nickname", str(user_id))

                announcement = ""
                if sub_type == "leave":
                    announcement = f"用户 {user_nickname} ({user_id}) 已主动退出本群。\n其在本插件中的所有积分数据已被同步清除。"
                elif sub_type == "kick":
                    operator_info = await client.get_group_member_info(group_id=group_id, user_id=operator_id)
                    operator_nickname = operator_info.get("card") or operator_info.get("nickname", str(operator_id))
                    announcement = f"用户 {user_nickname} ({user_id}) 已被管理员 {operator_nickname} 移出本群。\n其在本插件中的所有积分数据已被同步清除。"
                
                if announcement:
                    yield event.plain_result(announcement)
            else:
                logger.info(f"用户 {user_id} 退出了群 {group_id}，但其在数据库中无数据，无需清理。")

        except Exception as e:
            logger.error(f"处理用户 {user_id} 退群事件时发生数据库错误: {e}", exc_info=True)
            
        event.stop_event()

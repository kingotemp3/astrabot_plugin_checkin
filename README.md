# 多宝阁签到插件 V5 (Check-in Plugin Pro)

## 📖 简介

这是一个为 AstrBot 设计的、基于固定商品栏的高度可配置化签到插件。它采用与 AstrBot 配置界面完美兼容的“静态插槽”架构，旨在提供一个稳定、直观、易于管理的群组激励方案。

**当前版本:** 0.5.1
**作者:** Future-404

---

## 🔧 安装与配置

### **第一步：处理依赖项 (Dependencies)**

本插件的运行，依赖于两个核心的 Python 库：

1.  `aiomysql`: 用于与 MySQL 数据库进行异步通信，是所有数据存储（用户积分、兑换码库存等）的基础。
2.  `httpx`: 用于在“批量导入”功能中，下载管理员发送的 `.txt` 文件。

请确保您的环境中已安装这些库。最简单的方法，是检查并确保插件目录下的 `requirements.txt` 文件中包含以下两行：

```
aiomysql
httpx
```

然后通过 `pip install -r requirements.txt` 来安装它们。

### **第二步：配置数据库 (Database - 核心中的核心)**

本插件需要一个**独立的 MySQL 数据库**来存储所有数据。您需要预先准备好一个可用的 MySQL 服务，并完成以下操作：

1.  **创建数据库**: 在您的 MySQL 中创建一个新的数据库。例如，可以命名为 `checkin_plugin_db`。
2.  **创建用户 (推荐)**: 为了安全，推荐您为这个数据库创建一个专用的用户，并授予其对该数据库的完全权限。例如，创建一个名为 `Future404` 的用户。
3.  **获取连接信息**: 您需要准备好以下五项信息：
    - **主机地址 (host)**: 数据库服务器的 IP 地址或域名 (如 `127.0.0.1` 或 `mysql`)。
    - **端口 (port)**: 数据库的端口 (默认为 `3306`)。
    - **用户名 (user)**: 您创建的专用用户名。
    - **密码 (password)**: 该用户的密码。
    - **数据库名 (db_name)**: 您创建的数据库的名称。

4.  **填入 AstrBot 配置**: 将上述五项信息，填入 AstrBot 的主配置文件 (`config/default.yaml` 或您的自定义配置) 中，如下方示例所示。插件启动时，会自动读取这些信息来连接数据库，并自动创建所需的数据表 (`users`, `codes`, `whitelisted_groups`)。

### **第三步：完成插件配置**

在 AstrBot 的主配置文件中，找到或创建 `checkin_plugin_pro` 区域，并参照以下示例完成所有配置：

**配置示例 (`config/default.yaml`):**
```yaml
# ... (其他 AstrBot 配置) ...

# 签到插件 V5 的配置区域
checkin_plugin_pro:
  # 【必填】数据库连接信息
  database:
    host: "mysql"
    port: 3306
    user: "Future404"
    password: "your_password_here"
    db_name: "checkin_plugin_db"

  # 【可选】签到奖励数值 (若不填则使用默认值)
  rewards:
    first_checkin_points: 20
    min_points: 5
    max_points: 15
    crit_chance: 0.05

  # 【可选】固定的商品栏位 (根据需要启用和配置)
  item_slot_1:
    enabled: true
    item_name: "灵石"
    item_cost: 75
  item_slot_2:
    enabled: true
    item_name: "月卡"
    item_cost: 300
  item_slot_3:
    enabled: false
    item_name: "改名卡"
    item_cost: 100
```

### **第四步：设**置管理员

请确保您的 QQ 号已添加在 AstrBot 主配置文件的 `admins` 列表中，以便您能使用管理员指令。

---

## 🚀 使用指南

### 对于群成员

- **签到**: `签到`
- **查询积分**: `我的积分`
- **浏览商品**: `多宝阁` 或 `商品列表`
- **兑换商品**: `兑换 [商品名称]` (示例: `兑换 灵石`)

### 对于管理员

> **注意**: 指令需要以 `/` 开头。

- **授权群聊**: `/添加白名单`
- **取消授权**: `/移除白名单`
- **批量导入**: `/导入兑换码 [商品名称]` (然后按提示发送 `.txt` 文件)
- **获取导入帮助**: `/导入兑换码`

---

*This plugin was proudly crafted by Future-404 & Gemini.*添加白名单`
- **取消授权**: `/移除白名单`
- **批量导入**: `/导入兑换码 [商品名称]` (然后按提示发送 `.txt` 文件)
- **获取导入帮助**: `/导入兑换码`

---

*This plugin was proudly crafted by Future-404.*
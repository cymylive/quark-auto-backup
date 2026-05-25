<img width="1127" height="851" alt="image" src="https://github.com/user-attachments/assets/5266316d-0d80-4a32-8681-753cb2bfb9a7" /># 夸克自动备份

定时将本地文件夹自动备份到夸克网盘。支持 **GUI 桌面端** 和 **CLI 命令行** 两种模式。

## 运行截图
<img width="1127" height="851" alt="image" src="https://github.com/user-attachments/assets/c27e2fa8-4762-4ec1-91a0-c73083a4ccca" />
<img width="1127" height="851" alt="image" src="https://github.com/user-attachments/assets/963ab1a7-44b8-4617-b4c3-4b40c24fe2d6" />
<img width="1127" height="851" alt="image" src="https://github.com/user-attachments/assets/feb8e9ac-7f78-45d5-92e5-ce2770d0b19f" />




## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动图形界面
python main.py gui

# 3. 点击「登录」扫码登录夸克网盘

# 4. 在「备份源」页面添加要备份的目录

# 5. 切换到「备份执行」页面，点击「开始备份」
```

## 命令

| 命令 | 说明 |
|------|------|
| `python main.py gui` | 启动图形界面（推荐） |
| `python main.py backup` | 执行一次备份 |
| `python main.py login` | 登录夸克网盘 |
| `python main.py status` | 查看存储状态和配置 |
| `python main.py watch` | 启动终端定时备份 |

## 功能特性

### 备份源管理
- **可视化编辑**：添加/编辑/删除备份源，每个源独立配置
- **路径保留**：夸克远程目录自动创建，保持本地目录结构
- **排除模式**：支持 glob 通配符排除文件或目录
- **增量备份**：基于 MD5 哈希对比，只上传新增/变更的文件
- **备份后删除**：每个源独立可选，上传成功后自动清理本地文件

### 登录认证
- **二维码扫码**：登录二维码直接显示在 GUI 窗口中
- **持久化登录**：一次扫码，Cookie 自动保存，后续启动免重新扫码
- **自动续期**：Cookie 过期后自动用 service_ticket 静默刷新

### 定时调度
- **启用/禁用开关**：随时开启或关闭自动备份
- **可视化配置**：频率下拉框 + 时间选择器，所见即所得
- **自定义间隔**：支持 `每 N 分钟/小时/秒` 灵活配置
- **快捷预设**：一键选择常用调度

### 系统托盘
- **最小化隐藏**：点击最小化后窗口自动隐藏到系统托盘
- **托盘菜单**：右键可显示主窗口或退出程序
- **后台运行**：定时备份在后台持续执行

### 备份记录
- **自动记录**：每次成功备份写入 Excel 文件，记录文件名、时间、远程路径
- **表格样式**：蓝底白字表头、隔行变色、自动筛选功能
- **自定义路径**：支持浏览选择 Excel 文件保存位置

### 上传引擎
- **多线程并发**：支持多文件同时上传
- **单分片上传**：统一使用单分片策略，避免多分片兼容性问题
- **自动重试**：上传失败自动重试

## 调度语法

| 表达式 | 说明 |
|--------|------|
| `每天 02:00` | 每天凌晨2点 |
| `每小时` | 每小时执行 |
| `每 30 分钟` | 每30分钟执行 |
| `每 2 小时` | 每2小时执行 |
| `每 90 分钟` | 每90分钟执行 |
| `每 10 秒` | 每10秒执行 |
| `每周一 03:00` | 每周一凌晨3点 |

## 配置

编辑 `config.yaml`:

```yaml
sources:
  - local: "C:\\Users\\xxx\\Documents"     # 本地路径
    remote: "/自动备份/Documents"           # 夸克远程目录
    exclude: ["*.tmp", "*.log", ".git/*"]  # 排除模式（glob）
    include: []                            # 包含模式（空=全部）
    recursive: true                        # 递归子目录
    delete_after_backup: false             # 备份后自动删除原文件

schedule: "每天 02:00"                     # 调度计划
schedule_enabled: true                     # 启用定时备份
backup_log_path: "data.xlsx"               # 备份记录文件路径
```

## CHANGELOG

详见 [CHANGELOG.md](CHANGELOG.md)

## 许可证

MIT License

# 夸克自动备份

定时将本地文件夹自动备份到夸克网盘。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 修改配置 config.yaml（指定要备份的目录）

# 3. 首次运行（会弹出二维码登录）
python main.py login

# 4. 执行一次备份
python main.py backup

# 5. 启动定时监控备份
python main.py watch
```

## 命令

| 命令 | 说明 |
|------|------|
| `python main.py login` | 登录夸克网盘（二维码扫描） |
| `python main.py backup` | 执行一次备份 |
| `python main.py status` | 查看存储状态和配置 |
| `python main.py watch` | 启动定时备份 |

## 配置

编辑 `config.yaml`:

```yaml
sources:
  - local: "C:\\Users\\xxx\\Documents"   # 本地路径
    remote: "/自动备份/Documents"         # 夸克远程目录
    exclude: ["*.tmp", "*.log", ".git/*"] # 排除模式
    include: []                           # 包含模式（空=全部）
    recursive: true                       # 递归子目录

schedule: "每天 02:00"                    # 定时计划
```

## 调度语法

- `每天 02:00` - 每天凌晨2点
- `每小时` - 每小时执行
- `每 30 分钟` - 每30分钟执行
- `每周一 03:00` - 每周一凌晨3点

## 增量备份

基于文件 MD5 哈希，只上传新增/变更的文件，已存在且未变更的文件会自动跳过。

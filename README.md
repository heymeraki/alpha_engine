# Alpha 因子自动挖掘工具（CLI）

面向 WorldQuant BRAIN 平台的 Alpha 因子命令行工具：自动生成表达式 → 批量回测 → 逐层筛选 → 质量检查 → 提交。

## 项目结构

```
cli.py             # CLI 统一入口
config.py          # 区域 / 延迟 / 股票池等常量
machine_lib*.py    # 会话登录、批量回测、剪枝、结果查询
field_provider.py  # 字段来源（datafields / 推荐器 / 已有因子）
mcp_server/        # MCP Server
tasks/             # 各命令对应的任务模块
template/          # 自定义模板（每个文件一个模板）
recommenders/      # 外部字段推荐器
groups.txt         # 各区域/延迟/股票池的分组字段配置（可选）
records/ logs/ alphas/   # 运行记录、日志与缓存（自动生成）
user_info.txt      # WQ 账号密码（需自行填写）
```

## 特性

- 四阶段流水线：一阶算子 → 分组算子 → `trade_when` 条件 → 模板组合
- 字段自动预处理：`winsorize(ts_backfill(field, 120), std=4)`，自动填充缺失值 + 去极值
- 批量回测，自动轮询状态、失败重试、限流退避
- 同字段剪枝 + 本地去重，支持断点续跑
- 自相关 / PROD 相关性检查，通过的因子自动标记颜色
- 内置 MCP Server，可接入 AI 客户端自动完成研究流程

## 安装与配置

要求 Python 3.9+：

```bash
pip install -r requirements.txt
```

在项目根目录创建 `user_info.txt`（注意单引号和空格格式）：

```
username: 'your_email@example.com'
password: 'your_password'
```

## 快速开始

以 `analyst34` 数据集、美国市场、delay 1、TOP3000 为例：

```bash
# 依次跑四个阶段（参数保持一致，tag 自动衔接）
python cli.py dig 1step --dataset-id analyst34 --region USA --delay 1 --universe TOP3000 --n-jobs 8
python cli.py dig 2step --dataset-id analyst34 --region USA --delay 1 --universe TOP3000 --n-jobs 8
python cli.py dig 3step --dataset-id analyst34 --region USA --delay 1 --universe TOP3000 --n-jobs 8
python cli.py dig 4step --dataset-id analyst34 --region USA --delay 1 --universe TOP3000 --n-jobs 8

# 质量检查（自相关 / PROD 相关性，通过的进入可提交清单）
python cli.py check --mode USER

# 查看某阶段结果并导出 CSV
python cli.py results --tag USA_1_EQUITY_TOP3000_analyst34_step1 --export step1.csv

# 提交指定 Alpha
python cli.py submit --alpha-id <ALPHA_ID>
```

各挖掘阶段会持续循环运行、异常自动重试，可 `Ctrl+C` 安全退出。进度实时保存在 `records/`，重跑自动跳过已回测的表达式。

## 命令一览

| 命令 | 作用 |
|------|------|
| `dig 1step~4step` | 四阶段因子挖掘 |
| `template` | 按 `template/` 下自定义模板批量生成因子 |
| `check` | 自相关 / PROD 相关性检查，标记可提交因子 |
| `submit --alpha-id` | 提交指定 Alpha |
| `results --tag` | 按 tag 查询回测结果，可导出 CSV |

所有参数及默认值见 `python cli.py <命令> --help`。

## MCP 接入

内置 MCP Server，接入 Claude Desktop / Cursor / Codex 等客户端后，AI 可调用完整研究流程（发现字段与算子、查询因子、有界批量回测、相关性检查、改名打标、提交、查绩效）：

```bash
python -m mcp_server   # stdio 传输，由 MCP 客户端以子进程方式拉起
```

AI 的写操作强制走项目内置的批量模拟器：单批 ≤8、自动去重、按 tag 归档；`run_simulations` 为有界调用，单次最多 100 个表达式，跑完即返回。



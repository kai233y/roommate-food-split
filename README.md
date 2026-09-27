# 合租食材账本

适用于 1–3 位室友共用食材的 Flet 桌面程序。支持室友、分批入库、按人数均分消耗、报废、库存、流水筛选，以及按周或按月结算。所有数据保存在本机 SQLite 文件中。

## 运行

需要 Python 3.10+；支持 Windows 10/11 和 macOS 12+。在本目录打开终端：

```bash
python -m venv .venv
# macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

如果本目录已有可用的虚拟环境，直接激活并运行 `python main.py`。当前本地 `.venv` 已安装 Flet 1.0.1。

macOS 上的 Python.org Python 若未配置系统 CA 证书，本程序会使用 `certifi` 的标准 CA 证书包完成 Flet 首次下载客户端时的 HTTPS 验证；首次启动需要能访问 Flet 的 GitHub Release 下载地址。
若 PyCharm 启动时没有继承 `/usr/bin`，程序会补齐该系统路径，以便 Flet 调用 macOS 的 `open` 命令。

macOS 开发运行时数据库默认在 `data/pantry.db`；Windows 运行时默认在 `%LOCALAPPDATA%\RoommatePantry\pantry.db`，因此打包程序更新后数据仍保留。首次启动自动创建。可用环境变量 `PANTRY_DB` 指向其他路径。备份时关闭程序并复制这个文件。

## 使用顺序

1. 在「室友」页添加最多 3 人。
2. 在「入库」页录入食材、计量方式、单价、数量、购买人、购买日期和保质期天数。到期日由购买日期加保质期计算。
3. 在「库存」页按批次选择「消耗」或「报废」。消耗时勾选 1–3 人；金额按人数均分，分到不足 1 分时按室友 ID 顺序分配余分。
4. 在「总览」查看各人账目、食用金额柱状图、库存价值变化图和结算日提醒；在「流水」按日期、食材名、相关人员筛选。
5. 在「结算」页选择按周或按月。到期时总览会提醒；结算页实时列出建议转账。确认结束本期后，结算单会保存到历史记录，并立即开启新周期。

## 账目规则

- 食材按每次购买的批次管理，同名食材可以有不同单价、购买人和到期日。
- 购买金额计入购买人累计购买；批次剩余价值为其「未消耗贡献」，消耗和报废都会扣减。
- 「贡献−消耗」为累计购买减个人食用，包含尚未食用的库存价值。
- 「待结算净额」仅看已食用部分：自己购买且被食用的金额减自己的食用金额。正数应收、负数应付；所有人净额合计为零。未食用库存暂不参与结算。
- 周期结算按食用流水计算“消耗人欠购买人”的金额，先抵消室友之间的应收应付，再列出实际需要转账的最少清单。购买当天未吃的食材不会提前分账；跨周期食用时在食用的那个周期结算。
- 结算提醒只在程序打开时显示，不会在程序关闭后发送系统通知。结束周期会保存结算单，但不会自动执行真实转账。
- 报废默认仅减库存和未消耗贡献，不计入食用分摊；勾选「由购买人承担」时单列其报废金额，仍不向其他室友收费。
- 金额以整数分存储；数量以 0.001 kg 或 1 个为最小单位。最后一次扣减会带走该批次剩余的全部价值，避免四舍五入残留。

例如 A 买入 1 kg、50 元牛肉，B 与 C 消耗 0.5 kg：B/C 各承担 12.50 元，A 的未消耗贡献变为 25 元，A 的待结算应收为 25 元。

## 验证

```bash
python -m unittest discover -p 'test_*.py' -v
```

测试覆盖示例分摊、库存不足、报废承担选项、分位舍入、周期净额抵消、跨周期库存，以及提交后关闭弹窗。

## Windows 免 Python 运行包

在 Windows 10/11（64 位）电脑上安装 Python 3.12 后，在本目录的 PowerShell 中运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt 'pyinstaller>=6,<7'
.\.venv\Scripts\python.exe -m unittest discover -p 'test_*.py' -v
.\.venv\Scripts\flet.exe pack main.py --name RoommatePantry --yes
```

生成的 `dist/RoommatePantry.exe` 可复制到其他 Windows 电脑运行，目标电脑无需安装 Python。

也可以把本目录内容放在 GitHub 仓库根目录，再在 Actions 页手动运行 **Build Windows executable** 工作流，下载 `RoommatePantry-Windows` 构建产物。macOS 无法直接构建 Windows exe，因此需要 Windows 机器或 Windows CI 运行器。

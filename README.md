# dsh-doctor

[![CI](https://github.com/hansei996/dsh-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/hansei996/dsh-doctor/actions/workflows/ci.yml)

给 [DeepSeek Harness](https://github.com/) 的安装做体检：体积分布、可回收空间、凭据状态、插件与扩展、磁盘余量。

一个命令看清 `~/.dsh` 到底把空间花在哪，并且能安全清掉其中"确定可以删"的部分。

## 为什么

DSH 运行时目录会长得很快：`profiles/` 和 `dsh-runtimes/` 动辄几百 MB，`attachments/` 里全是历史截图，`backups/` 每次更新都留一份。本地实测：

```
$ dsh-doctor --top 3
dsh-doctor · ~/.dsh
健康分 100/100  评级 A  可回收 3.4 MB
体积分布：profiles 343.2 MB · dsh-runtimes 300.1 MB · extensions 12.4 MB · plugins 11.1 MB

空间 Top 3（按单文件大小）
  115.8 MB  dsh-runtimes/dsh-primary-runtime/dependencies/node/bin/node
  21.5 MB   dsh-runtimes/dsh-primary-runtime/dependencies/python/lib/python3.12/site-packages/numpy/.dylibs/libscipy_openblas64_.dylib
  17.1 MB   dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3.12

✓ 主目录体积  680.5 MB（17 个子目录）
        → profiles 与 dsh-runtimes 通常占大头
✓ 缓存目录   3.4 MB / 23 个文件
        → 可安全清理，下次启动会重建
✓ 备份目录   2 份备份，共 85.4 KB
        → 数量正常
✓ 运行时    300.1 MB，1 个版本
        → 旧版本可在 DSH 更新后手动清理，工具不自动删
✓ 版本一致性  应用 0.2.1-rc.2，runtime.json 记录 0.2.1-rc.2
✓ 附件     4.7 MB / 24 个文件
        → 截图与会话绑定，删前先确认会话是否还需要
✓ 凭据文件   权限 600
        → 应存在且权限为 600
✓ 会话     2 个，最大 3.4 MB
        → 只在需要时清理
✓ 磁盘余量   380.9 GB 可用 / 共 926.3 GB
✓ 插件与扩展  1 个插件，1 个扩展

可自动清理：缓存目录(3.4 MB)
执行：dsh-doctor --fix
```

## 安装

零依赖，只要求 Python 3.8+：

```bash
git clone git@github.com:hansei996/dsh-doctor.git
cd dsh-doctor
python3 -m dsh_doctor            # 直接跑，无需安装
# 或者安装成命令
pipx install .
dsh-doctor
```

## 用法

```bash
dsh-doctor                       # 体检当前 ~/.dsh
dsh-doctor --root /path/to/.dsh  # 指定目录（也支持 DSH_HOME 环境变量）
dsh-doctor --format json         # 给脚本用
dsh-doctor --format markdown     # 贴到 issue / 文档里
dsh-doctor --format html         # 单文件报告，浏览器直接打开
dsh-doctor --older-than 30d      # 额外报告：超过 30 天的附件占多少
dsh-doctor --fix --dry-run       # 先看会删什么，不真删
dsh-doctor --fix                 # 列出将删内容，确认后清理
dsh-doctor --fix --yes           # 跳过确认（脚本/非交互环境必需）
dsh-doctor --top 10              # 看最大的 10 个文件（默认 5，0 关闭）
dsh-doctor --history ./my.jsonl  # 指定历史文件
dsh-doctor --no-history          # 不读不写历史，纯单次体检（缓存 + 旧备份）
dsh-doctor --fix --older-than 30d --dry-run   # 先看会删哪些历史附件
dsh-doctor --fix --older-than 30d             # 清掉超过 30 天的附件
```

应用包路径默认是 `/Applications/DeepSeek Harness.app`，装在别处时可以覆盖：

```bash
DSH_APP_PATH=/opt/dsh/DeepSeek\ Harness.app dsh-doctor
```
`--older-than` 只接受天（`30d` 或 `30`）。年龄**刚好等于** N 天的文件视为超期，会被清理。

退出码：健康分 ≥ 60 返回 0，否则返回 1，方便接到 CI 或定时任务里。

## 检查项

| 检查 | 关注点 | 是否可自动清理 |
| --- | --- | --- |
| 主目录体积 | 总量与子目录分布 | 否 |
| 缓存目录 | 超过 50 MB 时提示 | **是**（清空内容，保留目录） |
| 备份目录 | 超过 2 份的部分 | **是**（保留最近 2 份） |
| 运行时 | 超过 500 MB 时提示 | 否，只报告 |
| 版本一致性 | 应用包版本 vs 运行时 `runtime.json` 的 `desktopVersion`（读不到时退回目录名） | 否，不一致时提示重启 |
| 附件 | 超过 1 GB 时提示 | 否，与会话绑定 |
| 历史附件（`--older-than N`） | 超过 N 天的附件占用与数量 | **是**（只删超期文件，未超期的不动） |
| 凭据文件 | 是否存在、权限是否 600 | 否 |
| 会话 | 数量与最大体积 | 否 |
| 磁盘余量 | 少于 10 GB 时警告 | 否 |
| 无法读取的目录 | 权限不足导致统计偏小时提示 | 否 |
| 插件与扩展 | 数量统计 | 否 |

除了一级目录体积，`--top N` 会列出最大的 N 个**单文件**并给出相对路径——`profiles/` 那 343 MB 到底是谁占的，一眼能看到（比如 `node/bin/node` 115 MB、`mermaid.min.js.map` 12 MB）。这一项只读，不参与清理判断。

每次运行会往 `~/.dsh-doctor/history.jsonl` 追加一条体积记录（最近 100 条），下次运行就能看到「较上次（3 天前）+12.3 MB」这样的趋势。路径可用 `--history` 或环境变量 `DSH_DOCTOR_HISTORY` 指定；`--no-history` 完全不碰磁盘。历史文件坏行会被跳过，不会影响体检。

版本比较只取「主.次」两段做归一化，不做语义化排序——目的是判断"是不是同一代"，不是比大小。`:dsh-runtimes/<name>/runtime.json` 里的 `desktopVersion` 是权威来源，读不到时才退回目录名；两者都拿不到则输出「无法判断」，不影响健康分。

## 安全边界

`--fix` 只会做三件事：清空 `cache/`、删除最近两份之外的 `backups/`、在显式带上 `--older-than N` 时删除超过 N 天的附件文件。

不带 `--older-than` 时，`attachments/` 一个字节都不会动。带了也只删"超期文件"，目录结构保留（避免影响会话里引用的路径）。

以下目录**永不触碰**：`sessions/`、`memories/`、`profiles/`、`plugins/`、`extensions/`、`dsh-runtimes/`、`.credentials.yaml`。删除能力被收在 `rules.py` 的三个私有函数（`_clear_dir`、`_delete_backups`、`_delete_attachments`）里，单测覆盖了"该删的删掉、不该动的还在"。

## 开发

```bash
make test     # 103 个单测，纯标准库，不需要网络
make demo     # 对本机 ~/.dsh 跑一遍
```

代码结构：

```
dsh_doctor/
  scanner.py   # 只读扫描：体积、文件数、凭据权限、磁盘、附件 mtime
  version.py   # 读应用包版本、归一化、与运行时目录比对
  rules.py     # 规则 → 结论 + 可回收字节 + 清理动作
  report.py    # table / markdown / json / html 四种输出
  history.py   # 体检历史（JSONL），用于对比体积趋势
  cli.py       # 参数与 --fix 流程
```

设计上把"读"和"删"分开：`scanner` 只读，`rules` 决定能不能删，`cli` 才触发删除。这样体检可以放心在只读环境跑。

## 路线图

- [x] 支持 `--older-than`，按天清理附件
- [x] 检测 DSH 版本与应用目录是否一致
- [x] 输出 HTML 报告
- [x] 版本判断改用运行时自带的 `runtime.json`（`desktopVersion`），不再依赖目录名

# dsh-doctor

给 [DeepSeek Harness](https://github.com/) 的安装做体检：体积分布、可回收空间、凭据状态、插件与扩展、磁盘余量。

一个命令看清 `~/.dsh` 到底把空间花在哪，并且能安全清掉其中"确定可以删"的部分。

## 为什么

DSH 运行时目录会长得很快：`profiles/` 和 `dsh-runtimes/` 动辄几百 MB，`attachments/` 里全是历史截图，`backups/` 每次更新都留一份。本地实测：

```
$ dsh-doctor
dsh-doctor · /Users/junshengwu/.dsh
健康分 100/100  评级 A  可回收 3.4 MB
体积分布：profiles 343.2 MB · dsh-runtimes 300.1 MB · extensions 12.4 MB · plugins 11.1 MB

✓ 主目录体积  678.1 MB（17 个子目录）
        → profiles 与 dsh-runtimes 通常占大头
✓ 缓存目录   3.4 MB / 23 个文件
        → 可安全清理，下次启动会重建
✓ 备份目录   2 份备份，共 85.4 KB
        → 数量正常
✓ 运行时    300.1 MB，1 个版本
        → 旧版本可在 DSH 更新后手动清理，工具不自动删
✓ 附件     4.7 MB / 24 个文件
        → 截图与会话绑定，删前先确认会话是否还需要
✓ 凭据文件   权限 600
        → 应存在且权限为 600
✓ 会话     2 个，最大 1.9 MB
        → 只在需要时清理
✓ 磁盘余量   379.4 GB 可用 / 共 926.3 GB
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
dsh-doctor --fix --dry-run       # 先看会删什么，不真删
dsh-doctor --fix                 # 执行安全清理
```

退出码：健康分 ≥ 60 返回 0，否则返回 1，方便接到 CI 或定时任务里。

## 检查项

| 检查 | 关注点 | 是否可自动清理 |
| --- | --- | --- |
| 主目录体积 | 总量与子目录分布 | 否 |
| 缓存目录 | 超过 50 MB 时提示 | **是**（清空内容，保留目录） |
| 备份目录 | 超过 2 份的部分 | **是**（保留最近 2 份） |
| 运行时 | 超过 500 MB 时提示 | 否，只报告 |
| 附件 | 超过 1 GB 时提示 | 否，与会话绑定 |
| 凭据文件 | 是否存在、权限是否 600 | 否 |
| 会话 | 数量与最大体积 | 否 |
| 磁盘余量 | 少于 10 GB 时警告 | 否 |
| 插件与扩展 | 数量统计 | 否 |

## 安全边界

`--fix` 只会做两件事：清空 `cache/`、删除最近两份之外的 `backups/`。

以下目录**永不触碰**：`sessions/`、`memories/`、`profiles/`、`plugins/`、`extensions/`、`dsh-runtimes/`、`attachments/`、`.credentials.yaml`。删除能力被收在 `rules.py` 的两个函数里，单测覆盖了"该删的删掉、不该动的还在"。

## 开发

```bash
make test     # 14 个单测，纯标准库，不需要网络
make demo     # 对本机 ~/.dsh 跑一遍
```

代码结构：

```
dsh_doctor/
  scanner.py   # 只读扫描：体积、文件数、凭据权限、磁盘
  rules.py     # 规则 → 结论 + 可回收字节 + 清理动作
  report.py    # table / markdown / json 三种输出
  cli.py       # 参数与 --fix 流程
```

设计上把"读"和"删"分开：`scanner` 只读，`rules` 决定能不能删，`cli` 才触发删除。这样体检可以放心在只读环境跑。

## 路线图

- [ ] 支持 `--older-than`，按天清理附件
- [ ] 检测 DSH 版本与应用目录是否一致
- [ ] 输出 HTML 报告

# Thread Restore

[English](README.md) | 中文

恢复切换登录方式或 API provider 后，在 Codex Desktop 侧边栏消失的活跃对话。

## 对 Codex 说

> 安装 `https://github.com/yunKKang/codex-thread-restore`，然后恢复我全部活跃对话，完成后提醒我重启 Codex。

## 安装

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/yunKKang/codex-thread-restore.git ~/.codex/skills/thread-restore
```

## 使用

```bash
cd ~/.codex/skills/thread-restore

python3 restore.py             # 一次性恢复全部活跃对话
python3 restore.py now
python3 restore.py --dry-run
python3 restore.py restore -n 10
python3 restore.py restore --all
python3 restore.py verify
python3 restore.py show
python3 restore.py auto        # now 的兼容别名
python3 restore.py install-auto
python3 restore.py auto-status
python3 restore.py uninstall-auto
```

恢复后重启 Codex Desktop。

默认命令是一次性执行。它会先检查是否真的需要恢复；如果已经一致，不会创建新备份。

如需在每次登录后自动同步，可在 macOS 上显式安装 LaunchAgent：

```bash
python3 restore.py install-auto
python3 restore.py auto-status
python3 restore.py uninstall-auto
```

`install-auto` 会安装 `~/Library/LaunchAgents/com.codex.thread-restore.plist`。
它在登录时启动一个轻量 monitor，检测到 Codex 正在运行且 provider/索引数据变化后，
自动执行一次 `now`，恢复全部活跃对话。日志写入 `~/.codex/logs/thread-restore.auto.log`
和 `~/.codex/logs/thread-restore.auto.err.log`。

这不是 Codex Desktop 内部启动 hook，而是 macOS 用户级 LaunchAgent；Windows 端仍保持
手动一次性恢复。

Windows 端可在同一目录运行：

```powershell
py -3 restore.py
py -3 restore.py now
py -3 restore.py verify
```

## 安全边界

- 只选择活跃、未归档对话。
- 最近活跃按 rollout 最后一条事件判断，SQLite `updated_at` 仅作兜底。
- 所有 provider 的对话放在一起全局排序。
- rollout 文件可通过 header ID 或文件名匹配线程。
- 默认范围是全部活跃对话；`restore -n 10` 可显式恢复最近 10 个。
- `auto` 只是 `now` 的兼容别名。
- `install-auto` 只有用户显式执行时才会创建后台 LaunchAgent。
- 备份写入 `~/.codex/backups/restore.*`。
- 恢复失败时会自动拷回最新备份。
- 无第三方 Python 依赖。

MIT 协议。

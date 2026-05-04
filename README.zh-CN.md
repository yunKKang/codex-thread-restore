# Thread Restore

[English](README.md) | 中文

恢复切换登录方式或 API provider 后，在 Codex Desktop 侧边栏消失的最近 10 个活跃对话。

## 对 Codex 说

> 安装 `https://github.com/yunKKang/codex-thread-restore`，然后直接恢复我最近 10 个活跃对话。

## 安装

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/yunKKang/codex-thread-restore.git ~/.codex/skills/thread-restore
```

## 使用

```bash
cd ~/.codex/skills/thread-restore

python3 restore.py             # 恢复最近 10 个活跃对话
python3 restore.py --dry-run
python3 restore.py restore -n 10
python3 restore.py restore --all
python3 restore.py verify
python3 restore.py show
```

恢复前关闭 Codex Desktop，恢复后重启。

## 安全边界

- 只选择活跃、未归档对话。
- 默认范围是最近 10 个对话；如果不足 10 个，则全部恢复。
- 备份写入 `~/.codex/backups/restore.*`。
- 恢复失败时会自动拷回最新备份。
- 无第三方 Python 依赖。

MIT 协议。

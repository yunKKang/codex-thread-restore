# Thread Restore

[English](README.md) | 中文

恢复切换登录方式或 API provider 后，在 Codex Desktop 侧边栏消失的最近活跃对话。

## 安装

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/yunKKang/codex-thread-restore.git ~/.codex/skills/thread-restore
```

## 使用

```bash
cd ~/.codex/skills/thread-restore

python3 restore.py --dry-run   # 预览最近 5 个活跃对话
python3 restore.py             # 恢复最近 5 个活跃对话
python3 restore.py restore -n 10
python3 restore.py restore --all
python3 restore.py verify
python3 restore.py show
```

恢复前关闭 Codex Desktop，恢复后重启。

## 安全边界

- 只选择活跃、未归档对话。
- 默认范围是最近 5 个对话。
- 备份写入 `~/.codex/backups/restore.*`。
- 恢复失败时会自动拷回最新备份。
- 无第三方 Python 依赖。

## 测试

```bash
python3 test_restore.py
```

MIT 协议。

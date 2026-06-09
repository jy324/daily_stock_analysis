# Upstream Sync Baseline

本文记录 `feat/ashare-intelligence-foundation` 在 A 股情报收敛工作中的本地同步基线。这里的 ref 状态来自当前工作区本地 Git refs；本次没有在含有未提交改动的工作树上执行 rebase 或 merge。

## 2026-06-09 A 股情报收敛基线

- 工作分支：`feat/ashare-intelligence-foundation`
- DSA HEAD：`5e4a3ca4`
- 本地 `origin/main`：`98bfdef6`
- 与本地 `origin/main` 差异：落后 2 个提交，领先 11 个提交
- `a-stock-data` HEAD：`78c0270`
- 数据库 baseline schema：`2026-06-05-create-all-baseline`

本次收敛在当前分支上直接修改工作树，用于验证真实 package contract、Adapter、市场复盘、快照写入、风险事件过滤、runtime skills 和测试基线。最终形成 PR 前，应从干净工作树重新执行：

```bash
git fetch origin
git rebase origin/main
```

如果仓库维护策略不允许 rebase，则改用 merge `origin/main`，但 PR 描述必须记录同步方式、同步后的 HEAD、冲突处理范围和重新执行的验证命令。

## 当前未纳入同步动作

- 未执行远端 push、tag 或 commit。
- 未发布 `a-stock-data` wheel 或固定 Git SHA 依赖。
- 未把 A 股快照 repository 改为 append-only；当前仍沿用同槽位 revision 覆盖模型。
- 未执行 live provider smoke；当前 `a-stock-data` 只有 facade contract 与 fixture/injected-provider 测试。

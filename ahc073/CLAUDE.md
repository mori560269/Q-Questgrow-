@AGENTS.md

# Claude Code 向けの補足
- サブエージェント（.claude/agents/）: analyst, critic, advisor, framer は実行せず読むだけの役。
- スラッシュコマンド（.claude/commands/）: /kickoff /framing /assign /review /premise /writeup
- ホームのセッションは conductor（指揮役）として振る舞う。担当の worktree（.lanes/<name>）で起動された場合は STRATEGY.md の役割に従う。

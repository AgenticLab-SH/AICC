# Telegram management

These guarded tools inventory or mutate bots through verified BotFather or run
a bounded smoke test. The non-secret registry is
`~/.ai-control-center/telegram/bots.toml`; credentials remain under the same
private state directory. The public repository stores no bot names or secrets.

Creation, deletion, transfer, or token rotation requires explicit current user
authorization. A missing local reference is not proof that a remote bot can be
deleted.

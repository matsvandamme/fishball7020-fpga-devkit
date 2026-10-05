---
icon: material/key-outline
description: One command sets up a dedicated ssh key, so ssh fishball logs straight in.
---

# Log in with a key

```bash
# run from: the repo root
./devkit ssh-key            # idempotent; --check reports whether it is done
ssh fishball
```

It creates `~/.ssh/fishball`, a key used for nothing else (the board has a
published root password), installs it on the board, adds a `Host fishball`
block to `~/.ssh/config`, and proves it by logging in with the key alone.

The password stays enabled. Turning it off, and the risk of locking yourself
out: [networking reference](../networking.md#logging-in-without-a-password).

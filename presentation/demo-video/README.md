# Demo video

`Video.mp4` — the project walkthrough submitted with the final project (11:22).

## This file is stored with Git LFS

It is ~70 MB, so it is tracked with [Git LFS](https://git-lfs.com) rather than committed directly —
keeping it out of the git history means a clone stays small for anyone who does not need it.

**If `Video.mp4` opens as a ~130-byte text file** beginning `version https://git-lfs.github.com/…`,
you have the pointer rather than the video. Install Git LFS and fetch it:

```sh
# macOS: brew install git-lfs   |   Ubuntu/WSL: sudo apt install git-lfs
git lfs install
git lfs pull
```

You can also download it straight from the GitHub web UI, which resolves LFS pointers for you.

## What is in it

A walkthrough of the deployed application at https://app.worksmarternotharder.dev — check-in and
readiness, the generated programme, the Forum, and direct messages.

From **06:34** the recording uses **two browser sessions side by side**, so the Forum and the direct
messages can be shown working between two accounts at once. That part is deliberately recorded with
two separate cookie jars (two browser profiles): a browser holds one session cookie, so two tabs of
the same browser cannot hold two signed-in accounts — the second sign-in replaces the first. See
issue #609.

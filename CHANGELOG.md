# Changelog

- Mobile backend: PR detail routes for iPhone approval flow with media streaming and HTTP Range support
  - `GET /mr/<owner>/<name>/<number>` — fetch PR detail with parsed images and metadata
  - `GET /mr/image?url=<>&kind=<>` — stream media bytes with Range support for seeking
  - Added comprehensive test coverage for both routes (23 tests)
  - Reuses existing pr_images loader with shared cache at `~/.claude/mr-media-cache/`
- MARVIN button: a second press opens a new tab in the window it already opened ([#376](https://github.com/G-Eskayo/marvin/pull/376))


Wire the box's marvin-build provisioning to the default-build installer (#648)

The box VM's golden image is built by `config/mac-mini-2012/build-builder-image.sh` → `builder/provision.sh` (PR #981). Once the default build installer ships (marvin#648: "Default build step 6: installer --new/--join"), wire `provision.sh` to use it instead of building the image from scratch.

**Part of:** #981, #951
**Blocked by:** #648

See marvin#988 for context.

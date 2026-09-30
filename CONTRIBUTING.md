# Contributing

Bug reports, fixes and new device support are welcome.

## Reporting bugs

Open an [issue](../../issues/new/choose) using the bug report template. Debug
logs from `custom_components.pvvx_time_sync` and `bleak_retry_connector` make
Bluetooth problems much easier to track down.

## Pull requests

1. Fork the repository and branch from `main`.
2. Set up the development environment:

   ```bash
   uv sync
   uv run pre-commit install
   ```

3. Make your change, with tests. Protocol code (`protocol.py`, `client.py`)
   has no Home Assistant dependency and is tested against the fake device in
   `tests/fakes.py`.
4. Run the checks:

   ```bash
   uv run pre-commit run --all-files
   uv run pyright
   uv run pytest --cov=custom_components.pvvx_time_sync
   ```

5. Update `README.md` when behaviour or entities change, then open the pull
   request.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`).

## Releasing

Versions are bumped with [Commitizen](https://commitizen-tools.github.io/commitizen/)
from the Conventional Commits since the last tag:

```bash
uv run cz bump        # updates pyproject.toml, manifest.json, uv.lock and tags
git push --follow-tags
```

Pushing the tag (for example `0.2.0`, without a `v`) runs
`.github/workflows/release.yml`: it runs the checks, verifies that the tag,
`pyproject.toml` and `manifest.json` agree, and publishes a GitHub release with
generated notes and `pvvx_time_sync.zip`. HACS picks the release up.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).

# Release procedure

1. Confirm that the working tree contains only intended changes.
2. Update `CHANGELOG.md`, `CITATION.cff`, `src/diffractscout/__init__.py` and `pyproject.toml` to the same version.
3. Run:

```bash
python -m compileall -q src
pytest -q
rm -rf outputs/release_demo
SOURCE_DATE_EPOCH=<release-epoch> diffractscout demo -o outputs/release_demo
diffractscout verify outputs/release_demo
python -m pip wheel . --no-deps -w dist
```

4. Install the wheel in a clean environment and repeat the demo.
5. Review `docs/SCIENTIFIC_CONTRACTS.md`, `docs/SOURCE_LINEAGE.md`, dependency licenses and the paper disclosure.
6. Commit the release, create an annotated tag such as `v0.1.0`, and push both.
7. Create GitHub release notes from the changelog and attach source/wheel checksums when appropriate.
8. Archive the tagged release with Zenodo or an equivalent service.
9. Add the archive DOI to `CITATION.cff`, `paper/paper.md` and the GitHub release.
10. For a JOSS review release, report the exact tag and archive DOI in the review issue.

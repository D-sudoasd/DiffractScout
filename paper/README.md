# JOSS paper sources

- `paper.md`: manuscript source using current JOSS section headings;
- `paper.bib`: bibliography;
- `fig_workflow.*`: workflow figure in raster and editable vector formats;
- `fig_validation.*`: executable offline-validation figure in raster and editable vector formats;
- `make_figures.py`: deterministic figure-generation source;
- `paper.pdf`: locally reviewed draft; the Open Journals action remains the authoritative JOSS build.

Regenerate figures from the current package:

```bash
python -m pip install -e ".[paper]"
SOURCE_DATE_EPOCH=1786492800 python paper/make_figures.py
```

Build the authoritative draft with `.github/workflows/draft-pdf.yml` or Docker through `scripts/build_paper.sh`. Render every page to PNG and inspect it before release.

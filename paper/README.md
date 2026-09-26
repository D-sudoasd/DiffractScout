# JOSS paper sources

This directory contains the JOSS manuscript and its reproducible figures:

- **paper.md**: Markdown manuscript with the required JOSS sections and YAML metadata.
- **paper.bib**: cited crystallography, software, data-service, and source-project records.
- **fig_workflow.png** and **fig_validation.png**: manuscript figures; their editable SVGs are retained beside them.
- **make_figures.py**: deterministic source for the two figures.
- **paper.pdf**: a generated preview only. It is stale after any manuscript, bibliography, or figure change. The Open Journals draft build is authoritative.

The manuscript describes a bounded workflow contribution: linking candidate records, source CIFs, calculation settings, diagnostic states, theoretical references, and their exported result bundle. It does not claim a new diffraction or elasticity algorithm. The developer reports prior use in several published materials-science papers; those records and their exact software-version links have not yet been provided for citation-level traceability.

## Submission inputs still required

Complete these items before submitting to JOSS:

1. **Public development history.** The repository became public at 10:02:29 UTC on 12 August 2026. The current JOSS guidance asks for more than six months of public development history when a repository is recent, with sustained development and supporting release, issue, or pull-request evidence. On the manuscript date of 26 September 2026, this period is not yet met; submission should be after 10:02:29 UTC on 12 February 2027, and 15 February 2027 is a practical earliest date if development and the other criteria remain adequate.
2. **Published-use evidence.** Provide representative paper titles and DOI or stable links, identify where DiffractScout was used in each study, and give the software version or commit where possible. The manuscript currently attributes this use to the developer's report and does not cite unidentified papers.
3. **Funding and acknowledgements.** Provide any funding body and grant identifiers and state whether funders influenced software design, data collection, analysis, or publication. If there was no external financial support, confirm that explicitly. Add any additional acknowledgements that belong in the manuscript.
4. **Author list.** Delun Gong's name, ORCID, and affiliation were confirmed for this draft. Confirm that the author list is complete and that all listed authors agree to authorship.
5. **Human review of AI-assisted work.** Earlier repository work and this revision used OpenAI GPT-5.6 Pro, OpenAI Codex GPT-6, and cooperating assistant agents across software, tests, figures, documentation, and manuscript work. Automated checks are described in the manuscript, but no assertion that the human author has completed review is made. The responsible author must review, edit, and validate every AI-assisted contribution and make the core design decisions before the JOSS AI disclosure can assert compliance.
6. **Submission date.** Update the JOSS metadata date to the actual submission date if the submission happens after this draft.
7. **Archived software citation.** JOSS requests a tagged, archived software release with a DOI after successful review. At that stage, replace or supplement the source-repository citation in paper.bib with the DOI for the reviewed release; do not invent a DOI beforehand.

The independent analytic benchmark and synthetic fixtures are software checks. They are not experimental validation and should not be presented as research-use evidence.

## Figures

Regenerate figures from the current package:

    python -m pip install -e ".[paper]"
    SOURCE_DATE_EPOCH=1786492800 python paper/make_figures.py

## Paper build

Build the draft with .github/workflows/draft-pdf.yml or Docker through scripts/build_paper.sh. Render and inspect every page after the paper source is frozen. The checked-in paper.pdf is not updated as part of a manuscript-only revision.

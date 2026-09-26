# JOSS readiness evidence audit — 26 September 2026

This is a dated snapshot of the public repository before the current 0.4.0
usability work was pushed. It records verifiable evidence and outstanding
evidence requests; it is not a JOSS editorial decision.

## Public-development timeline

GitHub's repository API reported creation at **2026-08-12 10:02:29 UTC**.
The public `main` HEAD at this audit was
[`0d56f99e10`](https://github.com/D-sudoasd/DiffractScout/commit/0d56f99e10abd7e32e87c6f0e5344fc29ba3c670),
dated 12 September 2026. Public records reviewed:

| Date (UTC) | Public record | What it documents |
|---|---|---|
| 12 Aug 2026 | [v0.3.0 release](https://github.com/D-sudoasd/DiffractScout/releases/tag/v0.3.0) | First tagged GitHub release. It is not an immutable archive DOI. |
| 12 Aug 2026 | [PR #3](https://github.com/D-sudoasd/DiffractScout/pull/3), [PR #5](https://github.com/D-sudoasd/DiffractScout/pull/5), [PR #6](https://github.com/D-sudoasd/DiffractScout/pull/6), [PR #7](https://github.com/D-sudoasd/DiffractScout/pull/7) | CI repair, CIF/peak workflow and Excel views, GUI layout, and quick-export race correction. |
| 17 Aug 2026 | [PR #8](https://github.com/D-sudoasd/DiffractScout/pull/8) | Scientific-analysis and desktop-workflow hardening. |
| 20 Aug 2026 | [PR #9](https://github.com/D-sudoasd/DiffractScout/pull/9) | Transaction and scientific-input safeguards. |
| 23 Aug 2026 | [PR #11](https://github.com/D-sudoasd/DiffractScout/pull/11) | Unit-handling and desktop workflow fixes. |
| 27 Aug 2026 | [PR #13](https://github.com/D-sudoasd/DiffractScout/pull/13) | Scientific parsing and release-workflow hardening. |
| 12 Sep 2026 | [main commit `0d56f99`](https://github.com/D-sudoasd/DiffractScout/commit/0d56f99e10abd7e32e87c6f0e5344fc29ba3c670) | Quick-export launch and GUI status/form-mapping fixes. |

The reviewed activity is in **August and September only** and is concentrated
between 12 and 27 August. Commits dated before 12 August are not public
development evidence. Automated workflows are not counted as substantive
development. The public PRs reviewed were opened by the maintainer account;
the issue tracker at this snapshot had the author's roadmap issue but no
recorded non-author issue or discussion. This record does not establish
external adoption or multiple contributors.

The GitHub history does establish open iteration and a release. It does not
yet establish more than six months of active public development. The latest
JOSS submission guidance requires the repository to have been public for
**more than six months** before submission, with active development spanning
that period; its checklist also asks for public issue/PR and release evidence.
The six-month anniversary is 12 February 2027. Do not submit on that date;
the project's conservative earliest date is 15 February 2027, subject to the
activity and evidence gates.

## Research-use status

On 26 September 2026 the submitting author reported that DiffractScout was
used in multiple published papers. The report is evidence that research-use
records should be collected; no specific article, DOI, version/commit, feature,
or research outcome was supplied to this audit. The claim is therefore not
yet indexed in `publications_or_preprints` or linked to a reproducible case.
Do not report a paper count, paper titles, or specific scientific outcomes
until the source records are identified and checked.

The package's 45-check analytic benchmark and synthetic offline demonstration
are software and mathematical-contract evidence. They are not records of a
research decision, experimental validation, or external adoption.

## Official JOSS gates and local project policy

| Topic | Official guidance checked on 26 Sep 2026 | Project status at this audit |
|---|---|---|
| Public age and iteration | More than six months public, active development across the period, evidence of a release and public issues/PRs; concentrated history can fail screening. | **Blocked by time and distribution.** Two public calendar months are recorded; meaningful work must continue through the period. |
| Research impact | Evidence of actual research use, at least by the developers; citations, documented workflow use, and external integration are examples. A future-potential claim alone is insufficient. | **Reported, source audit pending.** The author identifies published use, but the representative source records and exact software contribution remain to be recorded. |
| Open-source practice | For a single-author project, JOSS accepts broader evidence, but expects multiple indicators such as ongoing public commits, release/changelog, tests/CI, documentation, contribution and support expectations. | Core routes and one release exist; continue iterative activity and capture real interactions. |
| Paper | 750–1750 words; required sections, references, author/affiliation metadata, applicable publication examples, funding acknowledgement, and specific AI disclosure. | The draft needs a final impact-reference map, funding statement, exact AI-use and human-review confirmation, official build, and page review. |
| Project's stricter scientific gates | Not separate boxes in the current JOSS checklist. | Local script also requires four active months, a hashed real-use case, diffraction and elasticity comparison reports, and an external-engagement record. Keep these labeled as local controls. |

JOSS's current sources are [submission requirements](https://joss.readthedocs.io/en/latest/submitting.html),
[review criteria](https://joss.readthedocs.io/en/latest/review_criteria.html),
[review checklist](https://joss.readthedocs.io/en/latest/review_checklist.html),
[paper format](https://joss.readthedocs.io/en/latest/paper.html), and
[policies](https://joss.readthedocs.io/en/latest/policies.html).

## Actions

1. Identify representative papers named by the submitting author. For each,
   verify the DOI/URL, how DiffractScout was used, the matching release or
   commit, and the claim the paper can support. Add the citation to the paper
   bibliography and `publications_or_preprints` only after verification.
2. Continue substantive public maintenance across each remaining month. Add
   only merged, meaningful work to the public-development ledger; do not
   backdate activity or count CI.
3. Complete the final 0.4.0 source acceptance, remote CI, and official
   Open Journals build against one clean commit. Update the readiness snapshot
   after those checks rather than carrying the pre-upgrade diagnostic forward.
4. Keep the local scientific-validation requirements separate from JOSS
   official gates. Publish methods, conventions, predeclared tolerances, and
   limitations before adding either comparison as completed evidence.
5. Obtain the submitting author's final confirmation of the complete author
   list and consent, funding and sponsor role, related-work disclosures, and
   human review of every AI-assisted output. The currently listed author's
   name, ORCID, and affiliation were confirmed, but that does not complete the
   remaining submission metadata.

After successful JOSS review, create the final tag and immutable archive DOI
and add them to `archived_releases`; an ordinary GitHub Release does not fill
that post-review step.

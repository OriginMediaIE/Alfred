# ADR-0004: Licence and commercial model (counsel brief)

- **Status:** Proposed — **blocked pending qualified counsel**
- **Date:** 2026-08-21
- **Decision owners:** OM Automate release engineering + external open-source/IP counsel
- **Related:** `docs/om-automate/licence-and-attribution-review.md`,
  `docs/om-automate/18-commercial-readiness-gap-analysis.md` (Track F), Gate 0 item 2

## Purpose

This document is a **brief for counsel**, not a decision. It records the
repository facts a lawyer needs in order to advise on licence, chain of title,
and the permissible commercial model. Engineering must not pre-empt that advice;
all other release work is being kept licence-agnostic until it returns.

**This is engineering analysis, not legal advice.**

## Decision-relevant findings

### 1. The contributor base is large and third-party — this is the governing fact

```
git log --all --format='%aN' | sort -u | wc -l   →  330
```

**330 distinct contributor identities** appear in history. The repository is a
fork of `https://github.com/odysseus-dev/odysseus` (origin and upstream both
point there). First commit `e5c99a5` "Odysseus v1.0", 2026-05-31, by
`pewdiepie-archdaemon`, who is also the highest-volume contributor (558 commits).

Commit-volume distribution:

| Contributor | Commits |
|---|---:|
| pewdiepie-archdaemon | 558 |
| Afonso Coutinho | 139 |
| red person | 89 |
| Alexandre Teixeira | 80 |
| Kenny Van de Maele | 56 |
| (325 others) | remainder |

**Consequence for counsel to confirm:** relicensing this work to proprietary or
dual-licensed terms would require permission from every copyright holder whose
contributions survive in the distributed work. With 330 identities and no
observed CLA or copyright-assignment mechanism in the repository, we assess that
path as **impractical rather than merely expensive**, and have sequenced the
programme accordingly. We ask counsel to confirm or correct that assessment
before we invest further in it.

### 2. Declared licence

`LICENSE` contains the GNU AGPL v3 text. `README.md:917` declares
AGPL-3.0-or-later. No separate project-level copyright-holder line or per-file
SPDX header convention was found.

**Question:** is the AGPL grant validly made and adequately evidenced for
distribution, given the absence of a project copyright line?

### 3. Contradictory permissive claims — corrected 2026-08-21, ratification needed

The prior review (`licence-and-attribution-review.md:63-65`) flagged "MIT core"
assertions conflicting with the AGPL declaration. Those were still live and have
now been corrected in `ACKNOWLEDGMENTS.md`, `Dockerfile`, and `src/pdf_forms.py`:
the dependency-licence analysis was retained, the claim that the *program* is
permissive was removed, and the implication that installing PyMuPDF is what
*activates* AGPL duties was corrected.

Genuine upstream attributions (`ACKNOWLEDGMENTS.md:25,29` — opencode, llmfit,
both MIT) were deliberately **preserved**.

**Question:** does the corrected wording satisfy notice obligations, and does the
prior inconsistent wording in published history create any residual exposure?

### 4. Third-party inventory is incomplete

- `THIRD_PARTY_NOTICES` **does not exist**.
- `licenses/` contains 4 files (DeepResearch Apache-2.0, OpenDyslexic OFL,
  llmfit MIT, opencode MIT) against a full Python + Node + vendored-JS + font tree.
- No SBOM tooling exists in the repository.

Notice generation is scheduled against the SBOM work in Track B2.

### 5. Specific dependencies needing an opinion

| Dependency | Licence | Status |
|---|---|---|
| PyMuPDF | AGPL-3.0-or-later / commercial (dual) | Optional; `requirements-optional.txt:22`, `requirements-optional.lock:5` (`==1.28.0`). Isolated to `src/pdf_forms.py` |
| caldav | GPL-3.0-or-later **OR** Apache-2.0 | Project **elects Apache-2.0**. Election needs ratification |
| markitdown | MIT | Optional, lazy-imported |
| pypdf / charset-normalizer | BSD-3-Clause / MIT | Default install |

### 6. Trademark

"OM Automate", its logo, retained upstream Odysseus branding, and provider marks
are unresolved. See `docs/om-automate/08-branding-register.md`. No clearance
search has been performed.

## Options presented for advice

Engineering makes no recommendation between these. Cost annotations are
engineering effort only and assume the option is lawful.

| Option | Engineering cost | Principal legal question |
|---|---|---|
| **A. AGPL + paid support / managed installation** | Low — source offer, notices, SBOM | Is the existing grant sufficient to distribute and monetise services around it? |
| **B. Sell signed binaries, still AGPL** | Medium — adds exact-version Corresponding Source beside every artifact, plus a pre-login source offer for network users | Does the planned delivery satisfy AGPL §13 network-interaction and §6 conveying obligations? |
| **C. Relicense proprietary or dual** | Very high — 330-holder permission, plus replacing or commercially licensing every copyleft dependency | Is this achievable at all? See finding 1 |

## Questions for counsel

1. Is the AGPL-3.0-or-later grant valid and sufficiently evidenced for distribution?
2. Confirm or correct the finding that Option C is impractical at 330 contributors.
3. Where is the combined-work boundary for the native app, the container, bundled
   models, and remote MCP servers?
4. Does AGPL §13 oblige us to expose the source offer **before login** for the
   companion and web surfaces?
5. Ratify the `caldav` Apache-2.0 election and the PyMuPDF isolation.
6. Does the corrected "MIT core" wording fully discharge the issue, including for
   already-published history?
7. What retention of legal evidence and artifact hashes is required per release?
8. Trademark: is "OM Automate" usable, and what upstream attribution must persist?

## Consequences

Until counsel responds, all of Track F is blocked, and Track C ships artifacts
without a final notices/source-offer payload. Tracks A, B, D, E, G, and H proceed
unaffected — none depends on the licence outcome.

## Follow-up

Record the returned advice as ADR-0005 and update
`docs/om-automate/licence-and-attribution-review.md` to reference it.

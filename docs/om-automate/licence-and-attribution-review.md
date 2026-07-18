# OM Automate Licence and Attribution Review

## Important limitation

This document is an engineering compliance review, **not legal advice**. It records repository evidence, conservative release controls and questions for qualified open-source/trademark counsel. It does not determine copyright ownership, create a licence, approve a distribution, or guarantee compliance in any jurisdiction.

No public, hosted, binary, container, app-store or commercial release of OM Automate should occur until counsel has confirmed the licence grant, copyright chain, third-party inventory, source-offer implementation and trademark position.

## Review basis

- **Audit date:** 2026-07-18.
- **Audited source:** upstream `main` commit `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed` from `https://github.com/odysseus-dev/odysseus`, working branch `om-automate/main`.
- **Repository files reviewed:** `LICENSE`, `README.md`, `ACKNOWLEDGMENTS.md`, `.dockerignore`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `requirements-optional.txt`, `licenses/`, vendored frontend assets, fonts, package metadata and source headers.
- **Primary explanatory sources:** the [GNU AGPL v3 text](https://www.gnu.org/licenses/agpl-3.0.html), [GNU licence FAQ](https://www.gnu.org/licenses/gpl-faq.en.html), including its explanations of [remote AGPL interaction](https://www.gnu.org/licenses/gpl-faq.en.html#AGPLv3InteractingRemotely), [AGPL Corresponding Source](https://www.gnu.org/licenses/gpl-faq.en.html#AGPLv3CorrespondingSource), [licence declarations](https://www.gnu.org/licenses/gpl-faq.en.html#LicenseCopyOnly) and [complete source rather than diffs](https://www.gnu.org/licenses/gpl-faq.en.html#DistributingSourceIsInconvenient).

The licence text controls over this engineering summary. The GNU FAQ is explanatory material, not a substitute for the licence or legal advice.

## Executive conclusion

The repository presents the program as **GNU Affero General Public License v3.0 or later** in `README.md:74-76` and includes the AGPL v3 text in `LICENSE`. OM Automate is intended to modify that program substantially and serve an interactive web application. The conservative release assumption is therefore:

1. The modified combined application must remain under the applicable AGPL terms unless the relevant copyright holders provide separate permission.
2. A modified OM Automate instance used by anyone remotely through a computer network must prominently offer those users the complete Corresponding Source for the exact running version at no charge.
3. Distribution of source, native binaries, installers, containers or offline bundles triggers the applicable notice, licence, modified-work and Corresponding Source conditions.
4. Rebranding does not permit removal of copyright, licence, no-warranty, provenance or third-party notices.
5. The AGPL does not provide a general trademark licence. The old name/logo can be removed from product surfaces while factual legal attribution remains.

The repository is **not release-ready from a licence-compliance perspective**. The most serious blockers are contradictory “MIT core” statements, incomplete third-party notices/source records, lack of a verified exact-version source-offer surface, and uncertainty around the project-level copyright/licence declaration.

## Current licence evidence

### Repository-level licence signal

- `README.md:74-76` explicitly says `AGPL-3.0-or-later` and links both `LICENSE` and `ACKNOWLEDGMENTS.md`.
- `LICENSE:35-44` defines modification, covered work, conveyance and Appropriate Legal Notices.
- `LICENSE:60-65` grants basic permission, including making/running/propagating covered works that are not conveyed while the licence remains in force.
- `LICENSE:72-75` requires verbatim source copies to retain copyright, licence and no-warranty notices and include the licence.
- `LICENSE:77-86` requires conveyed modified source to carry prominent modification/date and licence notices, license the whole covered work under the AGPL, and address Appropriate Legal Notices for interactive interfaces.
- `LICENSE:90-113` governs conveying object code and the available methods for supplying machine-readable Corresponding Source; the later part of section 6 also addresses Installation Information for certain User Products.
- `LICENSE:124-136` permits specified additional terms, including preservation of reasonable attribution, origin marking and withholding trademark rights.
- `LICENSE:186-190` requires a modified network-interactive version to prominently offer all remote users its Corresponding Source at no charge.
- `LICENSE:202-212` contains the no-warranty and liability provisions that must not be silently contradicted by product copy.

### Ambiguity requiring counsel

The README declaration is meaningful evidence of the intended licence, but the repository contains no clear project copyright-holder line and the first-party Python/JavaScript/HTML scan found no consistent SPDX or per-file copyright/licence header. The bundled `LICENSE` is the standard licence text rather than an application-specific notice. More importantly, `ACKNOWLEDGMENTS.md:141-159` and `Dockerfile:72-77` describe a “MIT core,” directly conflicting with the README and repository licence.

Counsel/rightsholder confirmation is required for:

- the identity of the copyright holders and their authority to license all first-party/adapted code;
- whether the intended grant is exactly AGPL-3.0-only or AGPL-3.0-or-later;
- whether every contributor/adapted contribution is covered compatibly;
- any additional terms, trademark policy or contributor agreement not present in the repository;
- the boundary between the AGPL-covered work, separate services and mere aggregation.

Until resolved, do not claim that any “core” is MIT, do not relicense OM Automate, and do not add a proprietary restriction to the covered work.

## Finding register

### LIC-001 — the repository contradicts its own AGPL declaration

- **Severity:** Critical release blocker.
- **Evidence:** `README.md:74-76` declares AGPL-3.0-or-later. `ACKNOWLEDGMENTS.md:143-159` calls the core “fully permissive,” “MIT-compatible” and “MIT core.” `Dockerfile:72-77` says the default image “stays MIT-core.” No separate MIT project licence was found.
- **Risk:** users, distributors and downstream developers receive materially misleading licensing information; a release may omit AGPL source/network obligations based on the false statement.
- **Required remediation:** remove/correct every “MIT core” assertion through a counsel-reviewed change; state the repository-level licence consistently; preserve accurate permissive-component notices without describing the whole work as permissive. The PyMuPDF note must not imply that installing PyMuPDF is what first activates AGPL duties when the repository already declares itself AGPL.
- **Release evidence:** counsel-approved licence statement, zero contradictory matches, and tests that all packaging/about/legal surfaces show the same licence identifier.

### LIC-002 — OM Automate needs an exact-version network source offer

- **Severity:** Critical for any modified instance with remote users.
- **Evidence:** AGPL section 13 at `LICENSE:186-190` applies when the modified version supports remote interaction. OM Automate is an interactive web application and the rebrand/feature work creates a modified version. No verified prominent exact-version source link was found in the login/application UI.
- **Risk:** operating the modified application for household, team, customer or public remote users without the offer can breach a condition of the declared licence.
- **Required remediation:** expose an unauthenticated, prominent **Source** or **Legal & Source** link on the login page and a persistent application menu/footer. It must identify the running version/commit and give standard, no-charge access to a complete source archive or repository tag that remains available. The source endpoint must not require an account, disclose secrets, or point merely to upstream/unmodified source.
- **Release evidence:** browser test from a remote-user perspective downloads the exact running version's complete source; the link remains correct after upgrades and rollbacks.

### LIC-003 — binary/container redistribution needs a Corresponding Source process

- **Severity:** Critical for distributed images, installers, native apps or offline bundles.
- **Evidence:** `LICENSE:90-113` requires machine-readable Corresponding Source using an allowed section 6 method when object code is conveyed. The GNU FAQ explains that the source must correspond to the distributed version and cannot be only upstream source or diffs. `.dockerignore:32-33` excludes `docs/` and all `*.md` from the Docker build context; `ACKNOWLEDGMENTS.md` therefore is not included in the image even though `LICENSE` (no extension) is not excluded.
- **Risk:** an image or binary can be distributed without the complete preferred form for modification, build/install scripts, notices or clear source directions.
- **Required remediation:** for every released artifact, publish a version-locked source archive alongside it with clear directions. Include all source needed to generate/install/run/modify the covered work, build and packaging scripts, interface/schema definitions, dependency/patch data, modified covered libraries and applicable installation information. Exclude user data, secrets and unrelated credentials. Do not rely on source being incidentally present inside a container.
- **Release evidence:** a clean-room build from the offered source produces the intended artifact/functionality; artifact metadata links to the source and records how long it will remain available.

### LIC-004 — modification, legal notice and no-warranty surfaces are incomplete

- **Severity:** High.
- **Evidence:** conveyed modified source must carry prominent modification/date and licence notices (`LICENSE:77-86`). Appropriate Legal Notices are defined at `LICENSE:40-44`. The repository currently has no OM Automate modification notice because implementation has only begun, and the current visible UI has no verified source/legal surface.
- **Risk:** rebranding can misrepresent origin or hide licence/no-warranty/source information.
- **Required remediation:** add a top-level counsel-reviewed modification notice, retain `LICENSE`, update acknowledgements accurately, and create a Legal/Source UI containing copyright/provenance, applicable licence, no-warranty notice, third-party notices and exact-version source access. Determine whether the upstream interactive interface displayed Appropriate Legal Notices and document the section 5(d) analysis; provide the surface regardless as the practical section 13 source offer.
- **Release evidence:** notice includes modifier identity and relevant dates, travels with source/artifacts, and is accessible from unauthenticated and authenticated UI.

### LIC-005 — vendored libraries and fonts lack a complete notice set

- **Severity:** High.
- **Evidence:** `ACKNOWLEDGMENTS.md:54-89` inventories vendored frontend libraries and fonts. The repository's `licenses/` directory contains only `DeepResearch-Apache-2.0.txt`, `OpenDyslexic-OFL.txt`, `llmfit-MIT-LICENSE.txt` and `opencode-MIT-LICENSE.txt`. `static/lib/html2pdf.bundle.min.js:1` explicitly says to see `html2pdf.bundle.min.js.LICENSE.txt`, but that file is absent. Fira Code, Inter and GohuFont files are shipped under `static/fonts/` without a corresponding complete notice set in `licenses/`. Other minified bundles may retain fragments but are not a reliable notices package.
- **Risk:** copyright/licence notices required by MIT/BSD/Apache/OFL or other terms may not accompany redistributed code/assets; bundled transitive components may be omitted.
- **Required remediation:** identify the exact version and provenance of every vendored file, obtain its complete applicable licence/NOTICE text, preserve embedded headers and generate `THIRD_PARTY_NOTICES`. Prefer rebuilding vendored bundles from pinned source with preserved licence files. Do not ship an asset whose source/licence cannot be established.
- **Release evidence:** file-level manifest maps hash → source/version/licence/copyright/notice path; an automated scanner and manual review both pass.

### LIC-006 — dependency/container attribution is incomplete and versions are unstable

- **Severity:** High for redistribution, Medium for private local testing.
- **Evidence:** `ACKNOWLEDGMENTS.md:91-123` lists Python dependencies but omits current direct requirements including `nh3`, `python-dateutil`, `httpx2`, `faster-whisper` and `ddgs`; it names `duckduckgo-search` instead of the current `ddgs` package. Most entries in `requirements.txt:1-50` and `requirements-optional.txt:7-25` are unpinned. Compose identifies SearXNG, Chroma and ntfy at `ACKNOWLEDGMENTS.md:42-52`, while Chroma uses `latest` and ntfy is untagged (`docker-compose.yml:80-88` and `docker-compose.yml:140-149`).
- **Risk:** the actual shipped dependency set and licence terms cannot be reproduced; notices can describe a different version from the artifact. Pulling/composing an image is not evidence that all redistribution/source duties are satisfied, particularly for offline bundles or mirrored images.
- **Required remediation:** lock every direct/transitive dependency and image to a reviewed version/digest; generate SPDX or CycloneDX SBOMs for Python, JavaScript, OS packages and container layers; run licence-policy review on the exact lock; link each composed service to its licence/source. Perform a separate analysis when OM Automate redistributes/mirrors images rather than asking users to pull them.
- **Release evidence:** SBOMs and licence reports are attached to every release and match artifact digests.

### LIC-007 — adapted code and optional copyleft components need boundary review

- **Severity:** High.
- **Evidence:** `ACKNOWLEDGMENTS.md:12-38` identifies adapted opencode (MIT), llmfit (MIT) and Tongyi DeepResearch (Apache-2.0) code. Their listed licence texts are present under `licenses/`, but a file-level provenance map is absent. `requirements-optional.txt:20-25` includes PyMuPDF under AGPL; `ACKNOWLEDGMENTS.md:149-154` asserts that its network clause applies only to that feature. CalDAV is claimed to be used under one side of a dual licence at `ACKNOWLEDGMENTS.md:155-156`.
- **Risk:** adapted files may have lost required notices; the project's existing AGPL status is obscured; optional component terms, commercial alternatives or dependency licence variants may be misstated.
- **Required remediation:** map adapted files/commits to original notices and preserve them; verify the exact package-version licences and compatibility; have counsel assess PyMuPDF integration/distribution and the CalDAV election. Correct the suggestion that the rest of the application is an MIT core.
- **Release evidence:** provenance manifest, retained notices, dependency licence copies and counsel decision for every non-permissive/dual/commercial component.

### LIC-008 — rebranding creates trademark and origin risks outside copyright licensing

- **Severity:** High until marks are cleared.
- **Evidence:** AGPL section 7 recognises that trademark rights may be withheld (`LICENSE:124-130`). The repository includes old sailboat/wordmark assets and third-party provider marks; see `docs/om-automate/08-branding-register.md`.
- **Risk:** AGPL permission to modify copyrightable code is not permission to use an upstream or provider trademark. Conversely, removing factual attribution can misrepresent origin or violate notice obligations. “OM Automate” itself may conflict with an existing mark.
- **Required remediation:** replace upstream visible marks with original, rights-cleared OM Automate assets; conduct name/domain/app-store trademark clearance; retain factual “based on/modified from” attribution in legal materials; review Ollama, SGLang, Google and other provider logos/names under their current brand rules; do not imply sponsorship.
- **Release evidence:** written ownership/licence for every OM asset, counsel clearance record for the product name, and an asset register for third-party marks.

### LIC-009 — runtime CDN and generated/browser-delivered code need inclusion in the bill of materials

- **Severity:** Medium.
- **Evidence:** `ACKNOWLEDGMENTS.md:69-78` lists KaTeX, Mermaid, Pyodide and PDFObject loaded at runtime from CDNs. The web application also conveys JavaScript/assets to browsers.
- **Risk:** runtime dependencies can change independently, notices may not match, and browser-delivered covered/minified code may lack a clear route to its preferred source.
- **Required remediation:** pin URLs with integrity hashes or self-host reviewed artifacts; include them in SBOM/notices; publish preferred source for OM Automate browser code and build steps; distinguish unmodified third-party CDN artifacts from covered application code.
- **Release evidence:** offline build inventory, integrity verification and source/notices links cover every browser-delivered artifact.

## Deployment scenario analysis

The following is a conservative engineering interpretation for planning only. Counsel must apply the facts and jurisdiction.

| Scenario | Likely engineering obligations/control |
|---|---|
| Run the **unmodified** upstream program locally for one user, no copy conveyed | The licence expressly permits running the unmodified program; preserve the received licence/notices. No OM Automate rebrand exists in this scenario. |
| Modify/rebrand and run locally for the modifier only, with no remote user and no copy conveyed | Section 2 generally permits private make/run/propagation without conveyance while the licence remains in force. Keep a complete internal source record and notices so later deployment is safe. |
| Modified OM Automate used remotely by another person over LAN, VPN or Internet | Treat section 13 as active: prominently offer every remote user the complete Corresponding Source for the exact running version at no charge. “Private” or authenticated access does not by itself remove the remote-user condition. |
| Modified OM Automate offered as a public/hosted service | Section 13 source offer is required; also implement legal/no-warranty/provenance surfaces and satisfy privacy/consumer/contract rules outside this licence review. |
| Give modified source to another person/entity | Treat as conveyance: retain notices/licence/no-warranty terms, add prominent modification/date notice and license the covered modified work under the applicable AGPL terms. |
| Give a native binary, installer, container image, VM or offline bundle to another person/entity | Treat as object-code conveyance under section 6: provide the applicable notices/licence plus machine-readable complete Corresponding Source through an allowed mechanism, and Installation Information where required. |
| Use a contractor/cloud operator to modify/run only on the commissioning party's behalf | Section 2 contains a narrow provision for exclusive work under the commissioning party's direction/control and restrictions on copies. Do not assume it applies; use counsel-reviewed contracts and access/copy controls. |
| Ship Docker Compose that pulls separate services | Record each service as a separate component, but do not assume “mere aggregation” without analysing modification, distribution, linking/communication and what artifacts OM Automate actually conveys. Mirrored/offline images require their own compliance process. |

Because OM Automate is, by definition, a modified network-capable version, the safest implementation is to ship the source offer in every build, including nominally local builds. It costs little and prevents a deployment-mode toggle from silently changing compliance.

## What Corresponding Source should contain

Subject to counsel and the licence's section 1 definition, the release source package should include the preferred form for making modifications, including:

- all OM Automate and retained upstream source at the exact release revision;
- frontend source, templates, styles, non-generated asset sources and source maps/build inputs;
- database schemas, migration source and interface definitions;
- installation, packaging, container, service, build and dependency-lock scripts;
- patches and modified source for covered/included dependencies where required;
- configuration examples needed to build/install/run, with every secret removed;
- test source and generation scripts needed to validate the build;
- `LICENSE`, accurate acknowledgements, modification notice and third-party licence/NOTICE files;
- instructions that identify the artifact/version and reproduce the build/install path;
- applicable Installation Information when object code is conveyed in a covered User Product.

Do not publish `.env`, API/OAuth secrets, signing/encryption keys, user databases, sessions, messages, uploads, model caches containing restricted weights, logs or backups. “Corresponding Source” does not mean disclosing private user data.

The source offer must correspond to the version users actually interact with or receive. A link to upstream `main`, a newer development branch, an old tag, or a patch file alone is insufficient.

## Required attribution and legal surfaces

### Notices that must be preserved pending legal review

- the complete upstream `LICENSE` and its no-warranty language;
- upstream copyright/licence notices wherever present;
- accurate adapted-code credits and retained MIT/Apache notices identified at `ACKNOWLEDGMENTS.md:12-38`;
- complete notices/licences for all vendored libraries, fonts, dependencies and distributed images;
- factual source/provenance history, including the upstream repository and baseline commit;
- any upstream Appropriate Legal Notices determined to exist;
- notices imposed by compatible additional terms.

### Proposed modification notice

Counsel should approve and fill the bracketed legal identity before use. A conservative draft is:

> OM Automate is a modified version of the Odysseus software obtained from
> `https://github.com/odysseus-dev/odysseus` at commit
> `9844a2f9a1996b8c8135a9e7bbde6a72f41df5ed`. Modifications for OM Automate
> began on 18 July 2026 and were made by [LEGAL NAME]. The upstream and modified
> covered work is provided under the GNU Affero General Public License as stated
> in the accompanying licence notice. This product is not represented as the
> unmodified upstream project. See Legal & Source for copyright, licence,
> no-warranty, third-party notices and the Corresponding Source for this version.

Do not add a copyright claim over upstream/adapted material. A modifier may identify copyright in its own original contributions only when ownership is established.

### Required application page

Add a prominent **Legal & Source** page/link available before login and from the authenticated application. It should show:

- product version, release identifier and exact source revision;
- the source-download/repository-tag link for that version;
- the applicable AGPL identifier and full licence link/text;
- the modification notice and factual upstream attribution;
- no-warranty notice;
- `THIRD_PARTY_NOTICES` and component SBOM download;
- contact method for source/compliance questions;
- trademark/non-endorsement statement approved by counsel.

The link must be a normal usable UI element, not hidden in developer tools, documentation that is excluded from artifacts, or a transient setup message.

## Third-party inventory requiring completion

| Component group | Current evidence | Gap/action |
|---|---|---|
| Adapted opencode code | `ACKNOWLEDGMENTS.md:22-26`; MIT text under `licenses/` | Map exact adapted files/commits and retain file-level notices |
| Adapted llmfit code | `ACKNOWLEDGMENTS.md:27-32`; MIT text under `licenses/` | Map exact files/version and preserve copyright |
| Tongyi DeepResearch | `ACKNOWLEDGMENTS.md:33-38`; Apache text under `licenses/` | Record version, modified files and any required NOTICE content |
| SearXNG, Chroma, ntfy | `ACKNOWLEDGMENTS.md:42-52`; Compose at `docker-compose.yml:80-149` | Pin digest/version, collect licences/source links, decide whether images are redistributed |
| Vendored JS | `ACKNOWLEDGMENTS.md:54-67` | Hash/version/provenance each bundle; add missing complete licences/notices and preferred source |
| Runtime CDN JS | `ACKNOWLEDGMENTS.md:69-78` | Pin/integrity-check, add to SBOM/notices, consider self-hosting |
| Fira Code, Inter, GohuFont, OpenDyslexic | `ACKNOWLEDGMENTS.md:80-89`; files under `static/fonts/` | Add complete applicable font licences/notices; verify modification/embedding terms |
| Python core/optional dependencies | `ACKNOWLEDGMENTS.md:91-123`; requirement files | Lock full transitive graph and scan exact versions; resolve stale/missing entries |
| PyMuPDF | `requirements-optional.txt:20-25` | Counsel review of version, integration, distribution and any commercial licence |
| Provider logos/names | assets/settings/integrations; branding register BR-009 | Current trademark/brand-guideline review; remove unclear marks |

## Release compliance workflow

1. **Resolve licence identity:** obtain counsel/rightsholder confirmation of AGPL version, copyright chain, additional terms and trademark position.
2. **Correct contradictions:** remove all MIT-core claims and align README, image labels, About/Legal UI, manifests and documentation.
3. **Lock the build:** pin dependencies/images/artifacts and record source/version/digest.
4. **Generate inventory:** produce SBOMs plus a file-level vendored/adapted asset manifest.
5. **Collect notices/source:** add every required full licence/NOTICE and preferred source/build input.
6. **Mark modifications:** add the reviewed modification/date notice without claiming upstream ownership.
7. **Implement source access:** publish exact-version complete source beside every binary/image and through the network UI.
8. **Verify clean-room completeness:** build/install from the offered source without private files; compare functional version metadata to the released artifact.
9. **Review marks and copy:** verify OM Automate ownership/clearance, factual upstream attribution and third-party logo compliance.
10. **Archive evidence:** preserve release artifact/source hashes, SBOM, notice bundle, source URL, build log and counsel decisions for the support life of that release.

## Release gates

Release is blocked until all of the following are true:

- [ ] Qualified counsel has approved the project licence/version and chain-of-title interpretation.
- [ ] No file or product surface claims that the covered core is MIT/permissive.
- [ ] The OM Automate modification/date notice is complete and travels with every format.
- [ ] `LICENSE`, accurate acknowledgements and a complete `THIRD_PARTY_NOTICES` are shipped/accessibly linked.
- [ ] Every vendored asset/dependency/image has known source, exact version/digest and reviewed licence.
- [ ] An exact-version, no-charge source offer is prominent to remote users, including before login.
- [ ] Every binary/container/download has adjacent clear Corresponding Source directions.
- [ ] The source package includes build/install/migration inputs and contains no secrets or user data.
- [ ] User Product Installation Information has been assessed and supplied where applicable.
- [ ] Old and third-party marks are removed or used only under documented permission/factual attribution.
- [ ] “OM Automate” and its logo have written ownership and trademark clearance.
- [ ] Clean-room build, source-link, notices-presence and prohibited-brand/legal-allowlist tests pass.

## Questions reserved for legal counsel

1. Who owns each first-party and adapted contribution, and did every contributor grant the rights needed for AGPL-3.0-or-later?
2. Does the README validly establish “or later” for the whole Program despite absent file headers and contradictory MIT statements?
3. What is the exact boundary of the covered combined work, separate process integrations and Compose aggregate?
4. Do any distribution channels qualify as a User Product requiring Installation Information?
5. What contractor/internal-group arrangements count as non-conveyance for the intended operating model?
6. What obligations attach to the exact PyMuPDF, CalDAV, font, JS bundle and container-image versions selected?
7. What modification/copyright wording may OM Automate use, and what upstream attribution is required?
8. Are the upstream sailboat/name and provider logos protected marks or copyrighted assets, and is the proposed factual attribution sufficient?
9. Is “OM Automate” clear for the intended software/services markets and jurisdictions?
10. Are there export-control, privacy, consumer, email/communications or platform-store terms outside open-source licensing that affect the planned release?

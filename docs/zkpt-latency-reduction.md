# ZKPT Latency Reduction

The current fresh rebuild can produce a real authoritative verified proof on the packaged stack, but the preserved `v2` profile is still too slow for a good product experience on this machine.

## Current measured baseline

- proof boundary: `canonical_segment_mask_v1`
- profile: `v2`
- protocol: `PLONK`
- zkey size: about `1.985 GiB`
- witness generation: about `0.16s`
- verification: about `0.23s`
- proving: about `274.8s`
- total runtime: about `275.6s`

Conclusion: the proving step dominates runtime. Witness generation is not the bottleneck.

## Hard gate before a faster authoritative profile

The repo currently preserves proving artifacts, but not the Circom source and build pipeline needed to generate a smaller authoritative profile. That means:

- we can benchmark and operate the existing profile
- we can keep production fail-closed and truthful
- we cannot honestly regenerate a smaller authoritative profile from this workspace alone

`/health`, `/status`, and `npm run zkpt:benchmark` now surface whether circuit source is present for the selected profile.

## What must be recovered

Before implementing the sub-2-minute profile plan, recover:

- the `.circom` source for the current authoritative circuit
- ceremony/build scripts that regenerate `r1cs`, `wasm`, `zkey`, and `verification_key`
- the exact manifest metadata contract for `profile_class`, `proof_boundary`, and circuit dimensions

Preferred source:

- the archived legacy reference at `D:\BlockVault-Legacy-Reference-20260312-025428`

## Once source is recovered

Generate candidate authoritative profiles that preserve `proof_boundary = canonical_segment_mask_v1` but reduce proving cost:

- fewer canonical segments
- smaller segment size
- lower Merkle depth only if proof semantics are preserved
- fewer policy-rule slots if the legal product boundary still fits

Benchmark every candidate against the current `v2` profile before promotion. Keep `v2` as the reproducible baseline profile.

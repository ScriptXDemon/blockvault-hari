# ZKPT Source Recovery

The fresh rebuild now includes the restored legacy source for the preserved authoritative profile:

- `circuits/zkpt/v2/src/zkpt_redaction_v2.circom`

This restores the missing source boundary that had been blocking profile regeneration work.

## What this enables

- the runtime can now distinguish between opaque artifact-only profiles and source-backed profiles
- the `v2` profile can remain the authoritative baseline while still being reproducible
- new candidate profiles can be generated from the restored source with the same proof boundary

## Build prerequisites

- `circom` on `PATH`
- `snarkjs` on `PATH`
- `npm install --prefix circuits` to provide `circomlib`
- a PTAU file, for example the preserved legacy file under:
  - `D:\BlockVault-Legacy-Reference-20260312-025428\circuits\build\powersOfTau28_hez_final_21.ptau`

## Build command

Example for rebuilding the baseline `v2` profile:

```powershell
python scripts/zkpt/build_profile.py `
  --profile-id v2 `
  --source circuits/zkpt/v2/src/zkpt_redaction_v2.circom `
  --output-dir circuits/zkpt/v2 `
  --ptau D:\BlockVault-Legacy-Reference-20260312-025428\circuits\build\powersOfTau28_hez_final_21.ptau `
  --num-segments 16 `
  --segment-size 1024 `
  --tree-depth 8 `
  --num-policy-rules 8
```

Example for a smaller candidate profile:

```powershell
python scripts/zkpt/build_profile.py `
  --profile-id v3a `
  --source circuits/zkpt/v2/src/zkpt_redaction_v2.circom `
  --output-dir circuits/zkpt/v3a `
  --ptau D:\BlockVault-Legacy-Reference-20260312-025428\circuits\build\powersOfTau28_hez_final_21.ptau `
  --num-segments 4 `
  --segment-size 256 `
  --tree-depth 6 `
  --num-policy-rules 4
```

The current script restores the reproducible build pipeline boundary. If the source itself is parameterized only through the top-level instantiation, adjust the copied source first or add generated variants before benchmarking.

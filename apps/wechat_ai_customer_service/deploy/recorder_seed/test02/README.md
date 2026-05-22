# test02 Recorder Seed Package

This folder is a Git-tracked delivery package for **AI Smart Recorder** seed data.

## Why this exists

`runtime/apps/...` is ignored by `.gitignore`, so runtime migration files cannot be shared through GitHub directly.
This folder provides a stable, downloadable package in the repository.

## Files

- `test02_recorder_only_20260522_145033.zip`
- `install_seed.ps1`

Package SHA256:

`42E1757E5D0ECC8E195CA1DD690DDE4416B5AE246E20C9DC2D469A0DEC980B93`

## Quick install on another machine

1. Clone/download repository.
2. Stop local admin backend and related worker processes.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\apps\wechat_ai_customer_service\deploy\recorder_seed\test02\install_seed.ps1 -WorkspaceRoot "D:\AI\omniauto"
```

4. Restart services.
5. Login and verify recorder data under tenant `test02`.

## Safety scope

- Imports only `payload/runtime/tenants/test02/*`.
- Does **not** auto-overwrite global module bindings.
- Includes optional reference material inside the zip under `optional_reference/`, not auto-applied.

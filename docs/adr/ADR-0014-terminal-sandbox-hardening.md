# ADR-0014 — Terminal sandbox hardening

- **Status:** Accepted — hard-block malformed + lapis regex bahaya + working-dir jail (opt-in) selesai
- **Tanggal:** 2026-07-23
- **Konteks:** Security hardening — audit "terminal server-side tanpa sandbox"
- **Terkait:** `terminal_service.py`, `tool_executor._exec_terminal_execute`, policy_engine (P1-C)

## Konteks
`TerminalService.execute` menjalankan shell via `create_subprocess_shell` dengan
proteksi: izin `RUN_TERMINAL`, blocklist approval **substring** (`_ALWAYS_REQUIRE_
APPROVAL`), timeout, output cap, env-filter. Tiga lubang nyata:
1. **Blocklist substring bypassable** — `rm -fr`/`rm -Rf` (bukan `rm -rf`), fork
   bomb, `curl … | sh`, `> /dev/sdX`, `mkfs.*`, `chmod -R 777 /` lolos.
2. **Working-dir jail DIJANJIKAN docstring** ("terbatas ke allowed_base_dir")
   **tapi TAK ditegakkan** di kode (`effective_cwd = cwd or working_dir`, tanpa
   validasi) — gap doc/kode = agen bisa `cwd` ke path sistem mana pun.
3. **Command malformed** (NUL/control-char) tak ditolak → bisa merusak audit/
   menyelundupkan perintah.

## Keputusan
Tiga lapis, **additive**:
1. **Hard-block malformed** (`_reject_reason`): command > 16KB atau mengandung
   control-char/NUL (kecuali tab/LF/CR) → DITOLAK, tak dieksekusi walau approval.
2. **Lapis regex bahaya** (`_DANGEROUS_REGEX`) di `_needs_approval`, DI ATAS
   substring lama (backward-compat): fork bomb, `rm -fr/-Rf`, `rm` target
   sensitif (`/ ~ * $HOME`), pipe unduhan→shell, tulis ke device blok, mkfs/
   fdisk/parted/wipefs, shutdown/reboot/halt/poweroff/init 0|6, chmod/chown -R /.
   **Reversible** via env `TERMINAL_STRICT_GUARDS=off` (kembali substring-only).
3. **Working-dir jail** (`_jail_cwd`, opt-in `TerminalService(allowed_base_dir=…)`):
   bila di-set, `cwd`/`working_dir` di-realpath & wajib di dalam base (anti
   path-traversal), selain itu ditolak. Default `None` → tanpa jail = **byte-identik**.

## Alternatif
1. **Allowlist first-token (hanya command tertentu boleh).** Ditolak untuk gate ini: agen sah pakai beragam tool (git/npm/python/docker/…); allowlist ketat berisiko blok berat. Blocklist-diperkuat + approval + jail lebih pas dulu.
2. **Ganti `create_subprocess_shell` → exec tanpa shell.** Ditolak: banyak command sah pakai pipe/redirect (`ps aux | grep`); menghapus shell = breaking. Guard di sekelilingnya.
3. **Hard-block + regex + jail opt-in (DIPILIH).** Menutup lubang nyata, reversible, default aman/identik.

## Konsekuensi
**Positif:** varian destruktif yang dulu lolos kini butuh approval; malformed
ditolak; jail menutup gap doc/kode. **Batasan/GOTCHA (JUJUR):** regex bisa
**false-positive** yang menambah approval untuk command sah — mis. `rm` ber-path
absolut (`rm /tmp/lock`) atau glob (`rm *.tmp`) kini minta approval; ini disengaja
(oversight untuk hapus destruktif) & reversible via env. Jail default OFF → belum
menjail kecuali pemanggil (tool_executor/sandbox_manager) mengoper `allowed_base_dir`
(adopsi menyusul). Shell tetap dipakai (pipe/redirect sah) → bukan isolasi penuh
(namespace/container); ini pengerasan, bukan sandbox OS-level.

## Rencana
- **(selesai):** hard-block + regex + jail opt-in + 20 test (regex varian, safe-pipe non-FP, reject, jail, service-level null-byte & cwd luar).
- **berikutnya:** oper `allowed_base_dir` dari pemanggil (workspace per-org); pertimbangkan isolasi OS-level (bwrap/nsjail/container) untuk eksekusi tak-tepercaya; wire policy_engine.check_tool (P1-C.2) di depan terminal.

## Rollback
`TERMINAL_STRICT_GUARDS=off` → deteksi kembali substring-only (perilaku lama).
Jangan oper `allowed_base_dir` → tanpa jail. Hard-block malformed bersifat murni
menambah keamanan (command sah tak terpengaruh).

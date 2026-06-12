# Deploy Permanen `botnesia.id` dengan Cloudflare Tunnel

Dokumen ini adalah runbook produksi untuk memindahkan BotNesia dari Quick Tunnel
`trycloudflare.com` ke **named tunnel** dengan hostname tetap. Prosedur ini tidak
mengubah fitur aplikasi. Origin tetap hanya mendengarkan di `127.0.0.1:8000` dan
PostgreSQL tetap hanya di `127.0.0.1:5432`.

## Target Arsitektur

```text
Pengguna
  -> HTTPS https://app.botnesia.id
  -> Cloudflare Edge + Universal SSL
  -> Named Tunnel botnesia-production
  -> cloudflared (systemd user)
  -> http://127.0.0.1:8000
  -> FastAPI BotNesia
  -> PostgreSQL lokal permanen
```

Hostname produksi yang disarankan adalah `app.botnesia.id`. Domain apex
`botnesia.id` dapat diarahkan ke hostname tersebut memakai Cloudflare Redirect
Rule. Memisahkan apex dan aplikasi memudahkan rollback dan penggunaan domain
untuk landing page di masa depan.

## Kondisi Saat Ini

- API lokal: `http://127.0.0.1:8000`
- PostgreSQL: `~/.local/share/botnesia/postgres/data`
- Quick Tunnel: service `botnesia-tunnel.service`
- URL quick tunnel: `~/.local/share/botnesia/public-url`
- Autostart user systemd: aktif, `Linger=yes`
- Backup database: setiap hari sekitar 03.30 WIB, retensi 14 hari
- `METRICS_AUTH_TOKEN`: sudah dikonfigurasi; jangan tulis nilainya di dokumentasi

Quick Tunnel hanya jalur sementara. URL-nya dapat berubah jika tunnel dibuat
ulang dan tidak memiliki jaminan uptime.

## Prasyarat

- [ ] Domain `botnesia.id` sudah dibeli dan belum kedaluwarsa.
- [ ] Memiliki akses registrar domain.
- [ ] Memiliki akun Cloudflare yang akan menjadi pemilik zone.
- [ ] Nameserver domain dapat diganti ke nameserver Cloudflare.
- [ ] Akses terminal sebagai user `asrory`.
- [ ] API lokal sehat: `curl -fsS http://127.0.0.1:8000/health`.
- [ ] Backup baru berhasil: `./start_all.sh backup`.
- [ ] Jangan menghapus Quick Tunnel sebelum named tunnel lulus seluruh tes.

## Fase 1: Aktifkan DNS Cloudflare

1. Tambahkan `botnesia.id` ke Cloudflare Dashboard.
2. Pilih paket yang diperlukan; paket Free cukup untuk tunnel dasar dan
   Universal SSL.
3. Cloudflare akan memberikan dua authoritative nameserver.
4. Di registrar domain, ganti nameserver lama dengan nameserver Cloudflare.
5. Tunggu status zone menjadi **Active**.
6. Jangan membuat record `A` ke IP rumah. Tunnel tidak memerlukannya.
7. Audit record lama. Hapus record konflik untuk hostname `app` sebelum membuat
   route tunnel.

Checklist DNS:

- [ ] Zone `botnesia.id` berstatus Active.
- [ ] Nameserver registrar sama dengan nameserver Cloudflare.
- [ ] Tidak ada record `A`, `AAAA`, atau `CNAME` konflik pada `app.botnesia.id`.
- [ ] DNSSEC dinyalakan hanya setelah zone aktif dan registrar mendukung DS record.
- [ ] Email record `MX`, SPF, DKIM, dan DMARC tidak dihapus jika domain dipakai email.

Verifikasi:

```bash
dig NS botnesia.id +short
dig A app.botnesia.id +short
dig CNAME app.botnesia.id +short
```

Sebelum route tunnel dibuat, hasil untuk `app.botnesia.id` boleh kosong.

## Fase 2: Buat Named Tunnel

Binary yang digunakan:

```bash
~/.local/bin/cloudflared --version
```

Autentikasi dilakukan interaktif satu kali:

```bash
~/.local/bin/cloudflared tunnel login
```

Browser akan meminta login Cloudflare dan pemilihan zone `botnesia.id`. Setelah
berhasil, file `cert.pem` dibuat di `~/.cloudflared/`. File ini memberi hak
manajemen tunnel/DNS dan harus berizin `600`.

Buat tunnel:

```bash
~/.local/bin/cloudflared tunnel create botnesia-production
~/.local/bin/cloudflared tunnel list
```

Catat UUID tunnel. Perintah tersebut membuat file credential:

```text
~/.cloudflared/<TUNNEL-UUID>.json
```

Amankan credential:

```bash
chmod 700 ~/.cloudflared
chmod 600 ~/.cloudflared/cert.pem
chmod 600 ~/.cloudflared/<TUNNEL-UUID>.json
```

Jangan commit file tersebut ke Git dan jangan kirim isinya lewat chat.

## Fase 3: Konfigurasi Ingress

Gunakan template [config.yml.example](../deploy/cloudflare/config.yml.example).
Buat file aktual:

```bash
mkdir -p ~/.cloudflared
cp deploy/cloudflare/config.yml.example ~/.cloudflared/config.yml
```

Ganti seluruh placeholder:

- `<TUNNEL-UUID>`
- `<HOME>` menjadi `/home/asrory`

Konfigurasi final harus menyerupai:

```yaml
tunnel: <TUNNEL-UUID>
credentials-file: /home/asrory/.cloudflared/<TUNNEL-UUID>.json

ingress:
  - hostname: app.botnesia.id
    service: http://127.0.0.1:8000
    originRequest:
      connectTimeout: 10s
      noHappyEyeballs: false
  - service: http_status:404
```

Rule `http_status:404` wajib menjadi rule terakhir agar hostname yang tidak
terdaftar tidak diteruskan ke aplikasi.

Validasi:

```bash
~/.local/bin/cloudflared tunnel --config ~/.cloudflared/config.yml ingress validate
~/.local/bin/cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://app.botnesia.id
```

## Fase 4: Buat Route DNS

```bash
~/.local/bin/cloudflared tunnel route dns botnesia-production app.botnesia.id
```

Perintah ini membuat CNAME menuju `<TUNNEL-UUID>.cfargotunnel.com`. DNS record
dan proses tunnel bersifat terpisah: record tetap ada ketika tunnel mati, tetapi
pengunjung akan melihat error Cloudflare sampai connector hidup kembali.

Verifikasi:

```bash
dig CNAME app.botnesia.id +short
~/.local/bin/cloudflared tunnel info botnesia-production
```

Jangan mengubah `APP_URL` pada tahap ini.

## Fase 5: Uji Manual Sebelum Cutover

Hentikan sementara quick tunnel hanya ketika siap melakukan tes singkat:

```bash
systemctl --user stop botnesia-tunnel.service
~/.local/bin/cloudflared tunnel \
  --config ~/.cloudflared/config.yml \
  run botnesia-production
```

Dari terminal/perangkat lain:

```bash
curl -fsS https://app.botnesia.id/health
curl -sS -o /dev/null -w '%{http_code}\n' https://app.botnesia.id/dashboard
curl -sS -o /dev/null -w '%{http_code}\n' https://app.botnesia.id/metrics
```

Hasil yang diharapkan:

- `/health`: HTTP `200`, `status=ok`, `db=true`.
- `/dashboard`: HTTP `200`.
- `/metrics` tanpa token: HTTP `401`.
- Login dashboard berhasil.
- Chat, suara, berita, dan upload dokumen diuji dari browser eksternal.

Tekan `Ctrl+C` setelah tes. Jika tes gagal, hidupkan kembali quick tunnel:

```bash
systemctl --user start botnesia-tunnel.service
```

## Fase 6: SSL Cloudflare

Cloudflare Universal SSL umumnya diterbitkan otomatis setelah zone aktif.
Sertifikat mencakup apex dan subdomain tingkat pertama seperti
`app.botnesia.id`; sertifikat dipresentasikan ketika hostname diproxy Cloudflare.
Provisioning dapat memerlukan sekitar 15 menit sampai 24 jam.

Checklist SSL:

- [ ] Cloudflare Dashboard > SSL/TLS > Edge Certificates menunjukkan Universal SSL Active.
- [ ] Mode SSL/TLS tidak disetel `Off`.
- [ ] `Always Use HTTPS` aktif.
- [ ] `Automatic HTTPS Rewrites` dapat diaktifkan.
- [ ] HSTS baru diaktifkan setelah HTTPS stabil dan rollback telah diuji.
- [ ] Tidak memasang sertifikat Let's Encrypt di origin; koneksi origin melalui tunnel lokal HTTP.
- [ ] Browser tidak menunjukkan mixed content.

Verifikasi sertifikat:

```bash
curl -Iv https://app.botnesia.id/health
openssl s_client -connect app.botnesia.id:443 -servername app.botnesia.id </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates
```

## Fase 7: Cutover ENV dan Callback

Setelah hostname lulus tes:

```dotenv
APP_URL=https://app.botnesia.id
GMAIL_REDIRECT_URI=https://app.botnesia.id/integrations/gmail/callback
```

Jangan mengubah token atau secret lain saat cutover domain.

Perbarui callback eksternal secara terpisah bila fitur terkait dipakai:

- Gmail OAuth redirect URI:
  `https://app.botnesia.id/integrations/gmail/callback`
- Meta webhook:
  `https://app.botnesia.id/webhooks/meta`
- Telegram webhook dibuat aplikasi dari `APP_URL`.
- Midtrans:
  `https://app.botnesia.id/api/billing/webhooks/midtrans`
- Xendit:
  `https://app.botnesia.id/api/billing/webhooks/xendit`

Setelah mengubah `.env`:

```bash
systemctl --user restart botnesia-api.service
```

## Fase 8: Autostart Named Tunnel

Gunakan template
[botnesia-tunnel-named.service.example](../deploy/cloudflare/botnesia-tunnel-named.service.example).

Backup unit quick tunnel saat ini:

```bash
cp ~/.config/systemd/user/botnesia-tunnel.service \
  ~/.config/systemd/user/botnesia-tunnel.quick.service.backup
```

Pasang named tunnel:

```bash
cp deploy/cloudflare/botnesia-tunnel-named.service.example \
  ~/.config/systemd/user/botnesia-tunnel.service
systemctl --user daemon-reload
systemctl --user enable botnesia-tunnel.service
systemctl --user restart botnesia-tunnel.service
```

Verifikasi:

```bash
systemctl --user is-enabled botnesia-postgres.service botnesia-api.service botnesia-tunnel.service
systemctl --user is-active botnesia-postgres.service botnesia-api.service botnesia-tunnel.service
loginctl show-user "$USER" -p Linger
journalctl --user -u botnesia-tunnel.service -n 100 --no-pager
~/.local/bin/cloudflared tunnel info botnesia-production
```

Hasil yang diharapkan: ketiga service `enabled` dan `active`, serta `Linger=yes`.

## Fase 9: Apex Domain

Pilihan yang disarankan:

- `app.botnesia.id`: aplikasi BotNesia.
- `botnesia.id`: redirect permanen ke `https://app.botnesia.id`.

Buat Cloudflare Redirect Rule:

```text
Jika hostname equals botnesia.id
Redirect dinamis ke https://app.botnesia.id${uri.path}
Status 301
Preserve query string
```

Jangan menambahkan apex ke ingress tunnel jika hanya diperlukan sebagai redirect.

## Checklist Go-Live

- [ ] Backup database baru dibuat dan dapat dibaca `pg_restore -l`.
- [ ] Named tunnel status Healthy.
- [ ] `app.botnesia.id` resolve melalui Cloudflare.
- [ ] Universal SSL Active.
- [ ] Dashboard HTTP 200.
- [ ] Health HTTP 200 dan database sehat.
- [ ] Login berhasil dari jaringan seluler.
- [ ] Chat menghasilkan jawaban.
- [ ] Audio dapat diputar sampai selesai.
- [ ] Berita memiliki sumber/link.
- [ ] `/metrics` tanpa token menghasilkan 401.
- [ ] Webhook yang digunakan sudah diperbarui.
- [ ] `APP_URL` menggunakan hostname permanen.
- [ ] Quick tunnel tetap tersedia sebagai rollback selama minimal 48 jam.
- [ ] Log tunnel tidak berisi loop reconnect/error 1016.

## Rollback Jika Domain Gagal

Rollback ini tidak menyentuh database.

### Rollback cepat ke Quick Tunnel

1. Hentikan named tunnel:

```bash
systemctl --user stop botnesia-tunnel.service
```

2. Pulihkan unit quick tunnel:

```bash
cp ~/.config/systemd/user/botnesia-tunnel.quick.service.backup \
  ~/.config/systemd/user/botnesia-tunnel.service
systemctl --user daemon-reload
systemctl --user restart botnesia-tunnel.service
```

3. Ambil URL baru:

```bash
cat ~/.local/share/botnesia/public-url
```

4. Kembalikan `.env`:

```dotenv
APP_URL=https://<URL-QUICK-TUNNEL>.trycloudflare.com
```

5. Restart API:

```bash
systemctl --user restart botnesia-api.service
```

### Rollback DNS saja

Jika named tunnel sehat tetapi hostname salah:

1. Buka Cloudflare Dashboard > `botnesia.id` > DNS > Records.
2. Hapus CNAME `app` yang menunjuk ke `<TUNNEL-UUID>.cfargotunnel.com`.
3. Jangan menghapus tunnel atau file credential sampai diagnosis selesai.
4. Jika perlu membuat ulang route, jalankan:

```bash
~/.local/bin/cloudflared tunnel route dns botnesia-production app.botnesia.id
```

Versi `cloudflared` yang terpasang menyediakan pembuatan route DNS, tetapi tidak
menyediakan subcommand CLI `delete`; karena itu rollback record dilakukan dari
Dashboard atau Cloudflare DNS API.

### Rollback service tanpa quick tunnel

Aplikasi tetap dapat digunakan lokal:

```bash
systemctl --user stop botnesia-tunnel.service
curl -fsS http://127.0.0.1:8000/health
```

### Kriteria rollback

Rollback segera bila salah satu kondisi berikut terjadi lebih dari 10 menit:

- DNS `SERVFAIL`/`NXDOMAIN` setelah seharusnya aktif.
- Cloudflare error `1016`, `502`, `530`, atau reconnect terus-menerus.
- Universal SSL belum aktif dan browser menolak sertifikat.
- Login/callback OAuth gagal setelah URL diperbarui.
- Dashboard publik gagal tetapi health lokal tetap sehat.

## Troubleshooting Singkat

### Error 1016

DNS menunjuk ke tunnel tetapi connector tidak aktif atau UUID salah.

```bash
systemctl --user status botnesia-tunnel.service
~/.local/bin/cloudflared tunnel info botnesia-production
journalctl --user -u botnesia-tunnel.service -n 150 --no-pager
```

### Error 502

Tunnel aktif, tetapi origin API tidak dapat dijangkau.

```bash
curl -fsS http://127.0.0.1:8000/health
systemctl --user status botnesia-api.service
```

### DNS belum berubah

```bash
dig NS botnesia.id +short
dig CNAME app.botnesia.id +short @1.1.1.1
```

### SSL pending

Pastikan zone Active dan record diproxy. Tunggu sampai 24 jam sebelum menganggap
penerbitan gagal. Jangan aktifkan HSTS selama sertifikat belum stabil.

## Referensi Resmi

- Cloudflare: Create a locally-managed tunnel
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/
- Cloudflare: Tunnel configuration file
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/
- Cloudflare: Route DNS records to a tunnel
  https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/
- Cloudflare: Universal SSL
  https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/enable-universal-ssl/

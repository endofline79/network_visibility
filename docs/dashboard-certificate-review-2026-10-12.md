# Dashboard certificate review — 2026-10-12

The live dashboard at `https://192.168.5.230:8096/` presents a valid certificate
for that address. The workstation initially did not trust its issuing CA,
causing the browser's `ERR_CERT_AUTHORITY_INVALID` warning. The initial review was
read-only. After user approval, the verified CA was imported into the user's
NSS trust store as recorded below. After the user relaunched the app, the live
dashboard loaded successfully and browser refreshes were verified.

The layout deployment completed; its health check reports live mode. The earlier
Demo label belonged to the local preview at `http://127.0.0.1:8107/`. See the
[release record](layout-release-2026-10-12.md) for deployment validation.

## Initial review findings, before import

| Check | Result |
| --- | --- |
| Subject / issuer | `ai-02-visibility` / `ai-02-telemetry` |
| Address coverage | SAN includes `192.168.5.230`, `ai-02`, `localhost`, and `127.0.0.1` |
| Leaf validity | October 6, 2026 00:03:47 UTC through January 4, 2027 00:03:47 UTC |
| Certificate purpose | Non-CA certificate; TLS web server authentication |
| Strict chain, purpose, and IP validation | Pass using the deployment CA |
| Live TLS connection | TLS 1.3, `TLS_AES_256_GCM_SHA384` |
| Served certificate versus AI-02 file | SHA256 fingerprints match |
| Local deployment CA versus AI-02 CA file | SHA256 fingerprints match |
| Default workstation trust | Fails with code 20, `unable to get local issuer certificate` |
| User NSS database | Contains `Home Management CA 2026`; does not contain the dashboard CA |

The existing Home Management CA is a different issuer and does not validate
the dashboard certificate. The certificate was issued before the layout release;
that release preserved the certificate mounts and runtime settings.

Leaf SHA256 fingerprint:

```text
64:ED:28:31:E8:FC:DA:33:FA:38:7F:E4:42:C1:83:48:6B:C1:39:1F:35:48:44:10:E9:B3:08:D9:D7:CC:A4:AA
```

Deployment root CA SHA256 fingerprint:

```text
C7:24:63:32:49:F3:6F:55:A8:87:07:1B:03:58:DA:F1:DC:E3:4C:A2:14:53:DC:BE:9D:FD:D6:93:2A:91:DA:4D
```

The root is valid through September 25, 2027 00:32:52 UTC. Its public certificate
is `/home/klab/Documents/Codex/2026-10-04/task/visibility-deployment/Visibility-Root-CA.crt`.
The corresponding file on AI-02 is
`/home/klab/.local/share/visibility/presentation/dashboard-ca.crt`.
The original telemetry certificate has the same common name but a different
fingerprint; select the dashboard root by fingerprint, not common name alone.

## Approved correction — imported and browser verified

The user approved importing the verified dashboard root. The import completed
on October 12, 2026 at 21:43:25 EDT (October 13, 01:43:25 UTC) in
`sql:/home/klab/.pki/nssdb`, with nickname `Visibility Dashboard CA 2026` and
trust flags `C,,`. The exported imported certificate matches the expected
SHA256 fingerprint, and the existing Home Management CA certificate is
unchanged. No AI-02 service restart, deployment, or system-wide trust change
was performed. This trusts TLS server certificates issued by the CA, beyond
this one dashboard address.

[Chromium's Linux certificate documentation](https://chromium.googlesource.com/chromium/src/+/master/docs/linux/cert_management.md)
describes the NSS shared database and the `C,,` trust flag for server-issuing
roots. This workstation already has `/home/klab/.pki/nssdb`, which Chromium's
documented path selection preserves. In-app browser acceptance was verified
after the application relaunch; no certificate warning was bypassed.

Executed import, after rechecking the fingerprint and confirming the nickname
was unused:

```bash
certutil -A -d sql:/home/klab/.pki/nssdb \
  -n 'Visibility Dashboard CA 2026' -t 'C,,' \
  -i /home/klab/Documents/Codex/2026-10-04/task/visibility-deployment/Visibility-Root-CA.crt
```

Rollback removes only that newly added trust entry:

```bash
certutil -D -d sql:/home/klab/.pki/nssdb \
  -n 'Visibility Dashboard CA 2026'
```

The running in-app browser initially still reported `ERR_CERT_AUTHORITY_INVALID` after
the import. Its error page uses a `data:` URL, which browser automation policy
blocks; further inspection of that page was stopped. The user then relaunched
the application. At approximately 21:46 EDT on October 12, the live page was
accessible at its original HTTPS address, with an authenticated session and
current telemetry. This is consistent with the running app needing a fresh
launch to recognize the import. The
[official browser documentation](https://learn.chatgpt.com/docs/browser)
does not specify a certificate-trust refresh procedure.

If this recurs, inspect the active trust configuration before making additional
changes. A longer-term alternative is to issue the dashboard certificate from the
already trusted Home Management CA, if its issuance workflow is available.

## Reproduce and close out

Read-only verification from the repository root:

```bash
openssl verify -x509_strict -purpose sslserver -verify_ip 192.168.5.230 \
  -CAfile /home/klab/Documents/Codex/2026-10-04/task/visibility-deployment/Visibility-Root-CA.crt \
  state/certificate-review-20261012/served-certificate.pem
certutil -L -d sql:/home/klab/.pki/nssdb
```

Local evidence is in `state/certificate-review-20261012/`, including the served
public certificate and TLS review JSON. `trust-import.json` and the before/after
NSS listings record the approved import. The live TLS check was recorded at
2026-10-13 01:37:22 UTC (October 12, 21:37:22 EDT). No private keys were read.

After the application relaunch, verified the live page loads without a certificate
warning or Demo label. The signed-in dashboard displayed 18 devices and 522
destinations for the last hour. Refresh data completed, and successive map
observations changed from 146 to 145, 147, and 151 public endpoints with recent
check timestamps and newest flows within seconds. The accepted three-pane
layout, right-hand tabs, and consolidated bottom country selector were visible.
The existing Kitchen capture limitation remains. Browser verification is complete.

Renewal automation was not audited; the leaf must be renewed before its January
4 UTC expiry. Renewal readiness remains a separate follow-up.

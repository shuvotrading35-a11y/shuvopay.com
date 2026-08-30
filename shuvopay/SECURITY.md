# Security Policy

## Responsible Disclosure

If you discover a security vulnerability in ShuvoPay, please report it responsibly:

**Email:** security@shuvopay.com  
**Response time:** Within 72 hours  
**Do NOT** open a public GitHub issue for security vulnerabilities.

Please include:
- Description of the vulnerability and potential impact
- Steps to reproduce
- Any relevant code, screenshots, or logs
- Your contact information (for follow-up)

We commit to:
- Acknowledge receipt within 72 hours
- Provide a status update within 7 days
- Credit you in the changelog (if desired) after the fix is deployed
- Not take legal action against researchers acting in good faith

---

## Security Design Decisions

### Why RS256 (asymmetric JWT) instead of HS256?

RS256 uses a private key to sign and a public key to verify. This means:
- The public key can be distributed to any service that needs to verify tokens
- Only the backend (which holds the private key) can issue tokens
- Compromise of a verification endpoint does not expose the signing key

### Why per-device API keys instead of sharing merchant credentials?

Each Android device receives its own API key (PBKDF2-hashed in the database). This means:
- A compromised device key can be revoked without affecting other devices or the merchant account
- Rate limiting can be applied per-device
- Audit logs identify which device uploaded each SMS

### Why PBKDF2 for device keys instead of bcrypt?

Device keys are long random strings (~48 bytes of entropy). PBKDF2 with 200,000 rounds is appropriate here. We use bcrypt for user passwords (shorter, human-chosen values) where its adaptive cost factor is more valuable.

### Why is SMS data encrypted at rest?

SMS messages may contain sensitive financial information. Even if the database is compromised, raw SMS content is unreadable without the AES-256-GCM key stored separately in environment variables (and ideally in a secrets manager like HashiCorp Vault or AWS Secrets Manager in production).

### Why is the webhook secret stored bcrypt-hashed?

The webhook secret is used to sign outbound payloads. It is shown to the merchant exactly once at creation time. Storing it hashed means even a full database dump cannot be used to forge webhooks on behalf of a merchant. The tradeoff is that we cannot re-show the secret — merchants must rotate if they lose it.

### Why replay protection on SMS reports?

Without replay protection, a network attacker who captures a legitimate SMS report could replay it to artificially match multiple invoices. The `X-Request-ID` header (UUID, stored in Redis with 24h TTL) makes each request unique and idempotent.

### Why is the audit log immutable (no DELETE endpoint)?

The audit log is the authoritative record of all sensitive actions in the system. Making it append-only (even for admins) provides non-repudiation and meets compliance requirements for financial platforms. In production, consider writing audit logs to a separate append-only data store or WORM storage.

### Android: why no screen scraping or Accessibility Service?

ShuvoPay reads only SMS delivered directly to the device via the `SMS_RECEIVED` broadcast — the standard, documented Android API. We explicitly do not use Accessibility Services (which would allow reading any on-screen text), not screen capture, and not unofficial carrier APIs. This limits scope strictly to the device owner's own incoming messages.

---

## Known Limitations

1. **OEM background restrictions:** Xiaomi/MIUI, Samsung OneUI, and Oppo/ColorOS aggressively kill background processes. The app provides guidance and deep links to relevant settings, but cannot guarantee delivery on all devices without user configuration.

2. **SMS spoofing:** The parser trusts the sender ID field in the SMS. While most carriers filter spoofed sender IDs, a sophisticated attacker with carrier access could craft a fake payment SMS. The match engine's time-window and amount constraints reduce (but do not eliminate) this risk. For high-value transactions, enable receiver account matching to add a third factor.

3. **Device clock skew:** SMS timestamps use the device clock. If the device clock is significantly wrong, time-window matching may fail. The app shows a warning if the clock appears skewed.

4. **Single point of failure (device):** If the device is offline or the app is killed, SMS are queued locally. Invoices with short time windows may expire before the device comes back online. Use multiple devices per merchant account for critical deployments.

# ShuvoPay Webhook Consumer Guide

ShuvoPay sends HMAC-SHA256 signed webhook events to your endpoint when a payment is confirmed, a match requires review, or a webhook test is triggered.

---

## Webhook Payload

```json
{
  "event": "payment.confirmed",
  "invoice_id": "a1b2c3d4-...",
  "invoice_number": "INV-1A2B3C4D",
  "merchant_id": "...",
  "status": "paid",
  "amount": 500.00,
  "currency": "BDT",
  "provider": "bKash",
  "transaction_id": "TRX0001234567",
  "matched_at": "2025-08-15T14:23:11Z",
  "confidence": 0.98
}
```

## Request Headers

```
Content-Type: application/json
X-ShuvoPay-Signature: sha256=<hmac_hex>
X-ShuvoPay-Timestamp: <unix_epoch>
X-Webhook-ID: <uuid>
User-Agent: ShuvoPay-Webhook/1.0
```

---

## Signature Verification

### How it works

1. ShuvoPay computes `HMAC-SHA256(payload_bytes, your_signing_secret)`
2. Sends result as `X-ShuvoPay-Signature: sha256=<hex>`
3. **Your server must verify this before processing the event**
4. Also check `X-ShuvoPay-Timestamp` is within 5 minutes (replay protection)

Your signing secret is shown **once** when you configure your webhook URL. Store it securely.

---

### Python (Flask)

```python
import hashlib
import hmac
import time
from flask import Flask, request, abort

app = Flask(__name__)
WEBHOOK_SECRET = "whsec_your_secret_here"

def verify_shuvopay_webhook(body: bytes, signature: str, timestamp: str) -> bool:
    # Reject if timestamp is more than 5 minutes old
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > 300:
            return False
    except (ValueError, TypeError):
        return False

    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    body = request.get_data()
    signature = request.headers.get("X-ShuvoPay-Signature", "")
    timestamp = request.headers.get("X-ShuvoPay-Timestamp", "")

    if not verify_shuvopay_webhook(body, signature, timestamp):
        abort(401, "Invalid signature")

    event = request.get_json()

    if event["event"] == "payment.confirmed":
        invoice_id = event["invoice_id"]
        amount = event["amount"]
        provider = event["provider"]
        transaction_id = event["transaction_id"]
        print(f"Payment confirmed: {invoice_id} | {provider} | BDT {amount} | TrxID {transaction_id}")
        # TODO: Update your database, fulfill the order, etc.

    return "", 200
```

---

### PHP (Laravel)

```php
<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Http\Response;

class ShuvopayWebhookController extends Controller
{
    private string $secret;

    public function __construct()
    {
        $this->secret = config('services.shuvopay.webhook_secret');
    }

    public function handle(Request $request): Response
    {
        $body = $request->getContent();
        $signature = $request->header('X-ShuvoPay-Signature', '');
        $timestamp = $request->header('X-ShuvoPay-Timestamp', '');

        if (!$this->verifySignature($body, $signature, $timestamp)) {
            return response('Invalid signature', 401);
        }

        $event = $request->json()->all();

        match ($event['event']) {
            'payment.confirmed' => $this->handlePaymentConfirmed($event),
            default => null,
        };

        return response('', 200);
    }

    private function verifySignature(string $body, string $signature, string $timestamp): bool
    {
        // Reject stale timestamps (replay protection)
        if (abs(time() - (int) $timestamp) > 300) {
            return false;
        }

        $expected = 'sha256=' . hash_hmac('sha256', $body, $this->secret);
        return hash_equals($expected, $signature);
    }

    private function handlePaymentConfirmed(array $event): void
    {
        \Log::info('ShuvoPay payment confirmed', [
            'invoice_id'     => $event['invoice_id'],
            'amount'         => $event['amount'],
            'provider'       => $event['provider'],
            'transaction_id' => $event['transaction_id'],
            'confidence'     => $event['confidence'],
        ]);
        // Update order status, send confirmation email, etc.
    }
}
```

Add to `routes/api.php`:
```php
Route::post('/webhook/shuvopay', [ShuvopayWebhookController::class, 'handle']);
```

---

### Node.js (Express)

```javascript
const express = require('express');
const crypto = require('crypto');

const app = express();
const WEBHOOK_SECRET = process.env.SHUVOPAY_WEBHOOK_SECRET;

// Use raw body for signature verification
app.use('/webhook', express.raw({ type: 'application/json' }));

function verifySignature(body, signature, timestamp) {
  // Reject if timestamp is >5 minutes old
  const ts = parseInt(timestamp, 10);
  if (isNaN(ts) || Math.abs(Date.now() / 1000 - ts) > 300) {
    return false;
  }

  const expected = 'sha256=' + crypto
    .createHmac('sha256', WEBHOOK_SECRET)
    .update(body)
    .digest('hex');

  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(signature),
  );
}

app.post('/webhook', (req, res) => {
  const signature = req.headers['x-shuvopay-signature'] || '';
  const timestamp = req.headers['x-shuvopay-timestamp'] || '';

  if (!verifySignature(req.body, signature, timestamp)) {
    return res.status(401).json({ error: 'Invalid signature' });
  }

  const event = JSON.parse(req.body);

  if (event.event === 'payment.confirmed') {
    console.log('Payment confirmed:', {
      invoiceId: event.invoice_id,
      amount: event.amount,
      provider: event.provider,
      transactionId: event.transaction_id,
      confidence: event.confidence,
    });
    // Fulfill order, update database, etc.
  }

  res.status(200).end();
});

app.listen(3000, () => console.log('Webhook server listening on port 3000'));
```

---

## Event Types

| Event | When it fires |
|---|---|
| `payment.confirmed` | Invoice matched with confidence ≥ 0.95 and approved |
| `webhook.test` | When you click "Send Test" in the Merchant Panel |

---

## Retry Behavior

If your endpoint returns a non-2xx response or times out, ShuvoPay retries with exponential backoff:

| Attempt | Delay |
|---|---|
| 1 | 10 seconds |
| 2 | 30 seconds |
| 3 | 2 minutes |
| 4 | 10 minutes |
| 5 | 30 minutes |
| 6 | 2 hours |
| 7 | 6 hours |

After 7 failed attempts, the webhook is marked **dead** and admin is alerted. You can manually retry dead webhooks from the Merchant Panel → Webhooks → Delivery Logs.

**Your endpoint should respond within 10 seconds.** For time-consuming processing, respond with 200 immediately and process asynchronously.

---

## Idempotency

Each webhook delivery includes a unique `X-Webhook-ID` header. Store this ID and check for duplicates to handle retried deliveries safely.

```python
webhook_id = request.headers.get("X-Webhook-ID")
if WebhookDelivery.objects.filter(webhook_id=webhook_id).exists():
    return HttpResponse(status=200)  # Already processed
WebhookDelivery.objects.create(webhook_id=webhook_id)
# ... process event
```

---

## Security Checklist

- [ ] Verify `X-ShuvoPay-Signature` on every request
- [ ] Reject requests where `X-ShuvoPay-Timestamp` is >5 minutes old
- [ ] Use `hmac.compare_digest` / `crypto.timingSafeEqual` (not `==`) to prevent timing attacks
- [ ] Store your webhook secret in environment variables, not source code
- [ ] Respond with 200 quickly; process asynchronously for slow operations
- [ ] Store `X-Webhook-ID` to deduplicate retried deliveries

# ShuvoPay — System Design

## System Flow

```mermaid
flowchart TD
    A[Android Device\nSMS BroadcastReceiver] -->|Parse + Encrypt| B[Room DB\nOffline Queue]
    B -->|WorkManager\nExponential Backoff| C[HTTPS + JWT + AES\nX-Device-Key Header\nX-Request-ID Replay Guard]
    C --> D[FastAPI Backend\n/api/v1/sms/report]
    D --> E[Match Engine\nCelery Worker\nAsync Scoring]
    E -->|Invoice Status Update| F[(PostgreSQL\nAES-256 at rest)]
    E -->|Confidence ≥ 0.95| G[WebSocket Push\n/ws/merchant/{id}]
    E -->|HMAC-SHA256 signed| H[Webhook Delivery\nRetry Queue\nRQ Worker]
    G --> I[Merchant Panel\nNext.js - Live Updates]
    H --> J[Merchant's Server\nWebhook Consumer]
    F --> K[Admin Panel\nNext.js - Full Visibility]
    D --> L[Redis\nRate Limit + Replay Cache]
```

## Android Processing Pipeline

```mermaid
flowchart TD
    R[SMS Received\nBroadcastReceiver] --> S[SmsProcessingService\nForeground - Persistent Notification]
    S --> P[SmsParserEngine\nRegex Rule Matching\nJSON Rules from Backend]
    P -->|Parsed Fields| Q[Room Database\nStatus: PENDING\nEncrypted raw_sms]
    Q --> U[SmsUploadWorker\nWorkManager\n15s→30s→1m→5m→15m backoff]
    U -->|Success| V[Status: UPLOADED]
    U -->|Failure| W[Status: FAILED\nRetry scheduled]
    Q --> DASH[Dashboard\nQueue depth badge\nRecent activity feed]
```

## Database ERD

```mermaid
erDiagram
    USERS {
        uuid id PK
        varchar email
        varchar password_hash
        varchar role
        varchar totp_secret
        bool totp_enabled
        bool is_active
        timestamp created_at
        timestamp updated_at
        timestamp deleted_at
    }
    MERCHANTS {
        uuid id PK
        uuid user_id FK
        varchar name
        varchar webhook_url
        varchar webhook_secret_hash
        bool is_active
        timestamp created_at
        timestamp updated_at
        timestamp deleted_at
    }
    DEVICES {
        uuid id PK
        uuid merchant_id FK
        varchar name
        varchar fingerprint
        varchar fcm_token
        varchar status
        timestamp last_seen
        timestamp created_at
    }
    DEVICE_API_KEYS {
        uuid id PK
        uuid device_id FK
        varchar key_hash
        timestamp expires_at
        bool is_active
        timestamp created_at
    }
    SMS_LOGS {
        uuid id PK
        uuid device_id FK
        uuid merchant_id FK
        text raw_sms_encrypted
        varchar provider
        varchar transaction_id
        numeric amount
        varchar currency
        varchar sender_number
        varchar receiver_account
        timestamp sms_timestamp
        float parse_confidence
        varchar status
        timestamp created_at
    }
    INVOICES {
        uuid id PK
        uuid merchant_id FK
        varchar invoice_number
        numeric amount
        varchar currency
        varchar provider
        varchar receiver_account
        varchar status
        interval time_window
        timestamp expires_at
        timestamp created_at
        timestamp updated_at
        timestamp deleted_at
    }
    PAYMENT_MATCHES {
        uuid id PK
        uuid invoice_id FK
        uuid sms_log_id FK
        float confidence_score
        jsonb scoring_breakdown
        varchar status
        varchar reviewed_by
        timestamp matched_at
        timestamp reviewed_at
    }
    WEBHOOKS {
        uuid id PK
        uuid merchant_id FK
        uuid payment_match_id FK
        jsonb payload
        varchar status
        int attempt_count
        timestamp next_retry_at
        timestamp last_attempted_at
        timestamp created_at
    }
    AUDIT_LOGS {
        uuid id PK
        uuid actor_id FK
        varchar action
        varchar resource_type
        varchar resource_id
        inet ip_address
        text user_agent
        jsonb metadata
        timestamp created_at
    }
    PARSER_RULES {
        uuid id PK
        uuid merchant_id FK
        varchar rule_id
        varchar provider
        varchar sender_pattern
        text message_pattern
        jsonb fields
        varchar currency
        varchar direction
        bool enabled
        timestamp created_at
        timestamp updated_at
    }
    API_KEYS {
        uuid id PK
        uuid merchant_id FK
        varchar key_hash
        varchar label
        varchar scope
        timestamp expires_at
        bool is_active
        timestamp created_at
    }

    USERS ||--o{ MERCHANTS : "has"
    MERCHANTS ||--o{ DEVICES : "owns"
    MERCHANTS ||--o{ INVOICES : "creates"
    MERCHANTS ||--o{ API_KEYS : "has"
    MERCHANTS ||--o{ PARSER_RULES : "configures"
    DEVICES ||--o{ DEVICE_API_KEYS : "has"
    DEVICES ||--o{ SMS_LOGS : "uploads"
    INVOICES ||--o{ PAYMENT_MATCHES : "matched_by"
    SMS_LOGS ||--o{ PAYMENT_MATCHES : "matches"
    PAYMENT_MATCHES ||--o{ WEBHOOKS : "triggers"
    USERS ||--o{ AUDIT_LOGS : "generates"
```

## Match Engine Flow

```mermaid
flowchart TD
    A[New SMS Uploaded\nCelery Task Enqueued] --> B[Fetch Open Invoices\nSame Provider + Merchant]
    B --> C{Any candidates?}
    C -->|No| D[Status: UNMATCHED\nInvoice stays PENDING]
    C -->|Yes| E[Score Each Candidate]
    E --> F{Amount match?}
    F -->|Yes +0.35| G{Time window?}
    F -->|No| ZERO[Score: 0 for this invoice]
    G -->|Yes +0.30| H{TrxID unique?}
    G -->|No| LOW[Low score]
    H -->|Yes +0.25| I{Receiver match?}
    H -->|No| ZERO2[Score: 0 - duplicate]
    I -->|Yes/NA +0.10| SCORE[Final Score]
    SCORE --> J{Score ≥ 0.95?}
    J -->|Yes, 1 match| K[PAID\nUpdate Invoice\nEnqueue Webhook\nPush WebSocket\nWrite Audit]
    J -->|Yes, multiple| L[REVIEW_REQUIRED\nAmbiguous - admin queue]
    J -->|No| M[REVIEW_REQUIRED\nLow confidence - admin queue]
```

## Webhook Delivery

```mermaid
sequenceDiagram
    participant ME as Match Engine
    participant WQ as Webhook Queue (RQ)
    participant WW as Webhook Worker
    participant MS as Merchant's Server
    participant DB as PostgreSQL

    ME->>DB: Insert webhook record (status: PENDING)
    ME->>WQ: Enqueue delivery task
    WW->>DB: Fetch webhook payload
    WW->>WW: Sign with HMAC-SHA256
    WW->>MS: POST /your-webhook-url
    alt Success (2xx)
        MS-->>WW: 200 OK
        WW->>DB: status=DELIVERED
    else Failure
        MS-->>WW: 4xx/5xx or timeout
        WW->>DB: attempt++, next_retry = now + backoff
        Note over WW: 10s→30s→2m→10m→30m→2h→6h
        WW->>WQ: Re-enqueue at next_retry
    end
    alt All 7 attempts exhausted
        WW->>DB: status=DEAD
        WW->>WQ: Alert admin notification
    end
```

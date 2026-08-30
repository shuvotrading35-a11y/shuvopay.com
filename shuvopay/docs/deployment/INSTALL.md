# ShuvoPay — Fresh VPS Installation Guide

From a clean Ubuntu 22.04 LTS server to a fully running ShuvoPay instance in under 30 commands.

---

## Prerequisites

- Ubuntu 22.04 LTS VPS (2 vCPU, 4GB RAM minimum)
- Domain name pointed at your server's IP
- Port 80 and 443 open in firewall

---

## Step-by-Step Installation

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# 3. Install Docker Compose v2
sudo apt install -y docker-compose-plugin

# 4. Install Certbot (Let's Encrypt SSL)
sudo apt install -y certbot

# 5. Obtain SSL certificate BEFORE starting Nginx
sudo certbot certonly --standalone -d yourdomain.com -d api.yourdomain.com \
  --email you@email.com --agree-tos --non-interactive

# 6. Clone the repository
git clone https://github.com/yourorg/shuvopay.git /opt/shuvopay
cd /opt/shuvopay

# 7. Copy and configure environment
cp .env.example .env

# 8. Generate RSA key pair for JWT
openssl genrsa -out /opt/shuvopay/private.pem 2048
openssl rsa -in /opt/shuvopay/private.pem -pubout -out /opt/shuvopay/public.pem

# 9. Generate AES encryption key (32 bytes = 64 hex chars)
python3 -c "import secrets; print(secrets.token_hex(32))"
# → Copy output to AES_ENCRYPTION_KEY in .env

# 10. Edit .env with your actual values
nano .env
# Required changes:
#   POSTGRES_PASSWORD=<strong random password>
#   REDIS_PASSWORD=<strong random password>
#   JWT_PRIVATE_KEY=<contents of private.pem>
#   JWT_PUBLIC_KEY=<contents of public.pem>
#   AES_ENCRYPTION_KEY=<64 hex chars from step 9>
#   ADMIN_EMAIL=your@email.com
#   ADMIN_PASSWORD=<strong password>
#   CORS_ORIGINS=https://yourdomain.com
#   ALLOWED_HOSTS=yourdomain.com,api.yourdomain.com

# 11. Update Nginx config with your domain
sed -i 's/shuvopay.com/yourdomain.com/g' infrastructure/nginx/nginx.conf

# 12. Pull all Docker images
docker compose pull

# 13. Start database and Redis first
docker compose up -d postgres redis
sleep 10

# 14. Run database migrations
docker compose run --rm backend alembic upgrade head

# 15. Seed initial data (admin user + parser rules)
docker compose run --rm backend python scripts/seed.py

# 16. Start all services
docker compose up -d

# 17. Verify health
curl https://api.yourdomain.com/health
curl https://api.yourdomain.com/health/ready

# 18. Check all containers are running
docker compose ps

# 19. Set up automatic SSL renewal (cron)
echo "0 12 * * * root certbot renew --quiet --deploy-hook 'docker compose -f /opt/shuvopay/docker-compose.yml restart nginx'" \
  | sudo tee /etc/cron.d/certbot-renew

# 20. Set up log rotation
sudo tee /etc/logrotate.d/shuvopay > /dev/null <<EOF
/opt/shuvopay/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
}
EOF

# 21. Enable Docker to start on boot
sudo systemctl enable docker

echo "✓ ShuvoPay is running!"
echo "  Merchant Panel: https://yourdomain.com/merchant/"
echo "  Admin Panel:    https://yourdomain.com/admin/"
echo "  API Docs:       https://api.yourdomain.com/docs (dev only)"
echo "  Grafana:        http://your-server-ip:3003"
```

---

## Post-Install

1. **Log in to Admin Panel** at `/admin/` with your `ADMIN_EMAIL` + `ADMIN_PASSWORD`
2. **Create merchant accounts** via Admin → Users → Create User
3. **Install Android app** and register devices under each merchant account
4. **Configure webhook URLs** per merchant via Merchant Panel → Webhooks

---

## Firewall Configuration

```bash
# Allow only necessary ports
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
# Grafana (restrict to your IP in production)
sudo ufw allow from YOUR_IP to any port 3003
sudo ufw enable
```

---

## Troubleshooting

```bash
# View logs for a specific service
docker compose logs -f backend
docker compose logs -f worker
docker compose logs -f nginx

# Restart a single service
docker compose restart backend

# Shell into backend container
docker compose exec backend bash

# Manual DB migration
docker compose exec backend alembic upgrade head

# Check Redis
docker compose exec redis redis-cli -a $REDIS_PASSWORD ping
```

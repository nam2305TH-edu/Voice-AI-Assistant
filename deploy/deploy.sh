
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check domain argument
if [ -z "$1" ]; then
    echo -e "${RED}Error: Domain name required${NC}"
    echo "Usage: ./deploy.sh <domain_name>"
    echo "Example: ./deploy.sh voice.example.com"
    exit 1
fi

DOMAIN_NAME=$1
PROJECT_DIR=$(dirname $(dirname $(realpath $0)))
DEPLOY_DIR="$PROJECT_DIR/deploy"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  TME Voice System - Production Deploy  ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Domain: ${YELLOW}$DOMAIN_NAME${NC}"
echo -e "Project: ${YELLOW}$PROJECT_DIR${NC}"
echo ""

# ==================== 1. Check prerequisites ====================
echo -e "${YELLOW}[1/7] Checking prerequisites...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not installed. Installing...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Docker Compose not installed. Installing...${NC}"
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

echo -e "${GREEN}✓ Docker and Docker Compose ready${NC}"

# ==================== 2. Create directories ====================
echo -e "${YELLOW}[2/7] Creating directories...${NC}"

mkdir -p "$DEPLOY_DIR/nginx/ssl"
mkdir -p "$DEPLOY_DIR/certbot/conf"
mkdir -p "$DEPLOY_DIR/certbot/www"
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/temp_audio"

echo -e "${GREEN}✓ Directories created${NC}"

# ==================== 3. Create .env file ====================
echo -e "${YELLOW}[3/7] Setting up environment...${NC}"

if [ ! -f "$DEPLOY_DIR/.env" ]; then
    cat > "$DEPLOY_DIR/.env" << EOF
# Domain
DOMAIN_NAME=$DOMAIN_NAME

# API Keys (REQUIRED - fill these!)
GROQ_API_KEY=your_groq_api_key_here
TAVILY_API_KEY=your_tavily_api_key_here

# Telegram (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
    echo -e "${YELLOW}⚠ Created .env file. Please edit $DEPLOY_DIR/.env with your API keys!${NC}"
else
    echo -e "${GREEN}✓ .env file exists${NC}"
fi

# ==================== 4. Generate nginx config ====================
echo -e "${YELLOW}[4/7] Generating Nginx config...${NC}"

export DOMAIN_NAME
envsubst '${DOMAIN_NAME}' < "$DEPLOY_DIR/nginx/nginx.conf.template" > "$DEPLOY_DIR/nginx/nginx.conf"

echo -e "${GREEN}✓ Nginx config generated${NC}"

# ==================== 5. Get SSL certificate ====================
echo -e "${YELLOW}[5/7] Setting up SSL certificate...${NC}"

# First, create a temporary nginx config for certbot challenge
cat > "$DEPLOY_DIR/nginx/nginx-init.conf" << 'EOF'
events { worker_connections 1024; }
http {
    server {
        listen 80;
        server_name _;
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
        location / {
            return 200 'TME Voice System - Setting up SSL...';
            add_header Content-Type text/plain;
        }
    }
}
EOF

# Start nginx with temp config
docker run -d --name nginx-init \
    -p 80:80 \
    -v "$DEPLOY_DIR/nginx/nginx-init.conf:/etc/nginx/nginx.conf:ro" \
    -v "$DEPLOY_DIR/certbot/www:/var/www/certbot" \
    nginx:alpine

# Get certificate
docker run --rm \
    -v "$DEPLOY_DIR/certbot/conf:/etc/letsencrypt" \
    -v "$DEPLOY_DIR/certbot/www:/var/www/certbot" \
    certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email admin@$DOMAIN_NAME \
    --agree-tos \
    --no-eff-email \
    -d $DOMAIN_NAME \
    -d www.$DOMAIN_NAME

# Stop temp nginx
docker stop nginx-init && docker rm nginx-init
rm "$DEPLOY_DIR/nginx/nginx-init.conf"

echo -e "${GREEN}✓ SSL certificate obtained${NC}"

# ==================== 6. Build and start services ====================
echo -e "${YELLOW}[6/7] Building and starting services...${NC}"

cd "$DEPLOY_DIR"
docker-compose -f docker-compose.prod.yml build --no-cache
docker-compose -f docker-compose.prod.yml up -d

echo -e "${GREEN}✓ Services started${NC}"

# ==================== 7. Verify deployment ====================
echo -e "${YELLOW}[7/7] Verifying deployment...${NC}"

sleep 10

if curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN_NAME" | grep -q "200\|301\|302"; then
    echo -e "${GREEN}✓ HTTPS is working${NC}"
else
    echo -e "${YELLOW}⚠ HTTPS check failed - might need a few more seconds${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  🎉 Deployment Complete!  ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Your TME Voice System is now available at:"
echo -e "  ${YELLOW}https://$DOMAIN_NAME${NC}"
echo ""
echo -e "WebSocket (STT): ${YELLOW}wss://$DOMAIN_NAME/v1/stt${NC}"
echo -e "Search API:      ${YELLOW}https://$DOMAIN_NAME/v1/search${NC}"
echo ""
echo -e "Useful commands:"
echo -e "  View logs:     ${YELLOW}docker-compose -f docker-compose.prod.yml logs -f${NC}"
echo -e "  Restart:       ${YELLOW}docker-compose -f docker-compose.prod.yml restart${NC}"
echo -e "  Stop:          ${YELLOW}docker-compose -f docker-compose.prod.yml down${NC}"
echo ""

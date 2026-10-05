#!/usr/bin/env bash
# =============================================================================
# Dubbing Studio -- one-shot AWS deploy from AWS CloudShell
# =============================================================================
#
#   AWS Console -> CloudShell (top right ">_" icon), then:
#
#     git clone <YOUR-REPO-URL> dub && cd dub
#     bash deploy/aws-deploy.sh
#
# What it creates (all free-tier friendly, one small CPU box):
#
#   * S3 bucket              media (presigned PUT/GET), CORS + lifecycle
#   * Secrets Manager secret dub-studio/gemini  (optional, Gemini key)
#   * IAM role + profile     least-privilege S3 + secret read for the box
#   * Security group         22 (your IP only) + 80 (web)
#   * EC2 instance           Ubuntu 24.04, Docker, API + worker + frontend
#
# Everything is idempotent: run it again and it updates instead of duplicating.
# Nothing here is destructive; `bash deploy/aws-deploy.sh destroy` removes it.
# -----------------------------------------------------------------------------
set -euo pipefail

# ----------------------------- settings --------------------------------------
STACK="${STACK:-dub-studio}"
REGION="${REGION:-${AWS_REGION:-ap-southeast-1}}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"       # 2 vCPU / 2 GB, ~US$15/mo
VOLUME_GB="${VOLUME_GB:-30}"
REPO_URL="${REPO_URL:-$(git -C "$(dirname "$0")/.." remote get-url origin 2>/dev/null || true)}"
REPO_BRANCH="${REPO_BRANCH:-$(git -C "$(dirname "$0")/.." rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"
BUCKET="${BUCKET:-}"                              # default: $STACK-media-$ACCOUNT
SECRET_ID="${SECRET_ID:-dub-studio/gemini}"
GEMINI_API_KEY="${GEMINI_API_KEY:-}"              # optional; can be added later
KEY_NAME="${KEY_NAME:-$STACK-key}"
ACCESS_TOKEN="${ACCESS_TOKEN:-}"                  # single-user bearer token

ROLE="$STACK-role"
PROFILE="$STACK-profile"
SG="$STACK-sg"
TAG="$STACK"

c_ok()   { printf '\033[32m  ok\033[0m  %s\n' "$*"; }
c_run()  { printf '\033[36m  ..\033[0m  %s\n' "$*"; }
c_warn() { printf '\033[33mwarn\033[0m  %s\n' "$*"; }
die()    { printf '\033[31mfail\033[0m  %s\n' "$*" >&2; exit 1; }
step()   { printf '\n\033[1m[%s/13] %s\033[0m\n' "$1" "$2"; }

aws_() { aws --region "$REGION" "$@"; }

# ----------------------------- preflight -------------------------------------
command -v aws >/dev/null || die "aws CLI not found (run this inside AWS CloudShell)"
command -v jq  >/dev/null || die "jq not found"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)" \
  || die "AWS credentials not working"
BUCKET="${BUCKET:-$STACK-media-$ACCOUNT}"
[ -n "$REPO_URL" ] || die "REPO_URL is empty -- export REPO_URL=https://github.com/you/repo.git"
[ -n "$ACCESS_TOKEN" ] || ACCESS_TOKEN="$(openssl rand -hex 24)"

# ----------------------------- destroy ---------------------------------------
if [ "${1:-}" = "destroy" ]; then
  echo "Removing $STACK from $REGION (the S3 bucket is kept on purpose)..."
  ids=$(aws_ ec2 describe-instances \
          --filters "Name=tag:Name,Values=$TAG" "Name=instance-state-name,Values=pending,running,stopped" \
          --query 'Reservations[].Instances[].InstanceId' --output text)
  [ -n "$ids" ] && aws_ ec2 terminate-instances --instance-ids $ids >/dev/null && c_ok "terminated $ids"
  [ -n "$ids" ] && aws_ ec2 wait instance-terminated --instance-ids $ids
  aws_ iam remove-role-from-instance-profile --instance-profile-name "$PROFILE" --role-name "$ROLE" 2>/dev/null || true
  aws_ iam delete-instance-profile --instance-profile-name "$PROFILE" 2>/dev/null || true
  aws_ iam delete-role-policy --role-name "$ROLE" --policy-name "$STACK-inline" 2>/dev/null || true
  aws_ iam delete-role --role-name "$ROLE" 2>/dev/null || true
  sgid=$(aws_ ec2 describe-security-groups --filters "Name=group-name,Values=$SG" \
          --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)
  [ "$sgid" != "None" ] && aws_ ec2 delete-security-group --group-id "$sgid" 2>/dev/null || true
  c_ok "done -- bucket $BUCKET and secret $SECRET_ID were left in place"
  exit 0
fi

cat <<BANNER

  Dubbing Studio -- AWS deploy
  ---------------------------------------------
  account     $ACCOUNT
  region      $REGION
  stack       $STACK
  instance    $INSTANCE_TYPE  (${VOLUME_GB} GB gp3)
  bucket      $BUCKET
  repo        $REPO_URL  ($REPO_BRANCH)

BANNER

# ----------------------------- 1. S3 -----------------------------------------
step 1 "S3 bucket for media"
if aws_ s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  c_ok "bucket exists: $BUCKET"
else
  c_run "creating $BUCKET"
  if [ "$REGION" = "us-east-1" ]; then
    aws_ s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    aws_ s3api create-bucket --bucket "$BUCKET" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
  c_ok "created"
fi
aws_ s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" >/dev/null
aws_ s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
c_ok "private + encrypted"

# ----------------------------- 2. lifecycle ----------------------------------
step 2 "Lifecycle rules (keep the bill small)"
aws_ s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration '{
  "Rules": [
    {"ID":"expire-source","Status":"Enabled","Filter":{"Prefix":"projects/"},
     "Expiration":{"Days":30},
     "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":3}}
  ]}' >/dev/null
c_ok "uploads/intermediates expire after 30 days"

# ----------------------------- 3. CORS ---------------------------------------
step 3 "Bucket CORS (browser uploads straight to S3)"
aws_ s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration '{
  "CORSRules":[{"AllowedMethods":["PUT","GET","HEAD"],"AllowedOrigins":["*"],
  "AllowedHeaders":["*"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3000}]}' >/dev/null
c_warn "AllowedOrigins is \"*\" -- tighten it to your host once you have a domain"

# ----------------------------- 4. secret -------------------------------------
step 4 "Secrets Manager entry for the Gemini key"
if aws_ secretsmanager describe-secret --secret-id "$SECRET_ID" >/dev/null 2>&1; then
  c_ok "secret exists: $SECRET_ID"
  [ -n "$GEMINI_API_KEY" ] && aws_ secretsmanager put-secret-value --secret-id "$SECRET_ID" \
    --secret-string "{\"GEMINI_API_KEY\":\"$GEMINI_API_KEY\"}" >/dev/null && c_ok "value updated"
else
  aws_ secretsmanager create-secret --name "$SECRET_ID" \
    --description "Gemini API key for Dubbing Studio" \
    --secret-string "{\"GEMINI_API_KEY\":\"${GEMINI_API_KEY:-REPLACE_ME}\"}" >/dev/null
  c_ok "created $SECRET_ID"
  [ -z "$GEMINI_API_KEY" ] && c_warn "placeholder stored -- mock mode still works; set the real key later"
fi
SECRET_ARN="$(aws_ secretsmanager describe-secret --secret-id "$SECRET_ID" --query ARN --output text)"

# ----------------------------- 5. IAM ----------------------------------------
step 5 "IAM role for the instance (least privilege)"
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws_ iam get-role --role-name "$ROLE" >/dev/null 2>&1 \
  || aws_ iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" >/dev/null
aws_ iam put-role-policy --role-name "$ROLE" --policy-name "$STACK-inline" --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],
  "Resource":"arn:aws:s3:::$BUCKET/*"},
 {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::$BUCKET"},
 {"Effect":"Allow","Action":["secretsmanager:GetSecretValue"],"Resource":"$SECRET_ARN"}]}
JSON
)" >/dev/null
c_ok "role $ROLE -> bucket + one secret, nothing else"

# ----------------------------- 6. instance profile ---------------------------
step 6 "Instance profile"
aws_ iam get-instance-profile --instance-profile-name "$PROFILE" >/dev/null 2>&1 \
  || aws_ iam create-instance-profile --instance-profile-name "$PROFILE" >/dev/null
aws_ iam add-role-to-instance-profile --instance-profile-name "$PROFILE" --role-name "$ROLE" 2>/dev/null || true
c_ok "profile $PROFILE"
sleep 8   # IAM propagation

# ----------------------------- 7. key pair -----------------------------------
step 7 "SSH key pair"
if aws_ ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1; then
  c_ok "key pair exists: $KEY_NAME"
  [ -f "$HOME/$KEY_NAME.pem" ] || c_warn "private key not in CloudShell -- use Session Manager or recreate the key"
else
  aws_ ec2 create-key-pair --key-name "$KEY_NAME" --query KeyMaterial --output text > "$HOME/$KEY_NAME.pem"
  chmod 400 "$HOME/$KEY_NAME.pem"
  c_ok "saved $HOME/$KEY_NAME.pem  (download it from CloudShell: Actions -> Download file)"
fi

# ----------------------------- 8. security group -----------------------------
step 8 "Security group"
VPC="$(aws_ ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
[ "$VPC" != "None" ] || die "no default VPC in $REGION"
SGID="$(aws_ ec2 describe-security-groups --filters "Name=group-name,Values=$SG" "Name=vpc-id,Values=$VPC" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)"
if [ "$SGID" = "None" ] || [ -z "$SGID" ]; then
  SGID="$(aws_ ec2 create-security-group --group-name "$SG" --vpc-id "$VPC" \
          --description "Dubbing Studio" --query GroupId --output text)"
  c_ok "created $SGID"
fi
MYIP="$(curl -s https://checkip.amazonaws.com || echo 0.0.0.0)"
aws_ ec2 authorize-security-group-ingress --group-id "$SGID" \
  --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$MYIP/32,Description=cloudshell}]" \
  >/dev/null 2>&1 || true
aws_ ec2 authorize-security-group-ingress --group-id "$SGID" --protocol tcp --port 80 --cidr 0.0.0.0/0 \
  >/dev/null 2>&1 || true
c_ok "22 from $MYIP/32, 80 from anywhere"

# ----------------------------- 9. user-data ----------------------------------
step 9 "Boot script"
USERDATA="$(mktemp)"
cat > "$USERDATA" <<CLOUDINIT
#!/bin/bash
set -eux
exec > >(tee -a /var/log/dub-bootstrap.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git nginx
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \$VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

git clone --branch "$REPO_BRANCH" "$REPO_URL" /opt/dub || git -C /opt/dub pull
cd /opt/dub

cat > backend/.env <<ENV
DUB_PROVIDER_TRANSCRIPTION=mock
DUB_PROVIDER_TRANSLATION=mock
DUB_PROVIDER_TTS_MY=mock
DUB_PROVIDER_TTS_EN=mock
DUB_PROVIDER_TTS_FALLBACK=mock
DUB_PROVIDER_LIPSYNC=mock
DUB_PROVIDER_RENDER=ffmpeg
DUB_PROVIDER_STORAGE=s3
DUB_S3_BUCKET=$BUCKET
DUB_S3_REGION=$REGION
DUB_SECRETS_MANAGER_GEMINI_ID=$SECRET_ID
DUB_WORKER_INLINE=0
DUB_REQUIRE_AUTH=true
DUB_ACCESS_TOKEN=$ACCESS_TOKEN
ENV

docker compose up -d --build api worker

cd frontend && npm ci && npm run build && cd ..
rm -rf /var/www/dub && mkdir -p /var/www/dub && cp -r frontend/dist/* /var/www/dub/

cat > /etc/nginx/sites-available/dub <<NGINX
server {
  listen 80 default_server;
  client_max_body_size 0;
  root /var/www/dub;
  index index.html;
  location /api/ { proxy_pass http://127.0.0.1:8000;
                   proxy_http_version 1.1;
                   proxy_set_header Host \\\$host;
                   proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
                   proxy_read_timeout 600s; }
  location / { try_files \\\$uri \\\$uri/ /index.html; }
}
NGINX
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/dub /etc/nginx/sites-enabled/dub
nginx -t && systemctl restart nginx
touch /opt/dub/.bootstrap-done
CLOUDINIT
c_ok "docker + api + worker + nginx + built frontend"

# ----------------------------- 10. AMI ---------------------------------------
step 10 "Latest Ubuntu 24.04 AMI"
AMI="$(aws_ ssm get-parameters \
  --names /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query 'Parameters[0].Value' --output text 2>/dev/null || echo None)"
[ "$AMI" != "None" ] || AMI="$(aws_ ec2 describe-images --owners 099720109477 \
  --filters 'Name=name,Values=ubuntu/images/hvm-ssd*/ubuntu-*-24.04-amd64-server-*' \
  --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)"
c_ok "$AMI"

# ----------------------------- 11. instance ----------------------------------
step 11 "EC2 instance"
IID="$(aws_ ec2 describe-instances --filters "Name=tag:Name,Values=$TAG" \
       "Name=instance-state-name,Values=pending,running" \
       --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || echo None)"
if [ "$IID" != "None" ] && [ -n "$IID" ]; then
  c_ok "already running: $IID  (terminate it first to rebuild, or use deploy/install-on-server.sh)"
else
  IID="$(aws_ ec2 run-instances \
    --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --key-name "$KEY_NAME" \
    --security-group-ids "$SGID" \
    --iam-instance-profile "Name=$PROFILE" \
    --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":$VOLUME_GB,\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$TAG}]" \
    --user-data "file://$USERDATA" \
    --query 'Instances[0].InstanceId' --output text)"
  c_ok "launched $IID"
fi

# ----------------------------- 12. wait --------------------------------------
step 12 "Waiting for the instance to come up"
aws_ ec2 wait instance-running --instance-ids "$IID"
IP="$(aws_ ec2 describe-instances --instance-ids "$IID" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
c_ok "public IP $IP"
c_run "bootstrap (docker build + npm build) takes 5-10 minutes"
for i in $(seq 1 60); do
  if curl -fsS --max-time 5 "http://$IP/api/health" >/dev/null 2>&1; then
    c_ok "API is answering"; break
  fi
  sleep 15
  [ "$i" = 60 ] && c_warn "still not up -- ssh in and read /var/log/dub-bootstrap.log"
done

# ----------------------------- 13. summary -----------------------------------
step 13 "Done"
cat <<SUMMARY

  Open            http://$IP
  Access token    $ACCESS_TOKEN
                  (paste it on the Settings page -- stored in localStorage)

  SSH             ssh -i ~/$KEY_NAME.pem ubuntu@$IP
  Boot log        sudo tail -f /var/log/dub-bootstrap.log
  App logs        cd /opt/dub && sudo docker compose logs -f
  Update          cd /opt/dub && sudo git pull && sudo docker compose up -d --build

  Switch on real providers:
    sudo nano /opt/dub/backend/.env     # mock -> gemini / faster_whisper / mms_tts ...
    cd /opt/dub && sudo docker compose up -d

  Set the Gemini key:
    aws secretsmanager put-secret-value --region $REGION --secret-id $SECRET_ID \\
      --secret-string '{"GEMINI_API_KEY":"your-key"}'

  Tear everything down:
    bash deploy/aws-deploy.sh destroy

SUMMARY
rm -f "$USERDATA"

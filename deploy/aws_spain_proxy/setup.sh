#!/bin/bash
# Provisiona una piccola EC2 in eu-south-2 (Aragona, Spagna) con Squid
# configurato come forward-proxy autenticato, da usare come PROXY_URL
# per il bot Polymarket (vedi config.py / render.yaml).
#
# Prerequisiti:
#   - account AWS attivo, region eu-south-2 abilitata
#     (Account -> AWS Regions -> "Spain (eu-south-2)" -> Enable, puo' metterci
#     qualche minuto/ora a propagare la prima volta)
#   - aws CLI v2 installato e configurato: aws configure
#
# Uso: ./setup.sh

set -euo pipefail

REGION="eu-south-2"
INSTANCE_TYPE="t3.micro"
KEY_NAME="polybot-spain-proxy"
SG_NAME="polybot-spain-proxy-sg"
PROXY_PORT="3128"
PROXY_USER="polybot"
TAG_NAME="polybot-spain-proxy"

WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> IP pubblico locale (per limitare SSH)"
MY_IP="$(curl -s https://checkip.amazonaws.com)"
echo "    $MY_IP"

echo "==> Genero password proxy"
PROXY_PASS="$(openssl rand -base64 18 | tr -d '=+/')"

echo "==> Cerco l'AMI Amazon Linux 2023 piu' recente in $REGION"
# Usiamo describe-images (permesso incluso in AmazonEC2FullAccess) invece di
# SSM Parameter Store, che richiederebbe un permesso IAM aggiuntivo (ssm:GetParameter).
AMI_ID="$(aws ec2 describe-images --region "$REGION" --owners amazon \
  --filters "Name=name,Values=al2023-ami-2023.*-x86_64" "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)"
echo "    $AMI_ID"

if ! aws ec2 describe-key-pairs --region "$REGION" --key-names "$KEY_NAME" >/dev/null 2>&1; then
  echo "==> Creo key pair $KEY_NAME"
  aws ec2 create-key-pair --region "$REGION" --key-name "$KEY_NAME" \
    --query 'KeyMaterial' --output text > "$WORKDIR/$KEY_NAME.pem"
  chmod 400 "$WORKDIR/$KEY_NAME.pem"
else
  echo "==> Key pair $KEY_NAME gia' esistente, salto"
fi

VPC_ID="$(aws ec2 describe-vpcs --region "$REGION" \
  --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"

if ! SG_ID="$(aws ec2 describe-security-groups --region "$REGION" \
    --filters Name=group-name,Values="$SG_NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)" || [ "$SG_ID" = "None" ]; then
  echo "==> Creo security group $SG_NAME"
  SG_ID="$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$SG_NAME" --description "Polybot Spain proxy" --vpc-id "$VPC_ID" \
    --query 'GroupId' --output text)"
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr "${MY_IP}/32" >/dev/null
  # Il traffico proxy viene autenticato da Squid (utente/password), quindi la
  # porta resta aperta a tutti: Render (piano free) non ha un IP in uscita
  # fisso da poter whitelistare qui.
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port "$PROXY_PORT" --cidr "0.0.0.0/0" >/dev/null
else
  echo "==> Security group $SG_NAME gia' esistente, salto"
fi

echo "==> Preparo cloud-init"
USERDATA_FILE="$(mktemp)"
sed -e "s/__PROXY_PORT__/${PROXY_PORT}/" \
    -e "s/__PROXY_USER__/${PROXY_USER}/" \
    -e "s/__PROXY_PASS__/${PROXY_PASS}/" \
    "$WORKDIR/cloud-init.yaml.tmpl" > "$USERDATA_FILE"

echo "==> Lancio istanza EC2 ($INSTANCE_TYPE) in $REGION"
INSTANCE_ID="$(aws ec2 run-instances --region "$REGION" \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_NAME" \
  --security-group-ids "$SG_ID" \
  --user-data "file://$USERDATA_FILE" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$TAG_NAME}]" \
  --query 'Instances[0].InstanceId' --output text)"
rm -f "$USERDATA_FILE"

echo "==> Aspetto che l'istanza sia running ($INSTANCE_ID)"
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"

PUBLIC_IP="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"

cat <<EOF

==================================================================
Istanza pronta: $INSTANCE_ID  ($PUBLIC_IP, region $REGION)
Cloud-init impiega un paio di minuti a installare/avviare Squid.

PROXY_URL da impostare su Render (env var PROXY_URL):

  http://${PROXY_USER}:${PROXY_PASS}@${PUBLIC_IP}:${PROXY_PORT}

Salva questa password, non viene piu' mostrata da AWS.
Chiave SSH: $WORKDIR/$KEY_NAME.pem
  ssh -i "$WORKDIR/$KEY_NAME.pem" ec2-user@${PUBLIC_IP}
==================================================================
EOF

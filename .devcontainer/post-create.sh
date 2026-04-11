#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt

echo "==> Installing AWS CDK CLI..."
npm install -g aws-cdk

echo ""
echo "==> Versions:"
python --version
cdk --version
aws --version
echo "==> Configuring AWS SSO profile..."
mkdir -p ~/.aws
cat >> ~/.aws/config << 'EOF'

[profile jobsignal-admin-access]
sso_session = jobsignal
sso_account_id = 525530758624
sso_role_name = jobsignal-admin-access
region = ap-southeast-1
output = json

[sso-session jobsignal]
sso_start_url = https://ssoins-8210bbf19672aca1.portal.ap-southeast-1.app.aws
sso_region = ap-southeast-1
sso_registration_scopes = sso:account:access
EOF

echo 'export AWS_PROFILE=jobsignal-admin-access' >> ~/.bashrc
echo ""
echo "Run 'aws sso login --profile jobsignal-admin-access' to authenticate."
echo "Setup complete."

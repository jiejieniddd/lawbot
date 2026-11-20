# Create lawbot role/db on local PostgreSQL (Windows, no Docker).
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup_local_postgres.ps1 [-PgPassword <superuser password>]

param(
  [string]$PgHost = "127.0.0.1",
  [int]$PgPort = 5432,
  [string]$SuperUser = "postgres",
  [string]$PgPassword = $env:PGPASSWORD,
  [string]$AppUser = "lawbot",
  [string]$AppPassword = "lawbot",
  [string]$AppDb = "lawbot",
  [string]$Psql = "D:\Tools\PostgreSql\bin\psql.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Psql)) {
  throw "psql not found: $Psql"
}

if ([string]::IsNullOrWhiteSpace($PgPassword)) {
  # Common local defaults; first success wins.
  $candidates = @("postgres", "admin", "123456", "root", "lawbot")
} else {
  $candidates = @($PgPassword)
}

function Invoke-Psql([string]$User, [string]$Password, [string]$Database, [string]$Sql) {
  $env:PGPASSWORD = $Password
  $out = & $Psql -h $PgHost -p $PgPort -U $User -d $Database -v ON_ERROR_STOP=1 -c $Sql 2>&1
  return @{ Code = $LASTEXITCODE; Out = ($out | Out-String) }
}

$auth = $null
foreach ($pwd in $candidates) {
  $probe = Invoke-Psql $SuperUser $pwd "postgres" "SELECT current_user;"
  if ($probe.Code -eq 0) {
    $auth = $pwd
    Write-Host "Connected as $SuperUser"
    break
  }
}

if ($null -eq $auth) {
  Write-Host "Could not authenticate as $SuperUser with known/default passwords."
  Write-Host "Re-run with: -PgPassword YOUR_POSTGRES_PASSWORD"
  exit 2
}

$sql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$AppUser') THEN
    CREATE ROLE $AppUser LOGIN PASSWORD '$AppPassword';
  ELSE
    ALTER ROLE $AppUser WITH LOGIN PASSWORD '$AppPassword';
  END IF;
END
`$`$;
SELECT 'role_ok' AS status;
"@

$r1 = Invoke-Psql $SuperUser $auth "postgres" $sql
Write-Host $r1.Out
if ($r1.Code -ne 0) { exit $r1.Code }

$exists = Invoke-Psql $SuperUser $auth "postgres" "SELECT 1 FROM pg_database WHERE datname = '$AppDb';"
if ($exists.Out -match "\(1 row\)") {
  Write-Host "Database $AppDb already exists"
} else {
  $r2 = Invoke-Psql $SuperUser $auth "postgres" "CREATE DATABASE $AppDb OWNER $AppUser;"
  Write-Host $r2.Out
  if ($r2.Code -ne 0) { exit $r2.Code }
}

$priv = Invoke-Psql $SuperUser $auth $AppDb @"
GRANT ALL ON SCHEMA public TO $AppUser;
ALTER SCHEMA public OWNER TO $AppUser;
"@
Write-Host $priv.Out
if ($priv.Code -ne 0) { exit $priv.Code }

$app = Invoke-Psql $AppUser $AppPassword $AppDb "SELECT current_database(), current_user;"
Write-Host $app.Out
if ($app.Code -ne 0) { exit $app.Code }

Write-Host "OK: $AppUser / $AppDb ready on ${PgHost}:$PgPort"
exit 0

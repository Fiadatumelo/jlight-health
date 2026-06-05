# ════════════════════════════════════════════════════════════════════
# JLIGHT v8.0 — One-click deployment script
# Run this from PowerShell (right-click → Run with PowerShell)
# Or from VS Code: open this file → Ctrl+Shift+P → "Run PowerShell File"
# ════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

# ─── CONFIG ───
$ProjectFolder = "C:\Users\badje\jlight-health"
$DownloadsFolder = "$env:USERPROFILE\Downloads"
$NewIndexFile = "$DownloadsFolder\index.html"
$CommitMessage = "v8.0 - Supabase backend with correct publishable key"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  JLIGHT — Deploy Script" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ─── STEP 1: Verify the new index.html exists in Downloads ───
Write-Host "[1/5] Checking for new index.html in Downloads..." -ForegroundColor Yellow

if (-not (Test-Path $NewIndexFile)) {
    Write-Host "  ✗ Could not find $NewIndexFile" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Please download the new index.html from Claude first," -ForegroundColor Red
    Write-Host "  save it to your Downloads folder, then run this script again." -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

$fileSize = (Get-Item $NewIndexFile).Length
Write-Host "  ✓ Found index.html ($([Math]::Round($fileSize/1KB)) KB)" -ForegroundColor Green

# ─── STEP 2: Verify it has the right publishable key ───
Write-Host ""
Write-Host "[2/5] Verifying file has correct Supabase publishable key..." -ForegroundColor Yellow

$content = Get-Content $NewIndexFile -Raw
if ($content -match "sb_publishable_UfDgLqLadzAFGpf1uEQSiw_APZ3suXZ") {
    Write-Host "  ✓ Publishable key found" -ForegroundColor Green
} else {
    Write-Host "  ✗ Publishable key NOT found in this file" -ForegroundColor Red
    Write-Host "  This may not be the latest patched version." -ForegroundColor Red
    $confirm = Read-Host "  Continue anyway? (y/N)"
    if ($confirm -ne "y") { exit 1 }
}

# ─── STEP 3: Replace index.html in project folder ───
Write-Host ""
Write-Host "[3/5] Replacing index.html in project folder..." -ForegroundColor Yellow

cd $ProjectFolder

if (Test-Path "index.html") {
    Remove-Item "index.html" -Force
    Write-Host "  ✓ Old index.html deleted" -ForegroundColor Green
}

Copy-Item $NewIndexFile -Destination ".\index.html"
Write-Host "  ✓ New index.html copied into project" -ForegroundColor Green

# ─── STEP 4: Git commit and push ───
Write-Host ""
Write-Host "[4/5] Committing to git and pushing to GitHub..." -ForegroundColor Yellow

git add index.html

$status = git status --porcelain
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "  ⚠ Nothing changed — file is identical to what's already committed." -ForegroundColor Yellow
    Write-Host "  Skipping commit." -ForegroundColor Yellow
} else {
    git commit -m $CommitMessage
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ✗ Git commit failed" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  ✓ Committed locally" -ForegroundColor Green

    git push origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ✗ Git push failed — check your network or GitHub credentials" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  ✓ Pushed to GitHub successfully" -ForegroundColor Green
}

# ─── STEP 5: Wait for Netlify deploy + open the site ───
Write-Host ""
Write-Host "[5/5] Waiting for Netlify to rebuild..." -ForegroundColor Yellow
Write-Host "  Netlify takes about 60 seconds to deploy." -ForegroundColor Gray

for ($i = 60; $i -ge 0; $i -= 10) {
    Write-Host "  $i seconds remaining..." -ForegroundColor Gray
    Start-Sleep -Seconds 10
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✓ DEPLOY COMPLETE" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Opening https://jlight-health.co.za in your browser..." -ForegroundColor White
Write-Host "  2. When the site opens, press Ctrl+Shift+R to hard refresh" -ForegroundColor White
Write-Host "  3. Click 'Create new workspace' to make your account" -ForegroundColor White
Write-Host ""
Write-Host "Supabase checklist (do once if you haven't):" -ForegroundColor Cyan
Write-Host "  → https://supabase.com → your project → Authentication → Providers" -ForegroundColor White
Write-Host "  → Click 'Email'" -ForegroundColor White
Write-Host "  → Confirm 'Enable Email Signups' is ON" -ForegroundColor White
Write-Host "  → Toggle 'Confirm email' OFF for testing" -ForegroundColor White
Write-Host ""

Start-Process "https://jlight-health.co.za"

Read-Host "Press Enter to close this window"

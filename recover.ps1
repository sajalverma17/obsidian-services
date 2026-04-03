# Reset Docker Desktop distro when external drive is reconnected
# Just restarting containers won't work because drive's mount layer itself is now stale for the distro

Write-Host "Stopping CouchDB container..."
docker compose down 2>$null

Write-Host "Resetting Docker Desktop distro"
wsl --terminate docker-desktop

Write-Host "Waiting for Docker Desktop distro to recover..."
do {
    Start-Sleep -Seconds 2
    $status = docker info 2>&1
} while ($LASTEXITCODE -ne 0)

Write-Host "Restarting CouchDB..."
docker compose up -d

Write-Host "Done"

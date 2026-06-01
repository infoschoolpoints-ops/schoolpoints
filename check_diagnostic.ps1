$headers = @{
    'api-key' = 'jiz0AQBghTMDIJCwf_wMmhE0--HwVlRV'
    'x-tenant-id' = '47467980'
}
try {
    Write-Host "Checking /sync/diag endpoint..."
    $result = Invoke-RestMethod -Uri "https://schoolpoints.co.il/sync/diag?tenant_id=47467980" -Headers $headers
    Write-Host "Diagnostic Response:"
    $result | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $_"
    Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)"
}

try {
    Write-Host "`nChecking institution details..."
    $inst = Invoke-RestMethod -Uri 'https://schoolpoints.co.il/api/admin/institutions/47467980' -Headers $headers
    Write-Host "Institution Response:"
    $inst | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $_"
}

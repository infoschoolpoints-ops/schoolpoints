$headers = @{
    'api-key' = 'jiz0AQBghTMDIJCwf_wMmhE0--HwVlRV'
}
try {
    $result = Invoke-RestMethod -Uri 'https://schoolpoints.co.il/sync/status?tenant_id=47467980' -Headers $headers
    Write-Host "Sync Status Response:"
    $result | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $_"
    Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)"
}

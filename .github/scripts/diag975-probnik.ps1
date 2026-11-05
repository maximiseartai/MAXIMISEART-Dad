# DIAGNOSTYKA #975 (do usunięcia przed końcem PR): co 2 s liczba połączeń TCP w TIME_WAIT i wszystkich, do pliku CSV.
param([string]$Out)
while ($true) {
  $lines = netstat -an -p tcp
  $tw = ($lines | Select-String 'TIME_WAIT').Count
  $all = ($lines | Select-String 'TCP').Count
  Add-Content -Path $Out -Value ("{0},{1},{2}" -f (Get-Date -Format 'HH:mm:ss'), $tw, $all)
  Start-Sleep -Seconds 2
}

# Instala OpoTest en la Raspberry desde el PC con Windows y copia el temario.
# Uso (PowerShell, en la carpeta del proyecto):
#     powershell -ExecutionPolicy Bypass -File pc\instalar.ps1
#     powershell -ExecutionPolicy Bypass -File pc\instalar.ps1 -SoloServidor   # actualizar el código sin recopiar el temario
#     powershell -ExecutionPolicy Bypass -File pc\instalar.ps1 -Puerto 8795     # forzar un puerto concreto
# Sin -Puerto, la Pi elige sola el primero libre desde 8790 (y en actualizaciones conserva el que tenía).
param(
    [string]$Pi = "usuario@homelab2",
    [string]$TemarioA1 = "C:\Temario\A1",
    [string]$TemarioA2 = "C:\Temario\A2",
    [switch]$SoloServidor,
    [int]$Puerto = 0
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

function Paso($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }

# cmd /c se usa para que la tubería tar | ssh pase los bytes sin tocarlos
function Copiar($origen, $carpetas, $destino) {
    $lista = ($carpetas | ForEach-Object { '"' + $_ + '"' }) -join " "
    $cmd = "tar -C `"$origen`" -cf - $lista | ssh $Pi `"mkdir -p $destino && tar -xf - -C $destino`""
    cmd /c $cmd
    if ($LASTEXITCODE -ne 0) { throw "Falló la copia de $origen" }
}

Paso "1/3 Copiando la aplicación a $Pi"
Copiar $Repo @("server", "pi") "~/opotest"

Paso "2/3 Instalando en la Raspberry"
$envPuerto = if ($Puerto -gt 0) { "OPOTEST_PORT=$Puerto " } else { "" }
ssh -t $Pi "${envPuerto}bash ~/opotest/pi/install.sh"
if ($LASTEXITCODE -ne 0) { throw "La instalación falló" }

if (-not $SoloServidor) {
    Paso "3/3 Copiando el temario (A1 unos 200 MB, A2 unos 12 GB: puede tardar)"
    Write-Host "Si iCloud tiene archivos solo en la nube, se descargarán primero."
    Copiar $TemarioA1 @("Temario General", "Temario Especifico") "~/opotest/temario/A1"
    Copiar $TemarioA2 @(".") "~/opotest/temario/A2"
    ssh $Pi "sudo systemctl restart opotest-ocr"
    Write-Host "Temario copiado. El A1 se indexa en minutos; el OCR del A2 sigue en segundo plano (horas)."
}

$puertoFinal = (ssh $Pi "cat ~/opotest/port").Trim()
$host_ = ($Pi -split "@")[-1]
Write-Host "`nHecho. En la APK pon:  http://${host_}:$puertoFinal" -ForegroundColor Green

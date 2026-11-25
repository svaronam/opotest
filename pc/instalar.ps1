# Instala OpoTest en la Raspberry desde el PC con Windows y copia el temario.
# Uso (PowerShell, en la carpeta del proyecto):
#     powershell -ExecutionPolicy Bypass -File pc\instalar.ps1
#     powershell -ExecutionPolicy Bypass -File pc\instalar.ps1 -SoloServidor   # actualizar el código sin recopiar el temario
#     powershell -ExecutionPolicy Bypass -File pc\instalar.ps1 -SoloSupuestos    # actualizar el código y copiar la carpeta de supuestos prácticos
#     powershell -ExecutionPolicy Bypass -File pc\instalar.ps1 -Puerto 8795     # forzar un puerto concreto
# Sin -Puerto, la Pi elige sola el primero libre desde 8790 (y en actualizaciones conserva el que tenía).
param(
    [string]$Pi = "usuario@homelab2",
    [string]$TemarioA1 = "C:\Temario\A1",
    [string]$TemarioA2 = "C:\Temario\A2",
    [string]$Supuestos = "C:\Temario\Supuestos",
    [switch]$SoloServidor,
    [switch]$SoloSupuestos,
    [int]$Puerto = 0
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot

function Paso($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }

# cmd /c se usa para que la tubería tar | ssh pase los bytes sin tocarlos
function Copiar($origen, $carpetas, $destino, $excluir = @()) {
    $lista = ($carpetas | ForEach-Object { '"' + $_ + '"' }) -join " "
    $ex = ($excluir | ForEach-Object { "--exclude=`"$_`"" }) -join " "
    $cmd = "tar $ex -C `"$origen`" -cf - $lista | ssh $Pi `"mkdir -p $destino && tar -xf - -C $destino`""
    cmd /c $cmd
    if ($LASTEXITCODE -ne 0) { throw "Falló la copia de $origen" }
}

Paso "1/3 Copiando la aplicación a $Pi"
Copiar $Repo @("server", "pi") "~/opotest"

Paso "2/3 Instalando en la Raspberry"
$envPuerto = if ($Puerto -gt 0) { "OPOTEST_PORT=$Puerto " } else { "" }
ssh -t $Pi "${envPuerto}bash ~/opotest/pi/install.sh"
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nLa instalación falló (código $LASTEXITCODE). Estado de la Raspberry:" -ForegroundColor Red
    ssh $Pi "echo '--- Espacio en disco'; df -h / ~ | sort -u; echo '--- Memoria'; free -m; echo '--- Carga y temperatura'; uptime; vcgencmd measure_temp 2>/dev/null; vcgencmd get_throttled 2>/dev/null; echo '--- Servicios'; systemctl is-active opotest opotest-ocr"
    throw "La instalación falló"
}

function CopiarSupuestos {
    if (-not (Test-Path $Supuestos)) { Write-Host "No encuentro la carpeta de supuestos: $Supuestos" -ForegroundColor Yellow; return }
    Paso "Copiando los supuestos prácticos (sin vídeos ni imágenes)"
    # tar de Windows falla con nombres con tildes: se empaqueta en un zip (UTF-8) y se descomprime en la Pi
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $fuera = @(".mp4", ".3gp", ".mov", ".avi", ".mkv", ".png", ".jpg", ".jpeg", ".url", ".vpd")
    $base = (Resolve-Path $Supuestos).Path.TrimEnd("\")
    $zip = Join-Path $env:TEMP "opotest_supuestos.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    $archivos = Get-ChildItem -LiteralPath $base -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $fuera -notcontains $_.Extension.ToLower() }
    $mb = [math]::Round((($archivos | Measure-Object Length -Sum).Sum) / 1MB)
    Write-Host "Empaquetando $($archivos.Count) archivos ($mb MB)..."
    $z = [System.IO.Compression.ZipFile]::Open($zip, "Create")
    $fallos = 0
    try {
        foreach ($f in $archivos) {
            $rel = $f.FullName.Substring($base.Length + 1).Replace("\", "/")
            try { [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $f.FullName, $rel, "NoCompression") }
            catch { $fallos++ }
        }
    } finally { $z.Dispose() }
    if ($fallos) { Write-Host "  $fallos archivos no se pudieron leer y se omiten" -ForegroundColor Yellow }
    $libre = [int](ssh $Pi "df -Pm ~ | awk 'NR==2{print `$4}'")
    if ($libre -lt (2 * $mb + 300)) {
        Remove-Item $zip -Force
        throw "En la Raspberry quedan $libre MB libres y hacen falta unos $(2 * $mb + 300) MB. Libera espacio y repite."
    }
    Write-Host "Enviando a la Raspberry..."
    scp $zip "${Pi}:opotest/sp_upload.zip"
    if ($LASTEXITCODE -ne 0) { throw "Falló el envío de los supuestos" }
    ssh $Pi "python3 ~/opotest/pi/extraer_zip.py ~/opotest/sp_upload.zip ~/opotest/temario/SP; r=`$?; rm -f ~/opotest/sp_upload.zip; sudo -n systemctl restart opotest-ocr 2>/dev/null; exit `$r"
    if ($LASTEXITCODE -ne 0) { throw "Falló la descompresión en la Raspberry" }
    Remove-Item $zip -Force
    Write-Host "Supuestos copiados. Se leen en segundo plano y la IA va sacando el catálogo poco a poco."
}

if ($SoloSupuestos) { CopiarSupuestos }

if (-not $SoloServidor -and -not $SoloSupuestos) {
    Paso "3/3 Copiando el temario (A1 unos 200 MB, A2 unos 12 GB: puede tardar)"
    Write-Host "Si iCloud tiene archivos solo en la nube, se descargarán primero."
    Copiar $TemarioA1 @("Temario General", "Temario Especifico") "~/opotest/temario/A1"
    Copiar $TemarioA2 @(".") "~/opotest/temario/A2"
    ssh $Pi "sudo systemctl restart opotest-ocr"
    CopiarSupuestos
    Write-Host "Temario copiado. El A1 se indexa en minutos; el OCR del A2 sigue en segundo plano (horas)."
}

$puertoFinal = (ssh $Pi "cat ~/opotest/port").Trim()
$host_ = ($Pi -split "@")[-1]
Write-Host "`nHecho. En la APK pon:  http://${host_}:$puertoFinal" -ForegroundColor Green

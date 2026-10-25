#!/usr/bin/env sh
echo `# <#` >/dev/null
# AnyBundle polyglot launcher: POSIX sh section.
set -eu
AB_SELF=$0
ab_die(){ echo "AnyBundle: $*" >&2; exit 1; }
ab_reserved_name(){
    stem=${1%%.*}
    while :; do case "$stem" in *' ') stem=${stem%?};; *) break;; esac; done
    case "$stem" in [cC][oO][nN]|[pP][rR][nN]|[aA][uU][xX]|[nN][uU][lL]|[cC][oO][nN][iI][nN]'$'|[cC][oO][nN][oO][uU][tT]'$'|[cC][oO][mM][1-9]|[lL][pP][tT][1-9]|[cC][oO][mM]¹|[cC][oO][mM]²|[cC][oO][mM]³|[lL][pP][tT]¹|[lL][pP][tT]²|[lL][pP][tT]³) return 0;; esac
    return 1
}
ab_safe_component(){ case "$1" in ''|.|..|*/*|*\\*|*:*|*\**|*\?*|*\"*|*\<*|*\>*|*\|*|*[[:cntrl:]]*|*.|*' ') return 1;; esac; ab_reserved_name "$1" && return 1; return 0; }
ab_manifest_value(){ awk -v k="$1" 'BEGIN{inm=0} /^#__ANYBUNDLE_MANIFEST_BEGIN__$/ {inm=1; next} /^#__ANYBUNDLE_MANIFEST_END__$/ {exit} inm {sub(/^#/ , ""); if(index($0,k"=")==1) {sub(k"=",""); print; exit}}' "$AB_SELF"; }
ab_platform_line(){ awk -F'|' -v p="$1" 'BEGIN{inm=0} /^#__ANYBUNDLE_MANIFEST_BEGIN__$/ {inm=1; next} /^#__ANYBUNDLE_MANIFEST_END__$/ {exit} inm {sub(/^#/,""); if($1 == "platform=" p) {print; exit}}' "$AB_SELF"; }
ab_entry(){ ab_platform_line "$1" | awk -F'|' '{print $2}'; }
ab_sha(){ ab_platform_line "$1" | awk -F'|' '{print $3}'; }
ab_size(){ ab_platform_line "$1" | awk -F'|' '{print $4}'; }
ab_list(){ awk -F'|' 'BEGIN{inm=0} /^#__ANYBUNDLE_MANIFEST_BEGIN__$/ {inm=1; next} /^#__ANYBUNDLE_MANIFEST_END__$/ {exit} inm {sub(/^#/,""); if(index($1,"platform=")==1) {sub("platform=","",$1); printf "%s\t%s\t%s bytes\n", $1, $2, $4}}' "$AB_SELF"; }
ab_info(){ awk 'BEGIN{inm=0} /^#__ANYBUNDLE_MANIFEST_BEGIN__$/ {inm=1; next} /^#__ANYBUNDLE_MANIFEST_END__$/ {exit} inm {sub(/^#/,""); print}' "$AB_SELF"; }
ab_decode_base64(){ if command -v base64 >/dev/null 2>&1; then if base64 --help 2>&1 | grep -q -- '-d'; then base64 -d; else base64 -D; fi; elif command -v openssl >/dev/null 2>&1; then openssl enc -base64 -d; else ab_die 'need base64 or openssl to decode payload'; fi; }
ab_file_sha256(){ if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'; elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'; else ab_die 'need sha256sum or shasum to verify payloads'; fi; }
ab_self_hash(){ ab_file_sha256 "$AB_SELF" | cut -c1-16; }
ab_current_platform(){ os=$(uname -s 2>/dev/null || echo unknown); arch=$(uname -m 2>/dev/null || echo unknown); case "$os" in Linux*) os=linux;; Darwin*) os=macos;; *) os=unknown;; esac; case "$arch" in x86_64|amd64) arch=x64;; i386|i686) arch=x86;; aarch64|arm64) arch=arm64;; *) arch=unknown;; esac; echo "$os-$arch"; }
ab_extract_to()(
    platform=$1; out=$2; expected=$(ab_sha "$platform")
    [ -n "$expected" ] || ab_die "platform not found: $platform"
    ab_safe_component "$platform" || ab_die 'unsafe platform in manifest'
    ab_safe_component "$(ab_entry "$platform")" || ab_die 'unsafe entry in manifest'
    awk -v p="$platform" 'BEGIN{want="#__ANYBUNDLE_PAYLOAD_BEGIN__:" p} $0==want {found=1; next} /^#__ANYBUNDLE_PAYLOAD_END__$/ && found {ended=1; exit} END{exit !(found && ended)}' "$AB_SELF" || ab_die "payload block missing or incomplete: $platform"
    case "$out" in ''|*/) ab_die 'output must be a file path';; /*|./*|../*) ;; *) out="./$out";; esac
    parent=${out%/*}; mkdir -p -- "$parent" || ab_die "cannot create output directory: $parent"
    [ ! -d "$out" ] || ab_die "output is a directory: $out"
    tmp=
    trap '[ -z "$tmp" ] || rm -f -- "$tmp"' 0
    trap 'exit 1' HUP INT TERM
    tmp=$(mktemp "$out.tmp.XXXXXXXX") || ab_die 'cannot create extraction file'
    awk -v p="$platform" 'BEGIN{want="#__ANYBUNDLE_PAYLOAD_BEGIN__:" p; inb=0} $0==want {inb=1; next} /^#__ANYBUNDLE_PAYLOAD_END__$/ && inb {exit} inb {sub(/^#/ , ""); print}' "$AB_SELF" | ab_decode_base64 > "$tmp" || ab_die "failed to decode $platform"
    size=$(wc -c < "$tmp") || ab_die "failed to measure $platform"
    declared_size=$(ab_size "$platform")
    case "$declared_size" in ''|*[!0-9]*) ab_die "invalid payload size for $platform";; esac
    [ "$size" -eq "$declared_size" ] || ab_die "size mismatch for $platform"
    got=$(ab_file_sha256 "$tmp") || ab_die "failed to hash $platform"
    [ "$got" = "$expected" ] || ab_die "sha256 mismatch for $platform"
    chmod +rwx "$tmp" || ab_die "cannot mark payload executable: $platform"
    mv -f -- "$tmp" "$out" || ab_die "cannot write $out"
)
ab_cache_root(){ if [ -n "${XDG_CACHE_HOME:-}" ]; then echo "$XDG_CACHE_HOME/anybundle"; else echo "${HOME:-/tmp}/.cache/anybundle"; fi; }
ab_cache_dir(){
    if [ ! -d "$1" ]; then mkdir -- "$1" 2>/dev/null || [ -d "$1" ] || ab_die "cannot create cache directory: $1"; fi
}
ab_cached_exe()(
    platform=$1; name=$(ab_manifest_value name); ver=$(ab_manifest_value version); entry=$(ab_entry "$platform")
    ab_safe_component "$name" || ab_die 'unsafe cache name in manifest'
    ab_safe_component "$ver" || ab_die 'unsafe cache version in manifest'
    ab_safe_component "$platform" || ab_die 'unsafe platform in manifest'
    ab_safe_component "$entry" || ab_die 'unsafe entry in manifest'
    hash=$(ab_self_hash); [ -n "$hash" ] || ab_die 'cannot hash bundle'
    root=$(ab_cache_root)
    case "$root" in /*|./*|../*) ;; *) root="./$root";; esac
    parent=${root%/*}; mkdir -p -- "$parent" || ab_die "cannot create cache parent: $parent"
    dir=$root; ab_cache_dir "$dir"
    for part in "$name" "$ver" "$hash" "$platform"; do dir="$dir/$part"; ab_cache_dir "$dir"; done
    exe="$dir/$entry"; expected=$(ab_sha "$platform")
    if [ -f "$exe" ]; then got=$(ab_file_sha256 "$exe") || ab_die 'cannot hash cached payload'; [ "$got" = "$expected" ] || rm -f -- "$exe"; fi
    [ -f "$exe" ] || ab_extract_to "$platform" "$exe"
    echo "$exe"
)
ab_pick_platform_from_args(){ p=; while [ $# -gt 0 ]; do case "$1" in --platform) shift; p=${1:-};; --win-x64|--win-x86|--win-arm64|--linux-x64|--linux-x86|--linux-arm64|--macos-x64|--macos-arm64) p=${1#--};; esac; shift || true; done; [ -n "$p" ] && echo "$p" || ab_current_platform; }
ab_run(){ platform=$(ab_current_platform); exe=$(ab_cached_exe "$platform"); exec "$exe" "$@"; }
ab_unpack(){ platform=$(ab_pick_platform_from_args "$@"); out=; while [ $# -gt 0 ]; do case "$1" in -o|--output) shift; out=${1:-};; esac; shift || true; done; [ -n "$out" ] || out=$(ab_entry "$platform"); [ -n "$out" ] || ab_die 'cannot determine output path'; ab_extract_to "$platform" "$out"; echo "wrote $out ($platform)"; }
ab_manifest_platforms(){
    awk '
    function fail(message){ print "invalid manifest: " message; bad=1; exit 1 }
    function safe(s,stem,norm,i,c,pos){ if(s == "" || s == "." || s == ".." || s ~ /[\/\\:*?"<>|[:cntrl:]]/ || s ~ /[. ]$/) return 0; stem=s; sub(/\..*$/,"",stem); sub(/ +$/,"",stem); for(i=1;i<=length(stem);i++){ c=substr(stem,i,1); pos=index("abcdefghijklmnopqrstuvwxyz",c); if(pos) c=substr("ABCDEFGHIJKLMNOPQRSTUVWXYZ",pos,1); norm=norm c }; return norm !~ /^(CON|PRN|AUX|NUL|CONIN[$]|CONOUT[$]|(COM|LPT)([1-9]|¹|²|³))$/ }
    /^#__ANYBUNDLE_MANIFEST_BEGIN__$/ {
        if(begun || state != 0) fail("duplicate or misplaced manifest begin");
        begun=1; state=1; next
    }
    /^#__ANYBUNDLE_MANIFEST_END__$/ {
        if(state != 1) fail("misplaced manifest end");
        state=2; next
    }
    state == 1 {
        if(substr($0,1,1) != "#") fail("manifest records must be comments");
        row=substr($0,2);
        if(index(row,"platform=") == 1){
            n=split(row,f,/\|/); p=substr(f[1],10);
            if(n != 5 || p !~ /^(win|linux)-(x64|x86|arm64)$|^macos-(x64|arm64)$/) fail("invalid platform record");
            if(p in declared) fail("duplicate platform: " p);
            if(!safe(f[2]) || length(f[3]) != 64 || f[3] !~ /^[0-9a-f]+$/ || f[4] !~ /^(0|[1-9][0-9]*)$/ || f[5] != "0755") fail("invalid platform metadata: " p);
            declared[p]=1; order[++count]=p;
        } else {
            pos=index(row,"="); key=substr(row,1,pos-1); value=substr(row,pos+1);
            if(!pos || key !~ /^(format|name|version|builder)$/ || meta[key]++) fail("invalid or duplicate metadata");
            values[key]=value;
        }
        next
    }
    index($0,"#__ANYBUNDLE_PAYLOAD_BEGIN__:") == 1 {
        p=substr($0,length("#__ANYBUNDLE_PAYLOAD_BEGIN__:")+1);
        if(state != 2 || open != "") fail("misplaced or nested payload");
        if(!(p in declared)) fail("payload not declared: " p);
        if(p in blocks) fail("duplicate payload: " p);
        open=p; next
    }
    /^#__ANYBUNDLE_PAYLOAD_END__$/ {
        if(open == "") fail("misplaced payload end");
        blocks[open]=1; open=""; next
    }
    open != "" && substr($0,1,1) != "#" { fail("payload data must be comments") }
    END {
        if(bad) exit 1;
        if(!begun || state != 2 || open != "") fail("missing or incomplete manifest or payload");
        if(!count) fail("at least one platform is required");
        if(meta["format"] != 1 || meta["name"] != 1 || meta["version"] != 1 || meta["builder"] != 1) fail("missing required metadata");
        if(values["format"] != "anybundle.bundle.v1" || !safe(values["name"]) || !safe(values["version"]) || values["builder"] == "") fail("invalid required metadata");
        for(i=1;i<=count;i++) if(!(order[i] in blocks)) fail("payload missing: " order[i]);
        for(i=1;i<=count;i++) print order[i];
    }' "$AB_SELF"
}
ab_verify()(
    umask 077
    platforms=$(ab_manifest_platforms) || ab_die "$platforms"
    tmp=
    trap '[ -z "$tmp" ] || rm -f -- "$tmp"' 0
    trap 'exit 1' HUP INT TERM
    ok=1
    for p in $platforms; do
        tmp=$(mktemp "${TMPDIR:-/tmp}/abverify.XXXXXXXX") || ab_die 'cannot create verification file'
        if ab_extract_to "$p" "$tmp" >/dev/null 2>&1; then echo "OK $p"; else echo "FAIL $p"; ok=0; fi
        rm -f -- "$tmp"; tmp=
    done
    [ "$ok" -eq 1 ]
)
ab_clean_cache()(
    root=$(ab_cache_root); name=$(ab_manifest_value name)
    ab_safe_component "$name" || ab_die 'unsafe cache name in manifest'
    case "$root" in /*|./*|../*) ;; *) root="./$root";; esac
    target="$root/$name"
    [ "$target" != "$root" ] && [ "${target%/*}" = "$root" ] || ab_die 'refusing to remove cache root'
    if [ -e "$target" ] || [ -L "$target" ]; then
        [ -d "$target" ] || [ -L "$target" ] || ab_die 'cache target is not a directory'
        rm -rf -- "$target" || ab_die "failed to remove $target"
    fi
    echo "removed $target"
)
if [ $# -eq 0 ]; then ab_run; fi
case "$1" in
  --) shift; ab_run "$@";;
  run) shift; [ "${1:-}" = -- ] && shift; ab_run "$@";;
  unpack) shift; ab_unpack "$@";;
  list) ab_list;;
  info) ab_info;;
  verify) ab_verify;;
  clean-cache) ab_clean_cache;;
  help|-h|--help) echo 'Usage: this-bundle.sh.ps1 [run|unpack|list|info|verify|clean-cache] [-- args...]';;
  *) ab_run "$@";;
esac
exit $?
#> > $null
# AnyBundle polyglot launcher: PowerShell section.
$ErrorActionPreference = 'Stop'
$AB_SELF = $PSCommandPath; if (-not $AB_SELF) { $AB_SELF = $MyInvocation.MyCommand.Path }
function AB-Die($m) { throw "AnyBundle: $m" }
function AB-Lines { foreach($l in (Get-Content -LiteralPath $AB_SELF -Encoding UTF8)){ if($l.StartsWith('#')){ $l.Substring(1) } else { $l } } }
function AB-ManifestLines { $in=$false; foreach($l in AB-Lines){ if($l -eq '__ANYBUNDLE_MANIFEST_BEGIN__'){ $in=$true; continue }; if($l -eq '__ANYBUNDLE_MANIFEST_END__'){ break }; if($in){ $l } } }
function AB-ManifestValue($k) { foreach($l in AB-ManifestLines){ if($l.StartsWith($k + '=')){ return $l.Substring($k.Length + 1) } }; return '' }
function AB-PlatformLine($p) { foreach($l in AB-ManifestLines){ if($l.StartsWith('platform=' + $p + '|')){ return $l } }; return '' }
function AB-Entry($p) { $x=(AB-PlatformLine $p).Split('|'); if($x.Length -ge 2){ $x[1] } }
function AB-Sha($p) { $x=(AB-PlatformLine $p).Split('|'); if($x.Length -ge 3){ $x[2] } }
function AB-List { foreach($l in AB-ManifestLines){ if($l.StartsWith('platform=')){ $x=$l.Split('|'); $p=$x[0].Substring(9); Write-Output ("{0}`t{1}`t{2} bytes" -f $p,$x[1],$x[3]) } } }
function AB-Info { AB-ManifestLines }
function AB-FileSha($p) { (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLowerInvariant() }
function AB-SelfHash { (AB-FileSha $AB_SELF).Substring(0,16) }
function AB-SafeComponent($s) {
    if([string]::IsNullOrEmpty($s) -or $s -eq '.' -or $s -eq '..' -or $s.EndsWith('.') -or $s.EndsWith(' ') -or $s.IndexOfAny([char[]]('/\:*?"<>|')) -ge 0){ return $false }
    foreach($c in $s.ToCharArray()){ if([int][char]$c -lt 32 -or [int][char]$c -eq 127){ return $false } }
    $stem=$s.Split('.')[0].TrimEnd([char]' ').ToUpperInvariant()
    return $stem -cnotmatch '^(CON|PRN|AUX|NUL|CONIN[$]|CONOUT[$]|(COM|LPT)[1-9\u00b9\u00b2\u00b3])$'
}
function AB-CurrentPlatform { $arch=[Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant(); switch($arch){ 'x64' {$a='x64'} 'x86' {$a='x86'} 'arm64' {$a='arm64'} default {$a=$arch} }; return 'win-' + $a }
function AB-ExtractTo($platform, $out) {
    $expected=AB-Sha $platform
    if(-not $expected){ AB-Die "platform not found: $platform" }
    if(-not (AB-SafeComponent $platform)){ AB-Die 'unsafe platform in manifest' }
    if(-not (AB-SafeComponent (AB-Entry $platform))){ AB-Die 'unsafe entry in manifest' }
    $want='__ANYBUNDLE_PAYLOAD_BEGIN__:' + $platform; $found=$false; $ended=$false; $sb=New-Object System.Text.StringBuilder
    foreach($l in AB-Lines){
        if($l -ceq $want){ $found=$true; continue }
        if($found -and $l -ceq '__ANYBUNDLE_PAYLOAD_END__'){ $ended=$true; break }
        if($found){ [void]$sb.Append($l.Trim()) }
    }
    if(-not $found -or -not $ended){ AB-Die "payload block missing or incomplete: $platform" }
    $bytes=[Convert]::FromBase64String($sb.ToString())
    $size=(AB-PlatformLine $platform).Split('|')[3]
    if($size -cnotmatch '^(0|[1-9][0-9]*)$' -or $bytes.LongLength.ToString([Globalization.CultureInfo]::InvariantCulture) -cne $size){ AB-Die "size mismatch for $platform" }
    $out=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($out)
    if([IO.Directory]::Exists($out)){ AB-Die "output is a directory: $out" }
    $dir=[IO.Path]::GetDirectoryName($out); [void][IO.Directory]::CreateDirectory($dir)
    $tmp=$out + '.tmp.' + [IO.Path]::GetRandomFileName(); $created=$false
    try {
        $stream=[IO.File]::Open($tmp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None); $created=$true
        try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
        if((AB-FileSha $tmp) -ne $expected){ AB-Die "sha256 mismatch for $platform" }
        Move-Item -Force -LiteralPath $tmp -Destination $out
    } finally { if($created -and (Test-Path -LiteralPath $tmp)){ Remove-Item -Force -LiteralPath $tmp } }
}
function AB-CacheRoot { if($env:LOCALAPPDATA){ Join-Path $env:LOCALAPPDATA 'AnyBundle/cache' } else { Join-Path $env:TEMP 'AnyBundle/cache' } }
function AB-CachedExe($platform) { $name=AB-ManifestValue 'name'; $ver=AB-ManifestValue 'version'; $entry=AB-Entry $platform; if(-not (AB-SafeComponent $name)){ AB-Die 'unsafe cache name in manifest' }; if(-not (AB-SafeComponent $ver)){ AB-Die 'unsafe cache version in manifest' }; if(-not (AB-SafeComponent $platform)){ AB-Die 'unsafe platform in manifest' }; if(-not (AB-SafeComponent $entry)){ AB-Die 'unsafe entry in manifest' }; $dir=Join-Path (AB-CacheRoot) (Join-Path $name (Join-Path $ver (Join-Path (AB-SelfHash) $platform))); [void][IO.Directory]::CreateDirectory($dir); $exe=Join-Path $dir $entry; $expected=AB-Sha $platform; if(Test-Path -LiteralPath $exe){ if((AB-FileSha $exe) -ne $expected){ Remove-Item -Force -LiteralPath $exe } }; if(-not (Test-Path -LiteralPath $exe)){ AB-ExtractTo $platform $exe }; return $exe }
function AB-PickPlatform($argv) { for($i=0; $i -lt $argv.Count; $i++){ if($argv[$i] -eq '--platform' -and $i+1 -lt $argv.Count){ return $argv[$i+1] }; if($argv[$i] -match '^--(win-x64|win-x86|win-arm64|linux-x64|linux-x86|linux-arm64|macos-x64|macos-arm64)$'){ return $Matches[1] } }; return AB-CurrentPlatform }
function AB-QuoteArg([string]$s) { $sb=New-Object System.Text.StringBuilder; [void]$sb.Append('"'); $slashes=0; foreach($c in $s.ToCharArray()){ if($c -eq '\'){ $slashes++; continue }; if($c -eq '"'){ [void]$sb.Append(('\' * (2*$slashes+1))) } else { [void]$sb.Append(('\' * $slashes)) }; [void]$sb.Append($c); $slashes=0 }; [void]$sb.Append(('\' * (2*$slashes))); [void]$sb.Append('"'); return $sb.ToString() }
function AB-Run($argv) { $platform=AB-CurrentPlatform; $exe=AB-CachedExe $platform; $start=New-Object Diagnostics.ProcessStartInfo; $start.FileName=$exe; $start.UseShellExecute=$false; $start.Arguments=(@($argv | ForEach-Object { AB-QuoteArg $_ }) -join ' '); $start.WorkingDirectory=(Get-Location).ProviderPath; $proc=[Diagnostics.Process]::Start($start); $proc.WaitForExit(); $code=$proc.ExitCode; $proc.Dispose(); exit $code }
function AB-Unpack($argv) { $platform=AB-PickPlatform $argv; $out=''; for($i=0; $i -lt $argv.Count; $i++){ if(($argv[$i] -eq '-o' -or $argv[$i] -eq '--output') -and $i+1 -lt $argv.Count){ $out=$argv[$i+1] } }; if(-not $out){ $out=AB-Entry $platform }; AB-ExtractTo $platform $out; Write-Host "wrote $out ($platform)" }
function AB-ManifestPlatforms {
    $state=0; $begun=$false; $open=''
    $meta=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    $declared=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $blocks=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $order=[Collections.Generic.List[string]]::new()
    $prefix='#__ANYBUNDLE_PAYLOAD_BEGIN__:'
    foreach($line in (Get-Content -LiteralPath $AB_SELF -Encoding UTF8)){
        if($line -ceq '#__ANYBUNDLE_MANIFEST_BEGIN__'){
            if($begun -or $state -ne 0){ AB-Die 'invalid manifest: duplicate or misplaced manifest begin' }
            $begun=$true; $state=1; continue
        }
        if($line -ceq '#__ANYBUNDLE_MANIFEST_END__'){
            if($state -ne 1){ AB-Die 'invalid manifest: misplaced manifest end' }
            $state=2; continue
        }
        if($state -eq 1){
            if(-not $line.StartsWith('#')){ AB-Die 'invalid manifest: manifest records must be comments' }
            $row=$line.Substring(1)
            if($row.StartsWith('platform=')){
                $f=$row.Split('|'); $p=$f[0].Substring(9)
                if($f.Length -ne 5 -or $p -cnotmatch '^(win|linux)-(x64|x86|arm64)$|^macos-(x64|arm64)$'){ AB-Die 'invalid manifest: invalid platform record' }
                if(-not $declared.Add($p)){ AB-Die "invalid manifest: duplicate platform: $p" }
                if(-not (AB-SafeComponent $f[1]) -or $f[2] -cnotmatch '^[0-9a-f]{64}$' -or $f[3] -cnotmatch '^(0|[1-9][0-9]*)$' -or $f[4] -cne '0755'){ AB-Die "invalid manifest: invalid platform metadata: $p" }
                $order.Add($p)
            } else {
                $pos=$row.IndexOf('=')
                if($pos -lt 1){ AB-Die 'invalid manifest: invalid metadata' }
                $key=$row.Substring(0,$pos); $value=$row.Substring($pos+1)
                if($key -cnotmatch '^(format|name|version|builder)$' -or $meta.ContainsKey($key)){ AB-Die 'invalid manifest: invalid or duplicate metadata' }
                $meta.Add($key,$value)
            }
            continue
        }
        if($line.StartsWith($prefix)){
            $p=$line.Substring($prefix.Length)
            if($state -ne 2 -or $open){ AB-Die 'invalid manifest: misplaced or nested payload' }
            if(-not $declared.Contains($p)){ AB-Die "invalid manifest: payload not declared: $p" }
            if($blocks.Contains($p)){ AB-Die "invalid manifest: duplicate payload: $p" }
            $open=$p; continue
        }
        if($line -ceq '#__ANYBUNDLE_PAYLOAD_END__'){
            if(-not $open){ AB-Die 'invalid manifest: misplaced payload end' }
            [void]$blocks.Add($open); $open=''; continue
        }
        if($open -and -not $line.StartsWith('#')){ AB-Die 'invalid manifest: payload data must be comments' }
    }
    if(-not $begun -or $state -ne 2 -or $open){ AB-Die 'invalid manifest: missing or incomplete manifest or payload' }
    if($order.Count -eq 0){ AB-Die 'invalid manifest: at least one platform is required' }
    foreach($key in 'format','name','version','builder'){ if(-not $meta.ContainsKey($key)){ AB-Die 'invalid manifest: missing required metadata' } }
    if($meta['format'] -cne 'anybundle.bundle.v1' -or -not (AB-SafeComponent $meta['name']) -or -not (AB-SafeComponent $meta['version']) -or -not $meta['builder']){ AB-Die 'invalid manifest: invalid required metadata' }
    foreach($p in $order){ if(-not $blocks.Contains($p)){ AB-Die "invalid manifest: payload missing: $p" } }
    return $order.ToArray()
}
function AB-Verify {
    $platforms=@(AB-ManifestPlatforms); $ok=$true
    foreach($p in $platforms){
        $tmp=[IO.Path]::GetTempFileName()
        try { AB-ExtractTo $p $tmp; Write-Host "OK $p" }
        catch { Write-Host ("FAIL {0}: {1}" -f $p,$_.Exception.Message); $ok=$false }
        finally { Remove-Item -Force -LiteralPath $tmp -ErrorAction SilentlyContinue }
    }
    if(-not $ok){ exit 1 }
}
function AB-CleanCache { $name=AB-ManifestValue 'name'; if(-not (AB-SafeComponent $name)){ AB-Die 'unsafe cache name in manifest' }; $root=[IO.Path]::GetFullPath((AB-CacheRoot)); $path=[IO.Path]::GetFullPath((Join-Path $root $name)); if($path -eq $root -or [IO.Path]::GetDirectoryName($path) -ne $root){ AB-Die 'refusing to remove cache root' }; if(Test-Path -LiteralPath $path){ if(-not (Test-Path -LiteralPath $path -PathType Container)){ AB-Die 'cache target is not a directory' }; Remove-Item -Recurse -Force -LiteralPath $path -ErrorAction Stop }; Write-Host "removed $path" }
$argv = [System.Collections.Generic.List[string]]::new(); foreach($a in $args){ [void]$argv.Add($a) }
if($argv.Count -eq 0){ AB-Run @() }
$cmd=$argv[0]; $rest=@(); if($argv.Count -gt 1){ $rest=$argv.GetRange(1,$argv.Count-1).ToArray() }
switch($cmd){
  '--' { AB-Run $rest }
  'run' { if($rest.Count -gt 0 -and $rest[0] -eq '--'){ $rest=@($rest | Select-Object -Skip 1) }; AB-Run $rest }
  'unpack' { AB-Unpack $rest }
  'list' { AB-List }
  'info' { AB-Info }
  'verify' { AB-Verify }
  'clean-cache' { AB-CleanCache }
  {$_ -in 'help','-h','--help'} { Write-Host 'Usage: this-bundle.sh.ps1 [run|unpack|list|info|verify|clean-cache] [-- args...]' }
  default { AB-Run $argv.ToArray() }
}
exit 0

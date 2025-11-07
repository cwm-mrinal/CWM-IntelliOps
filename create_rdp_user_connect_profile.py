SSM_DOCUMENT_NAME = "CreateRDPUserAndConnectProfile"

SSM_DOCUMENT_CONTENT = """
  schemaVersion: '2.2'
  description: "Create RDP users and TSplus .connect profiles on Windows EC2 (Base64 JSON input)"
  parameters:
    UsersJsonBase64:
      type: String
      description: "Base64-encoded JSON list of user objects with fields: Username, PasswordPlain, ServerIP, DisplayMode, PrinterAction, PrinterScale, CommonGroups, Groups"
    S3BucketName:
      type: String
      description: "S3 bucket name to upload .connect files"
    S3Prefix:
      type: String
      description: "S3 prefix/folder path for .connect files"
      default: "tsplus-connect-files"

  mainSteps:
    - action: aws:runPowerShellScript
      name: CreateUsersAndProfiles
      inputs:
        runCommand:
          - |
            Write-Host "=== Starting TSplus user creation ==="
            $jsonDecoded = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String("{{ UsersJsonBase64 }}"))
            $users = ConvertFrom-Json $jsonDecoded
            $adminDesktop = "C:\\Users\\Public\\Desktop"
            $generatorExe = Join-Path "${env:ProgramFiles(x86)}\\TSplus\\Clients\\WindowsClient" "ClientGenerator.exe"
            $attachments = @()
            $bodyLines = @()
            $s3Objects = @()

            $bucketName = "{{ S3BucketName }}"
            $s3Prefix = "{{ S3Prefix }}"

            foreach ($user in $users) {
                $Username = $user.Username
                $PasswordPlain = $user.PasswordPlain
                $ServerIP = $user.ServerIP
                $ServerPort = Get-ItemPropertyValue -Path "HKLM:\\System\\CurrentControlSet\\Control\\Terminal Server\\WinStations\\RDP-Tcp" -Name "PortNumber"
                Write-Host "`n[+] Creating user: $Username with RDP port: $ServerPort"

                $SecurePassword = ConvertTo-SecureString $PasswordPlain -AsPlainText -Force
                try {
                    New-LocalUser -Name $Username -Password $SecurePassword -FullName $Username -ErrorAction Stop
                    Write-Host "[+] User $Username created"
                } catch {
                    Write-Host "[!] User $Username may already exist. Continuing..."
                }

                $TargetGroups = @()
                if ($user.CommonGroups) { $TargetGroups += ($user.CommonGroups -split ',') }
                if ($user.Groups) { $TargetGroups += ($user.Groups -split ',') }

                foreach ($group in $TargetGroups) {
                    $trimmedGroup = $group.Trim()
                    try {
                        Add-LocalGroupMember -Group $trimmedGroup -Member $Username -ErrorAction Stop
                        Write-Host "[+] Added $Username to group $trimmedGroup"
                    } catch {
                        Write-Host "[!] Could not add $Username to group $trimmedGroup"
                    }
                }

                try {
                    $adsi = [ADSI]"WinNT://$env:COMPUTERNAME/$Username,user"
                    $flags = $adsi.UserFlags.Value

                    if ($user.UserCanChange -eq "NO") { $flags = $flags -bor 0x40 } else { $flags = $flags -band (-bnot 0x40) }
                    if ($user.AccountDisabled -eq "YES") { $flags = $flags -bor 0x2 } else { $flags = $flags -band (-bnot 0x2) }

                    $adsi.UserFlags = $flags
                    try {
                        $adsi.SetInfo()
                        Write-Host "[+] UserFlags updated successfully for ${Username}"
                    } catch {
                        Write-Host "[!] Failed to apply UserFlags for ${Username}: $($_.Exception.Message)"
                    }
                } catch {
                    Write-Host "[!] Could not access ADSI object for ${Username}: $($_.Exception.Message)"
                }

                if ($user.PasswordNeverExpires -eq "YES") {
                    try {
                        $wmiUser = Get-WmiObject -Class Win32_UserAccount -Filter "Name='$Username' AND LocalAccount=True"
                        if ($wmiUser) {
                            $wmiUser.PasswordExpires = $false
                            $wmiUser.Put() | Out-Null
                            Write-Host "[+] Set PasswordNeverExpires for ${Username}"
                        }
                    } catch {
                        Write-Host "[!] Failed to set PasswordNeverExpires for ${Username}: $($_.Exception.Message)"
                    }
                } else {
                    try {
                        Set-LocalUser -Name $Username -PasswordNeverExpires $false -ErrorAction Stop
                        Write-Host "[+] Password expiration enabled for ${Username}"
                    } catch {
                        Write-Host "[!] Failed to set Password expiration for ${Username}: $($_.Exception.Message)"
                    }
                }

                if ($user.UserMustChange -eq "YES") {
                    try {
                        cmd /c "net user $Username /logonpasswordchg:yes"
                        Write-Host "[+] Set UserMustChange on next login for ${Username}"
                    } catch {
                        Write-Host "[!] Failed to set UserMustChange for ${Username}: $($_.Exception.Message)"
                    }
                }

                $DisplayMode = $user.DisplayMode
                $PrinterAction = $user.PrinterAction
                $PrinterScale = $user.PrinterScale

                $remoteappFlag = if ($DisplayMode -eq 'remoteapp') { 'on' } else { 'off' }
                $seamlessFlag  = if ($DisplayMode -eq 'seamless')  { 'on' } else { 'off' }
                $previewFlag   = if ($PrinterAction -eq 'preview') { 'on' } else { 'off' }
                $defaultFlag   = if ($PrinterAction -eq 'printdefault') { 'on' } else { 'off' }
                $selectFlag    = if ($PrinterAction -eq 'select') { 'on' } else { 'off' }
                $scaleFlag     = $PrinterScale

                $outputFile = Join-Path $adminDesktop "$Username.connect"
                $args = @(
                    "-server", "$ServerIP",
                    "-port", "$ServerPort",
                    "-user", "$Username",
                    "-password", "`"$PasswordPlain`"",
                    "-remoteapp", $remoteappFlag,
                    "-seamless", $seamlessFlag,
                    "-printer", "on",
                    "-preview", $previewFlag,
                    "-default", $defaultFlag,
                    "-select", $selectFlag,
                    "-printerscaling", $scaleFlag,
                    "-name", "$Username.connect",
                    "-location", $adminDesktop
                )

                Write-Host "[*] Running TSplus Client Generator for $Username"
                Start-Process -FilePath $generatorExe -ArgumentList $args -NoNewWindow -Wait
                Start-Sleep -Seconds 2

                if (Test-Path $outputFile) {
                    Write-Host "[+] .connect file created at $outputFile"
                    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
                    $s3KeyWithTimestamp = "$s3Prefix/$timestamp/$Username.connect"

                    try {
                        Write-Host "[*] Uploading $outputFile to S3: s3://$bucketName/$s3KeyWithTimestamp"
                        aws s3 cp $outputFile "s3://$bucketName/$s3KeyWithTimestamp" --no-progress
                        if ($LASTEXITCODE -eq 0) {
                            Write-Host "[+] Successfully uploaded $Username.connect to S3"
                            $s3Objects += @{
                                Username = $Username
                                S3Key = $s3KeyWithTimestamp
                                S3Bucket = $bucketName
                                LocalPath = $outputFile
                            }
                        } else {
                            Write-Host "[!] Upload failed with exit code $LASTEXITCODE for $Username.connect"
                        }
                    } catch {
                        Write-Host "[!] Error uploading $Username.connect: $($_.Exception.Message)"
                    }

                    $attachments += $outputFile
                    $bodyLines += "Username: $Username`nPassword: $PasswordPlain`n"
                } else {
                    Write-Host "[!] Failed to generate .connect file for $Username"
                }
            }

            if ($s3Objects.Count -gt 0) {
                $s3Json = ConvertTo-Json -InputObject $s3Objects -Depth 3
                Write-Host "S3_OBJECTS_JSON_START"
                Write-Host $s3Json
                Write-Host "S3_OBJECTS_JSON_END"
            }

            Write-Host "=== Script complete ==="
"""
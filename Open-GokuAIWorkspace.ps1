[CmdletBinding()]
param(
    [string]$Root = 'C:\gokuai',
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$startScript = Join-Path $Root 'Start-GokuAI.ps1'
$historyPath = Join-Path $Root 'runtime\workspace-history.json'
$converterWorkspace = Join-Path $Root 'projects\RB-Legacy-Java-Converter'
$syncScript = Join-Path $Root 'scripts\Sync-LegacyConverterWorkspace.ps1'
$packagingSync = Join-Path $Root 'projects\_upstream\LegacyJavaConverter\scripts\Sync-GokuaiConverterWorkspace.ps1'

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "GokuAI launcher dependency is missing: $startScript"
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Sync-MigrationSkillsIntoWorkspace {
    param(
        [Parameter(Mandatory)][string]$WorkspacePath,
        [switch]$FullConverterTools
    )
    $skillsOnly = -not $FullConverterTools
    if (Test-Path -LiteralPath $packagingSync) {
        $splat = @{ Workspace = $WorkspacePath }
        if ($skillsOnly) { $splat.SkillsOnly = $true }
        & $packagingSync @splat
        return
    }
    if (Test-Path -LiteralPath $syncScript) {
        $splat = @{ Workspace = $WorkspacePath }
        if ($skillsOnly) { $splat.SkillsOnly = $true }
        & $syncScript @splat
        return
    }

    # Inline fallback: copy .grok from converter workspace
    $srcGrok = Join-Path $converterWorkspace '.grok'
    if (-not (Test-Path -LiteralPath $srcGrok)) {
        throw "Cannot sync migration skills: missing $packagingSync and $srcGrok"
    }
    $dstGrok = Join-Path $WorkspacePath '.grok'
    & robocopy.exe $srcGrok $dstGrok /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy .grok failed: $LASTEXITCODE" }
    $agents = Join-Path $converterWorkspace 'Agents.md'
    if (Test-Path $agents) { Copy-Item $agents (Join-Path $WorkspacePath 'Agents.md') -Force }
    $toolsDst = Join-Path $WorkspacePath 'tools'
    if (-not (Test-Path $toolsDst)) { New-Item -ItemType Directory -Path $toolsDst -Force | Out-Null }
    foreach ($name in @('Build-WithDestinationJava.ps1', 'Lint-MigrationSkills.ps1')) {
        $src = Join-Path $converterWorkspace "tools\$name"
        if (Test-Path $src) { Copy-Item $src (Join-Path $toolsDst $name) -Force }
    }
}

if ($ValidateOnly) {
    Write-Host 'GokuAI Workspace Launcher validation passed.'
    Write-Host "Start script: $startScript"
    Write-Host "Converter workspace: $converterWorkspace"
    Write-Host "Sync script: $(if (Test-Path $packagingSync) { $packagingSync } elseif (Test-Path $syncScript) { $syncScript } else { 'inline fallback' })"
    exit 0
}

[System.Windows.Forms.Application]::EnableVisualStyles()

function Read-WorkspaceHistory {
    if (-not (Test-Path -LiteralPath $historyPath)) { return @() }
    try {
        $items = @(Get-Content -LiteralPath $historyPath -Raw | ConvertFrom-Json)
        return @($items | Where-Object { $_.path -and (Test-Path -LiteralPath $_.path) })
    } catch { return @() }
}

function Save-WorkspaceHistory([string]$WorkspacePath) {
    try {
        $parent = Split-Path -Parent $historyPath
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        $existing = @(Read-WorkspaceHistory | Where-Object {
            -not [string]::Equals($_.path, $WorkspacePath, [StringComparison]::OrdinalIgnoreCase)
        })
        $items = @([pscustomobject]@{
            path = $WorkspacePath
            last_opened = (Get-Date).ToString('o')
        }) + $existing
        @($items | Select-Object -First 12) | ConvertTo-Json -Depth 4 |
            Set-Content -LiteralPath $historyPath -Encoding UTF8
    } catch {
        # History is a convenience; launch must not fail if it cannot be saved.
    }
}

function Show-Error([string]$Message) {
    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        'GokuAI Workspace Launcher',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'GokuAI Workspace Launcher'
$form.StartPosition = 'CenterScreen'
$form.ClientSize = New-Object System.Drawing.Size(720, 590)
$form.MinimumSize = New-Object System.Drawing.Size(736, 629)
$form.BackColor = [System.Drawing.Color]::FromArgb(245, 247, 250)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.MaximizeBox = $false

$header = New-Object System.Windows.Forms.Panel
$header.Dock = 'Top'
$header.Height = 92
$header.BackColor = [System.Drawing.Color]::FromArgb(24, 31, 46)
$form.Controls.Add($header)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'GokuAI'
$title.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 23)
$title.ForeColor = [System.Drawing.Color]::White
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(24, 13)
$header.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = 'Open a workspace with GrokBuild + NeoForge 26.2 migration skills'
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(190, 202, 222)
$subtitle.AutoSize = $true
$subtitle.Location = New-Object System.Drawing.Point(28, 57)
$header.Controls.Add($subtitle)

$modeGroup = New-Object System.Windows.Forms.GroupBox
$modeGroup.Text = 'Workspace'
$modeGroup.Location = New-Object System.Drawing.Point(22, 110)
$modeGroup.Size = New-Object System.Drawing.Size(676, 278)
$modeGroup.Anchor = 'Top,Left,Right'
$form.Controls.Add($modeGroup)

$presetRadio = New-Object System.Windows.Forms.RadioButton
$presetRadio.Text = 'RB Legacy Converter repair (Fix-in-Grok skills preset)'
$presetRadio.Location = New-Object System.Drawing.Point(20, 28)
$presetRadio.AutoSize = $true
$presetRadio.Checked = $true
$modeGroup.Controls.Add($presetRadio)

$presetHint = New-Object System.Windows.Forms.Label
$presetHint.Text = $converterWorkspace
$presetHint.ForeColor = [System.Drawing.Color]::FromArgb(78, 89, 108)
$presetHint.Location = New-Object System.Drawing.Point(39, 52)
$presetHint.Size = New-Object System.Drawing.Size(615, 22)
$presetHint.Anchor = 'Top,Left,Right'
$modeGroup.Controls.Add($presetHint)

$existingRadio = New-Object System.Windows.Forms.RadioButton
$existingRadio.Text = 'Open an existing workspace'
$existingRadio.Location = New-Object System.Drawing.Point(20, 82)
$existingRadio.AutoSize = $true
$modeGroup.Controls.Add($existingRadio)

$existingPath = New-Object System.Windows.Forms.ComboBox
$existingPath.Location = New-Object System.Drawing.Point(39, 112)
$existingPath.Size = New-Object System.Drawing.Size(515, 28)
$existingPath.Anchor = 'Top,Left,Right'
$existingPath.DropDownStyle = 'DropDown'
$existingPath.AutoCompleteMode = 'SuggestAppend'
$existingPath.AutoCompleteSource = 'ListItems'
$modeGroup.Controls.Add($existingPath)

$browseExisting = New-Object System.Windows.Forms.Button
$browseExisting.Text = 'Browse...'
$browseExisting.Location = New-Object System.Drawing.Point(564, 111)
$browseExisting.Size = New-Object System.Drawing.Size(90, 30)
$browseExisting.Anchor = 'Top,Right'
$modeGroup.Controls.Add($browseExisting)

$newRadio = New-Object System.Windows.Forms.RadioButton
$newRadio.Text = 'Create a new workspace (migration skills synced in)'
$newRadio.Location = New-Object System.Drawing.Point(20, 154)
$newRadio.AutoSize = $true
$modeGroup.Controls.Add($newRadio)

$parentLabel = New-Object System.Windows.Forms.Label
$parentLabel.Text = 'Location'
$parentLabel.Location = New-Object System.Drawing.Point(40, 187)
$parentLabel.AutoSize = $true
$modeGroup.Controls.Add($parentLabel)

$parentPath = New-Object System.Windows.Forms.TextBox
$parentPath.Location = New-Object System.Drawing.Point(111, 183)
$parentPath.Size = New-Object System.Drawing.Size(443, 27)
$parentPath.Anchor = 'Top,Left,Right'
$parentPath.Text = Join-Path $Root 'projects'
$modeGroup.Controls.Add($parentPath)

$browseParent = New-Object System.Windows.Forms.Button
$browseParent.Text = 'Browse...'
$browseParent.Location = New-Object System.Drawing.Point(564, 182)
$browseParent.Size = New-Object System.Drawing.Size(90, 30)
$browseParent.Anchor = 'Top,Right'
$modeGroup.Controls.Add($browseParent)

$nameLabel = New-Object System.Windows.Forms.Label
$nameLabel.Text = 'Name'
$nameLabel.Location = New-Object System.Drawing.Point(40, 229)
$nameLabel.AutoSize = $true
$modeGroup.Controls.Add($nameLabel)

$workspaceName = New-Object System.Windows.Forms.TextBox
$workspaceName.Location = New-Object System.Drawing.Point(111, 225)
$workspaceName.Size = New-Object System.Drawing.Size(443, 27)
$workspaceName.Anchor = 'Top,Left,Right'
$modeGroup.Controls.Add($workspaceName)

$optionsGroup = New-Object System.Windows.Forms.GroupBox
$optionsGroup.Text = 'Launch options'
$optionsGroup.Location = New-Object System.Drawing.Point(22, 400)
$optionsGroup.Size = New-Object System.Drawing.Size(676, 90)
$optionsGroup.Anchor = 'Top,Left,Right'
$form.Controls.Add($optionsGroup)

$startBackend = New-Object System.Windows.Forms.CheckBox
$startBackend.Text = 'Load the recommended Java repair worker now'
$startBackend.Location = New-Object System.Drawing.Point(20, 28)
$startBackend.AutoSize = $true
$startBackend.Checked = $true
$optionsGroup.Controls.Add($startBackend)

$closeAfterLaunch = New-Object System.Windows.Forms.CheckBox
$closeAfterLaunch.Text = 'Close this window after GrokBuild opens'
$closeAfterLaunch.Location = New-Object System.Drawing.Point(20, 56)
$closeAfterLaunch.AutoSize = $true
$closeAfterLaunch.Checked = $true
$optionsGroup.Controls.Add($closeAfterLaunch)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Every launch syncs /repair-failed-262-output skills into the workspace (including new folders).'
$status.ForeColor = [System.Drawing.Color]::FromArgb(78, 89, 108)
$status.Location = New-Object System.Drawing.Point(24, 504)
$status.Size = New-Object System.Drawing.Size(490, 55)
$status.Anchor = 'Left,Right,Bottom'
$form.Controls.Add($status)

$openFolder = New-Object System.Windows.Forms.Button
$openFolder.Text = 'GokuAI folder'
$openFolder.Location = New-Object System.Drawing.Point(474, 524)
$openFolder.Size = New-Object System.Drawing.Size(105, 34)
$openFolder.Anchor = 'Right,Bottom'
$form.Controls.Add($openFolder)

$launch = New-Object System.Windows.Forms.Button
$launch.Text = 'Open GrokBuild'
$launch.Location = New-Object System.Drawing.Point(588, 524)
$launch.Size = New-Object System.Drawing.Size(110, 34)
$launch.Anchor = 'Right,Bottom'
$launch.BackColor = [System.Drawing.Color]::FromArgb(46, 111, 219)
$launch.ForeColor = [System.Drawing.Color]::White
$launch.FlatStyle = 'Flat'
$launch.FlatAppearance.BorderSize = 0
$form.Controls.Add($launch)
$form.AcceptButton = $launch

# Prefer converter workspace at top of history
if (Test-Path -LiteralPath $converterWorkspace) {
    [void]$existingPath.Items.Add($converterWorkspace)
}
foreach ($entry in Read-WorkspaceHistory) {
    $p = [string]$entry.path
    if (-not [string]::Equals($p, $converterWorkspace, [StringComparison]::OrdinalIgnoreCase)) {
        [void]$existingPath.Items.Add($p)
    }
}
if ($existingPath.Items.Count -gt 0) { $existingPath.SelectedIndex = 0 }

function Update-Mode {
    $isPreset = $presetRadio.Checked
    $isExisting = $existingRadio.Checked
    $isNew = $newRadio.Checked
    $existingPath.Enabled = $isExisting
    $browseExisting.Enabled = $isExisting
    $parentPath.Enabled = $isNew
    $browseParent.Enabled = $isNew
    $workspaceName.Enabled = $isNew
    if ($isPreset) {
        $status.Text = 'Preset: converter workspace + full tools sync, then GrokBuild with migration skills.'
    } elseif ($isNew) {
        $status.Text = 'New workspace: migration skills/agents will be synced in before GrokBuild opens.'
    } else {
        $status.Text = 'Existing workspace: migration skills will be refreshed before GrokBuild opens.'
    }
}

$presetRadio.Add_CheckedChanged({ Update-Mode })
$existingRadio.Add_CheckedChanged({ Update-Mode })
$newRadio.Add_CheckedChanged({ Update-Mode })
Update-Mode

$browseExisting.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose an existing project or workspace folder'
    $dialog.ShowNewFolderButton = $false
    if ($existingPath.Text -and (Test-Path -LiteralPath $existingPath.Text)) {
        $dialog.SelectedPath = $existingPath.Text
    }
    if ($dialog.ShowDialog($form) -eq 'OK') { $existingPath.Text = $dialog.SelectedPath }
})

$browseParent.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose where the new workspace will be created'
    $dialog.ShowNewFolderButton = $true
    if ($parentPath.Text -and (Test-Path -LiteralPath $parentPath.Text)) {
        $dialog.SelectedPath = $parentPath.Text
    }
    if ($dialog.ShowDialog($form) -eq 'OK') { $parentPath.Text = $dialog.SelectedPath }
})

$openFolder.Add_Click({ Start-Process -FilePath 'explorer.exe' -ArgumentList @($Root) })

$launch.Add_Click({
    try {
        $workspace = $null
        $fullTools = $false
        if ($presetRadio.Checked) {
            if (-not (Test-Path -LiteralPath $converterWorkspace -PathType Container)) {
                New-Item -ItemType Directory -Path $converterWorkspace -Force | Out-Null
            }
            $workspace = (Resolve-Path -LiteralPath $converterWorkspace).Path
            $fullTools = $true
        } elseif ($existingRadio.Checked) {
            $candidate = $existingPath.Text.Trim()
            if (-not $candidate -or -not (Test-Path -LiteralPath $candidate -PathType Container)) {
                Show-Error 'Choose an existing workspace folder.'
                return
            }
            $workspace = (Resolve-Path -LiteralPath $candidate).Path
            if ([string]::Equals($workspace, $converterWorkspace, [StringComparison]::OrdinalIgnoreCase)) {
                $fullTools = $true
            }
        } else {
            $parent = $parentPath.Text.Trim()
            $name = $workspaceName.Text.Trim()
            if (-not $parent -or -not (Test-Path -LiteralPath $parent -PathType Container)) {
                Show-Error 'Choose an existing parent location for the new workspace.'
                return
            }
            if (-not $name -or $name -in @('.', '..') -or
                $name.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0 -or
                $name.Contains('\') -or $name.Contains('/')) {
                Show-Error 'Enter a valid folder name for the new workspace.'
                return
            }
            $workspace = Join-Path (Resolve-Path -LiteralPath $parent).Path $name
            if (Test-Path -LiteralPath $workspace) {
                Show-Error 'That folder already exists. Choose "Open an existing workspace" instead.'
                return
            }
            New-Item -ItemType Directory -Path $workspace | Out-Null
        }

        $launch.Enabled = $false
        $form.UseWaitCursor = $true
        $status.Text = 'Syncing migration skills into workspace...'
        [System.Windows.Forms.Application]::DoEvents()

        Sync-MigrationSkillsIntoWorkspace -WorkspacePath $workspace -FullConverterTools:$fullTools

        $status.Text = 'Opening GrokBuild...'
        [System.Windows.Forms.Application]::DoEvents()

        Save-WorkspaceHistory $workspace
        $parameters = @{ ProjectPath = $workspace; Root = $Root }
        if (-not $startBackend.Checked) { $parameters.SkipBackendStart = $true }
        & $startScript @parameters

        $status.Text = "Opened (skills synced): $workspace"
        if ($closeAfterLaunch.Checked) { $form.Close() }
    } catch {
        $status.Text = 'Launch failed. Nothing was removed.'
        Show-Error $_.Exception.Message
    } finally {
        $launch.Enabled = $true
        $form.UseWaitCursor = $false
    }
})

[void]$form.ShowDialog()
